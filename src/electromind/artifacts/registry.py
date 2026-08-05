"""Artifact Registry — Provenance 索引（M6 §11.2）。

- 文件创建后计算 SHA-256；文件变化后必须生成新版本或更新 Digest。
- 不允许 Manifest 指向不存在的文件（``verify_integrity``）。
- 输入/输出 Artifact 形成可遍历依赖图。
- 删除或替换 Artifact 必须记录事件。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .manifest import ArtifactManifest, ArtifactStatus


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
        """注册新 Artifact。同 id 已存在（内容不同）→ 先记录替换事件。"""
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
            self._manifests[manifest.artifact_id] = manifest.supersede(by="registry")
            self._manifests[f"{manifest.artifact_id}@old"] = manifest
            return manifest
        self._manifests[manifest.artifact_id] = manifest
        self._flush()
        return manifest

    def get(self, artifact_id: str) -> ArtifactManifest | None:
        return self._manifests.get(artifact_id)

    def all(self) -> list[ArtifactManifest]:
        return list(self._manifests.values())

    def for_run(self, run_id: str) -> list[ArtifactManifest]:
        return [m for m in self._manifests.values() if m.run_id == run_id]

    def by_status(self, status: ArtifactStatus) -> list[ArtifactManifest]:
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
        """全量完整性检查；返回问题列表（空 = 全部一致）。"""
        errors: list[str] = []
        for manifest in self._manifests.values():
            try:
                self.verify_integrity(manifest, root)
            except ArtifactIntegrityError as exc:
                errors.append(str(exc))
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        lines = [
            json.dumps({**m.to_dict(), "type": "manifest"}, ensure_ascii=False)
            for m in self._manifests.values()
        ]
        lines.extend(
            json.dumps({**e, "type": "event"}, ensure_ascii=False) for e in self._events
        )
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except (ValueError, KeyError):
                continue
            if d.get("type") == "manifest":
                m = ArtifactManifest.from_dict(d)
                self._manifests[m.artifact_id] = m
            elif d.get("type") == "event":
                self._events.append(d)

    def __len__(self) -> int:
        return len(self._manifests)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()
