"""Artifact Registry — Provenance 索引（M6 §11.2）。

- 文件创建后计算 SHA-256；文件变化后必须生成新版本或更新 Digest。
- 不允许 Manifest 指向不存在的文件（``verify_integrity``）。
- 输入/输出 Artifact 形成可遍历依赖图。
- 删除或替换 Artifact 必须记录事件。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import replace
from pathlib import Path

from ..atomicfile import atomic_write_text, load_jsonl_recover
from .manifest import ArtifactManifest, ArtifactStatus

# 历史版本键：`{id}@v{n}`（n 从 1 递增，越大越新）。仅当该键的 manifest
# 处于 SUPERSEDED 终态时才算历史版本——防止与真实 basename（如 data@v2.txt）
# 撞键误判。
_VERSION_RE = re.compile(r"^(?P<base>.*)@v(?P<n>\d+)$")


class ArtifactIntegrityError(ValueError):
    """Manifest 指向的文件缺失或摘要不符。"""


class ArtifactRegistry:
    """按 artifact_id 索引 Manifest；可选磁盘持久化（JSONL）。"""

    def __init__(self, path: str | Path | None = None) -> None:
        self._manifests: dict[str, ArtifactManifest] = {}
        self._events: list[dict] = []  # 删除/替换事件记录
        self.path = Path(path) if path else None
        if self.path is not None:
            self._load()

    # ── 注册 ─────────────────────────────────────────────────────────

    def register(self, manifest: ArtifactManifest) -> ArtifactManifest:
        """注册新 Artifact。同 id 已存在（内容不同）→ 先记录替换事件。

        P0-7: 输入 Artifact 缺失不静默——记录 warning 事件（verify_all 时
        作为错误报告）。
        """
        for input_id in manifest.input_artifacts:
            if input_id not in self._manifests:
                self._events.append(
                    {
                        "event": "missing_input",
                        "artifact_id": manifest.artifact_id,
                        "input_artifact_id": input_id,
                        "at": time.time(),
                    }
                )
        existing = self._manifests.get(manifest.artifact_id)
        if existing is not None and existing.sha256 != manifest.sha256:
            self._events.append(
                {
                    "event": "replace",
                    "artifact_id": manifest.artifact_id,
                    "old_sha256": existing.sha256,
                    "new_sha256": manifest.sha256,
                    "at": time.time(),
                }
            )
            # P1.1：旧版本保留在 `{id}@v{n}` 版本链（逐次递增，全部 SUPERSEDED），
            # 新版本成为当前版本。所有旧版本都必须持久化。
            # （早期实现用单一 @old 槽——第二次替换会覆盖第一次的旧版本；
            #   再早的实现把 supersede 打在新版本上、@old 键存新内容。）
            # 历史版本以槽键为 artifact_id，保证序列化/重载后仍落在同一槽位，
            # 不会因 to_dict 里的 base id 而覆盖当前版本。
            slot_key = self._next_version_key(manifest.artifact_id)
            old_version = existing
            if existing.acceptance_status is not ArtifactStatus.SUPERSEDED:
                old_version = existing.supersede(by="registry")
            if old_version.artifact_id != slot_key:
                old_version = replace(old_version, artifact_id=slot_key)
            self._manifests[slot_key] = old_version
            self._manifests[manifest.artifact_id] = manifest
            self._flush()
            return manifest
        self._manifests[manifest.artifact_id] = manifest
        self._flush()
        return manifest

    # ── 版本历史 ──────────────────────────────────────────────────────

    def _next_version_key(self, artifact_id: str) -> str:
        """`{id}@v{n}` 中下一个未使用的 n（>= 当前最大 + 1）。"""
        n = 0
        for key in self._manifests:
            m = _VERSION_RE.match(key)
            if m and m.group("base") == artifact_id:
                n = max(n, int(m.group("n")))
        return f"{artifact_id}@v{n + 1}"

    def _is_historical(self, key: str) -> bool:
        """键是否为历史版本槽（`{id}@v{n}` 且 manifest 已 SUPERSEDED）。"""
        manifest = self._manifests.get(key)
        return (
            manifest is not None
            and manifest.acceptance_status is ArtifactStatus.SUPERSEDED
            and _VERSION_RE.match(key) is not None
        )

    def _current_manifests(self) -> dict[str, ArtifactManifest]:
        """仅当前版本（排除历史 `{id}@v{n}` 槽）。"""
        return {k: v for k, v in self._manifests.items() if not self._is_historical(k)}

    def history(self, artifact_id: str) -> list[ArtifactManifest]:
        """该 id 的所有历史版本（按版本号升序；不含当前版本）。"""
        versions: list[tuple[int, ArtifactManifest]] = []
        for key, manifest in self._manifests.items():
            m = _VERSION_RE.match(key)
            if m and m.group("base") == artifact_id and self._is_historical(key):
                versions.append((int(m.group("n")), manifest))
        versions.sort(key=lambda t: t[0])
        return [manifest for _, manifest in versions]

    def get(self, artifact_id: str) -> ArtifactManifest | None:
        return self._manifests.get(artifact_id)

    def all(self) -> list[ArtifactManifest]:
        """当前版本（不含历史 `{id}@v{n}` 槽）。"""
        return list(self._current_manifests().values())

    def for_run(self, run_id: str) -> list[ArtifactManifest]:
        return [m for m in self.all() if m.run_id == run_id]

    def by_status(self, status: ArtifactStatus) -> list[ArtifactManifest]:
        # 含历史版本：SUPERSEDED 查询应返回所有被替代的旧版本。
        return [m for m in self._manifests.values() if m.acceptance_status == status]

    def inputs_of(self, artifact_id: str) -> list[ArtifactManifest]:
        """输入 Artifact（依赖图上游）。"""
        manifest = self._manifests.get(artifact_id)
        if manifest is None:
            return []
        return [
            self._manifests[i] for i in manifest.input_artifacts if i in self._manifests
        ]

    def trace(self, artifact_id: str) -> list[str]:
        """可遍历的依赖链（输出 ← 输入，去环）。"""
        seen: set[str] = set()
        chain: list[str] = []

        def walk(aid: str) -> None:
            if aid in seen:
                return
            seen.add(aid)
            manifest = self._manifests.get(aid)
            if manifest is None:
                return
            chain.append(aid)
            for inp in manifest.input_artifacts:
                walk(inp)

        walk(artifact_id)
        return chain

    # ── 完整性 ───────────────────────────────────────────────────────

    def verify_integrity(self, manifest: ArtifactManifest, root: Path) -> None:
        """Manifest 指向的文件必须存在且 SHA-256 匹配。"""
        path = Path(manifest.path)
        if not path.is_absolute():
            path = root / path
        if not path.exists():
            raise ArtifactIntegrityError(
                f"artifact {manifest.artifact_id} 指向不存在的文件: {path}"
            )
        actual = sha256_file(path)
        if actual != manifest.sha256:
            raise ArtifactIntegrityError(
                f"artifact {manifest.artifact_id} 摘要不符: "
                f"manifest={manifest.sha256} 实际={actual}"
            )

    def verify_all(self, root: Path) -> list[str]:
        """全量完整性检查；返回问题列表（空 = 全部一致）。

        P0-7: 输入 Artifact 缺失同样作为错误报告（不静默忽略）。
        """
        errors: list[str] = []
        for manifest in self.all():
            try:
                self.verify_integrity(manifest, root)
            except ArtifactIntegrityError as exc:
                errors.append(str(exc))
            for input_id in manifest.input_artifacts:
                if input_id not in self._manifests:
                    errors.append(
                        f"artifact {manifest.artifact_id} 的输入 {input_id} 缺失"
                    )
        return errors

    # ── 事件 ─────────────────────────────────────────────────────────

    def delete(self, artifact_id: str, *, reason: str) -> bool:
        """删除 Artifact（记录事件后移除索引）。"""
        if artifact_id not in self._manifests:
            return False
        self._events.append(
            {
                "event": "delete",
                "artifact_id": artifact_id,
                "reason": reason,
                "at": time.time(),
            }
        )
        del self._manifests[artifact_id]
        self._flush()
        return True

    def events(self) -> list[dict]:
        return list(self._events)

    # ── 持久化 ──────────────────────────────────────────────────────

    def _flush(self) -> None:
        if self.path is None:
            return
        lines = [
            json.dumps({**m.to_dict(), "type": "manifest"}, ensure_ascii=False)
            for m in self._manifests.values()
        ]
        lines.extend(
            json.dumps({**e, "type": "event"}, ensure_ascii=False) for e in self._events
        )
        # P1.2/P1.3: 原子写 + .bak 备份（损坏恢复用）。
        atomic_write_text(
            self.path, "\n".join(lines) + "\n", encoding="utf-8", backup=True
        )

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        # P1.3: 整份损坏 → 自动尝试 .bak（load_jsonl_recover）；单条损坏
        # fail-soft 跳过，不阻塞恢复。
        for d in load_jsonl_recover(self.path, parse_line=json.loads):
            if d.get("type") == "manifest":
                m = ArtifactManifest.from_dict(d)
                self._manifests[m.artifact_id] = m
            elif d.get("type") == "event":
                self._events.append(d)

    def __len__(self) -> int:
        return len(self._current_manifests())


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()
