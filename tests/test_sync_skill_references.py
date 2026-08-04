"""W1 tests: byte-level deterministic knowledge reference sync.

Design: docs/superpowers/specs/2026-08-04-skill-aplus-self-contained-design.md
(W1 / 约束 2、3) — 全文复制、无头注、显式 TOML 映射、`--check` 六项验证只读。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "sync-skill-references.py"

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _tree(root: Path, files: dict[str, str]) -> None:
    """Create a repo-like file tree under *root* from relative path→content."""
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def _run(root: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *extra],
        capture_output=True,
        text=True,
    )


def _map_toml(*entries: tuple[str, list[str]]) -> str:
    lines = []
    for source, targets in entries:
        lines.append("[[references]]")
        lines.append(f'source = "{source}"')
        lines.append("targets = [")
        for t in targets:
            lines.append(f'  "{t}",')
        lines.append("]")
    return "\n".join(lines) + "\n"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _manifest(root: Path) -> dict:
    p = root / "skills" / "knowledge" / "sync-manifest.json"
    assert p.is_file(), f"manifest missing at {p}"
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# --check: 六项验证
# ---------------------------------------------------------------------------


class TestCheckBasics:
    def test_all_clean_passes(self, tmp_path):
        """干净状态：源、目标、SHA、manifest 全部一致 → 退出 0。"""
        src = "skills/knowledge/electronic-structure.md"
        tgt = "skills/tools/cp2k/references/knowledge/electronic-structure.md"
        body = "# Electronic structure\n\nβeta content.\n"
        _tree(
            tmp_path,
            {
                "skills/knowledge/sync-map.toml": _map_toml((src, [tgt])),
                src: body,
                tgt: body,
            },
        )
        # 先 sync 生成 manifest，再 check
        assert _run(tmp_path).returncode == 0
        proc = _run(tmp_path, "--check")
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_missing_source(self, tmp_path):
        """检查 1：源文件缺失 → 退出 1。"""
        src = "skills/knowledge/electronic-structure.md"
        tgt = "skills/tools/cp2k/references/knowledge/electronic-structure.md"
        _tree(
            tmp_path,
            {"skills/knowledge/sync-map.toml": _map_toml((src, [tgt])), tgt: "x"},
        )
        proc = _run(tmp_path, "--check")
        assert proc.returncode == 1
        assert "source" in (proc.stdout + proc.stderr).lower()

    def test_missing_target(self, tmp_path):
        """检查 2：目标文件缺失 → 退出 1。"""
        src = "skills/knowledge/electronic-structure.md"
        tgt = "skills/tools/cp2k/references/knowledge/electronic-structure.md"
        _tree(
            tmp_path,
            {"skills/knowledge/sync-map.toml": _map_toml((src, [tgt])), src: "y"},
        )
        proc = _run(tmp_path, "--check")
        assert proc.returncode == 1
        assert "target" in (proc.stdout + proc.stderr).lower()

    def test_sha_mismatch(self, tmp_path):
        """检查 3：源与目标 SHA-256 不同 → 退出 1。"""
        src = "skills/knowledge/electronic-structure.md"
        tgt = "skills/tools/cp2k/references/knowledge/electronic-structure.md"
        _tree(
            tmp_path,
            {
                "skills/knowledge/sync-map.toml": _map_toml((src, [tgt])),
                src: "original content",
                tgt: "tampered content",
            },
        )
        proc = _run(tmp_path, "--check")
        assert proc.returncode == 1

    def test_duplicate_conflicting_target(self, tmp_path):
        """检查 4：同一 target 被两个 source 声明 → 退出 1。"""
        tgt = "skills/tools/cp2k/references/knowledge/electronic-structure.md"
        _tree(
            tmp_path,
            {
                "skills/knowledge/sync-map.toml": _map_toml(
                    ("skills/knowledge/a.md", [tgt]),
                    ("skills/knowledge/b.md", [tgt]),
                ),
                "skills/knowledge/a.md": "a",
                "skills/knowledge/b.md": "b",
            },
        )
        proc = _run(tmp_path, "--check")
        assert proc.returncode == 1

    def test_undeclared_generated_copy(self, tmp_path):
        """检查 5：sync 之后新出现的、manifest 未记录的文件 → 退出 1。"""
        src = "skills/knowledge/electronic-structure.md"
        tgt = "skills/tools/cp2k/references/knowledge/electronic-structure.md"
        _tree(
            tmp_path,
            {
                "skills/knowledge/sync-map.toml": _map_toml((src, [tgt])),
                src: "ok",
                tgt: "ok",
            },
        )
        _run(tmp_path)  # 正常 sync
        # 之后有人放入未声明文件（sync 会剪除它，check 必须单独报错）
        rogue = tmp_path / "skills/tools/vasp/references/knowledge/rogue.md"
        rogue.parent.mkdir(parents=True, exist_ok=True)
        rogue.write_text("not declared anywhere", encoding="utf-8")
        proc = _run(tmp_path, "--check")
        assert proc.returncode == 1
        assert "undeclared" in (proc.stdout + proc.stderr).lower()

    def test_stale_copy_after_map_removal(self, tmp_path):
        """检查 6：映射已删除但 manifest/副本仍在 → 退出 1。"""
        src = "skills/knowledge/electronic-structure.md"
        tgt = "skills/tools/cp2k/references/knowledge/electronic-structure.md"
        _tree(
            tmp_path,
            {
                "skills/knowledge/sync-map.toml": _map_toml((src, [tgt])),
                src: "ok",
                tgt: "ok",
            },
        )
        _run(tmp_path)  # 先同步，产生 manifest + 副本
        # 映射删除该条，但副本与 manifest 记录仍在
        (tmp_path / "skills/knowledge/sync-map.toml").write_text(
            _map_toml(), encoding="utf-8"
        )
        proc = _run(tmp_path, "--check")
        assert proc.returncode == 1
        assert "stale" in (proc.stdout + proc.stderr).lower()

    def test_check_is_read_only(self, tmp_path):
        """--check 只读：运行前后工作树字节级不变。"""
        src = "skills/knowledge/electronic-structure.md"
        tgt = "skills/tools/cp2k/references/knowledge/electronic-structure.md"
        body = "# doc\n"
        files = {
            "skills/knowledge/sync-map.toml": _map_toml((src, [tgt])),
            src: body,
            tgt: body,
        }
        _tree(tmp_path, files)
        _run(tmp_path)  # 同步一次，制造不干净状态（删掉 manifest 会失败）
        # 加入一个未声明副本，使 --check 处于失败路径（更容易观测写行为）
        rogue = tmp_path / "skills/tools/vasp/references/knowledge/rogue.md"
        rogue.parent.mkdir(parents=True, exist_ok=True)
        rogue.write_text("rogue", encoding="utf-8")

        before: dict[str, bytes] = {}
        for p in tmp_path.rglob("*"):
            if p.is_file():
                before[str(p)] = p.read_bytes()
        proc = _run(tmp_path, "--check")
        assert proc.returncode == 1  # 失败路径也不得写
        for p in tmp_path.rglob("*"):
            if p.is_file() and str(p) in before:
                assert p.read_bytes() == before[str(p)], f"file modified: {p}"
        # 且不得新增任何文件（如 manifest）
        now = {str(p) for p in tmp_path.rglob("*") if p.is_file()}
        assert now == set(before)

    def test_missing_map_file(self, tmp_path):
        """映射文件缺失 → 明确错误、退出 1。"""
        proc = _run(tmp_path, "--check")
        assert proc.returncode == 1
        assert "map" in (proc.stdout + proc.stderr).lower()

    def test_malformed_map(self, tmp_path):
        """映射 TOML 语法错误 → 退出 1。"""
        _tree(
            tmp_path,
            {
                "skills/knowledge/sync-map.toml": "[[references]\nsource = 1\n",
            },
        )
        proc = _run(tmp_path, "--check")
        assert proc.returncode == 1


# ---------------------------------------------------------------------------
# sync: 字节级复制、剪除、manifest、幂等
# ---------------------------------------------------------------------------


class TestSync:
    def test_copies_bytes_exactly(self, tmp_path):
        """目标字节 == 源字节（含非 ASCII；无自动头注）。"""
        src = "skills/knowledge/electronic-structure.md"
        tgt = "skills/tools/cp2k/references/knowledge/electronic-structure.md"
        body = "# 电子结构\n\n## band gap\n\n$$ E_g \\approx 1.1\\,\\text{eV} $$\n"
        _tree(
            tmp_path,
            {"skills/knowledge/sync-map.toml": _map_toml((src, [tgt])), src: body},
        )
        proc = _run(tmp_path)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        copied = (tmp_path / tgt).read_bytes()
        assert copied == body.encode("utf-8")
        assert not copied.startswith(b"Generated from")
        assert not copied.startswith(b"Do not edit")

    def test_manifest_records_source_and_sha(self, tmp_path):
        """manifest 记录 target → {source, sha256}，sha 等于源文件。"""
        src = "skills/knowledge/electronic-structure.md"
        tgt = "skills/tools/cp2k/references/knowledge/electronic-structure.md"
        body = "# doc\n"
        _tree(
            tmp_path,
            {"skills/knowledge/sync-map.toml": _map_toml((src, [tgt])), src: body},
        )
        _run(tmp_path)
        entries = _manifest(tmp_path)["entries"]
        assert tgt in entries
        assert entries[tgt]["source"] == src
        assert entries[tgt]["sha256"] == _sha(body)

    def test_multiple_targets_and_sources(self, tmp_path):
        """一条 source 多个 target；多条 source 各自复制。"""
        src = "skills/knowledge/electronic-structure.md"
        body = "# es\n"
        targets = [
            "skills/tools/cp2k/references/knowledge/electronic-structure.md",
            "skills/tools/vasp/references/knowledge/electronic-structure.md",
        ]
        src2 = "skills/knowledge/bonding-analysis.md"
        tgt2 = "skills/tools/lobster/references/knowledge/bonding-analysis.md"
        _tree(
            tmp_path,
            {
                "skills/knowledge/sync-map.toml": _map_toml(
                    (src, targets), (src2, [tgt2])
                ),
                src: body,
                src2: "# ba\n",
            },
        )
        assert _run(tmp_path).returncode == 0
        for t in targets:
            assert (tmp_path / t).read_text(encoding="utf-8") == body
        assert (tmp_path / tgt2).read_text(encoding="utf-8") == "# ba\n"

    def test_sync_prunes_undeclared_files(self, tmp_path):
        """同步剪除未声明副本：sync 后 --check 全绿。"""
        src = "skills/knowledge/electronic-structure.md"
        tgt = "skills/tools/cp2k/references/knowledge/electronic-structure.md"
        rogue = tmp_path / "skills/tools/cp2k/references/knowledge/rogue.md"
        _tree(
            tmp_path,
            {
                "skills/knowledge/sync-map.toml": _map_toml((src, [tgt])),
                src: "ok",
                tgt: "ok",
            },
        )
        rogue.parent.mkdir(parents=True, exist_ok=True)
        rogue.write_text("rogue", encoding="utf-8")
        assert _run(tmp_path).returncode == 0
        assert not rogue.exists()
        assert _run(tmp_path, "--check").returncode == 0

    def test_sync_removes_stale_targets(self, tmp_path):
        """映射删除条目后 sync 移除陈旧副本与 manifest 记录。"""
        src = "skills/knowledge/electronic-structure.md"
        tgt = "skills/tools/cp2k/references/knowledge/electronic-structure.md"
        _tree(
            tmp_path,
            {
                "skills/knowledge/sync-map.toml": _map_toml((src, [tgt])),
                src: "ok",
            },
        )
        assert _run(tmp_path).returncode == 0
        assert (tmp_path / tgt).is_file()
        # 删除映射条目
        (tmp_path / "skills/knowledge/sync-map.toml").write_text(
            _map_toml(), encoding="utf-8"
        )
        assert _run(tmp_path).returncode == 0
        assert not (tmp_path / tgt).exists()
        assert _manifest(tmp_path)["entries"] == {}
        assert _run(tmp_path, "--check").returncode == 0

    def test_sync_idempotent(self, tmp_path):
        """幂等：第二次 sync 不产生任何字节变化。"""
        src = "skills/knowledge/electronic-structure.md"
        tgt = "skills/tools/cp2k/references/knowledge/electronic-structure.md"
        _tree(
            tmp_path,
            {
                "skills/knowledge/sync-map.toml": _map_toml((src, [tgt])),
                src: "# doc\n",
            },
        )
        assert _run(tmp_path).returncode == 0
        before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
        assert _run(tmp_path).returncode == 0
        after = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
        assert after == before

    def test_sync_rejects_conflicting_map_without_writing(self, tmp_path):
        """冲突映射：sync 退出 1 且工作树零变化。"""
        tgt = "skills/tools/cp2k/references/knowledge/electronic-structure.md"
        files = {
            "skills/knowledge/sync-map.toml": _map_toml(
                ("skills/knowledge/a.md", [tgt]),
                ("skills/knowledge/b.md", [tgt]),
            ),
            "skills/knowledge/a.md": "a",
            "skills/knowledge/b.md": "b",
        }
        _tree(tmp_path, files)
        before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
        proc = _run(tmp_path)
        assert proc.returncode == 1
        for p in tmp_path.rglob("*"):
            if p.is_file() and str(p) in before:
                assert p.read_bytes() == before[str(p)]
        assert {str(p) for p in tmp_path.rglob("*") if p.is_file()} == set(before)

    def test_relative_layout_preserved_in_target_dir(self, tmp_path):
        """相对目录关系保持：互链文档落在同一 references/knowledge/ 目录。"""
        src1 = "skills/knowledge/electronic-structure.md"
        src2 = "skills/knowledge/bonding-analysis.md"
        tgt_dir = "skills/tools/lobster/references/knowledge"
        _tree(
            tmp_path,
            {
                "skills/knowledge/sync-map.toml": _map_toml(
                    (src1, [f"{tgt_dir}/electronic-structure.md"]),
                    (src2, [f"{tgt_dir}/bonding-analysis.md"]),
                ),
                src1: "# es\n\nsee [bonding](bonding-analysis.md)\n",
                src2: "# ba\n",
            },
        )
        assert _run(tmp_path).returncode == 0
        assert (tmp_path / tgt_dir / "electronic-structure.md").is_file()
        assert (tmp_path / tgt_dir / "bonding-analysis.md").is_file()

    def test_missing_source_fails_sync_cleanly(self, tmp_path):
        """源缺失：sync 报错退出 1，不产生半同步状态。"""
        tgt = "skills/tools/cp2k/references/knowledge/electronic-structure.md"
        _tree(
            tmp_path,
            {
                "skills/knowledge/sync-map.toml": _map_toml(
                    ("skills/knowledge/ghost.md", [tgt])
                )
            },
        )
        proc = _run(tmp_path)
        assert proc.returncode == 1
        assert not (tmp_path / tgt).exists()


# ---------------------------------------------------------------------------
# P0-1: 路径穿越 / symlink / 原子写入
# ---------------------------------------------------------------------------


class TestPathSafety:
    def test_absolute_source_rejected(self, tmp_path):
        """绝对路径 source → 拒绝（P0-1）。"""
        _tree(
            tmp_path,
            {
                "skills/knowledge/sync-map.toml": _map_toml(
                    ("/etc/passwd", ["skills/tools/cp2k/references/knowledge/x.md"])
                )
            },
        )
        proc = _run(tmp_path, "--check")
        assert proc.returncode == 1
        assert "repo-root relative" in (proc.stdout + proc.stderr).lower()

    def test_dotdot_source_rejected(self, tmp_path):
        """`..` 穿越 source → 拒绝。"""
        _tree(
            tmp_path,
            {
                "skills/knowledge/sync-map.toml": _map_toml(
                    (
                        "skills/../knowledge/x.md",
                        ["skills/tools/cp2k/references/knowledge/x.md"],
                    )
                )
            },
        )
        proc = _run(tmp_path, "--check")
        assert proc.returncode == 1
        assert "'..'" in (proc.stdout + proc.stderr)

    def test_source_outside_knowledge_rejected(self, tmp_path):
        """source 不在 skills/knowledge/ 下 → 拒绝。"""
        _tree(
            tmp_path,
            {
                "skills/knowledge/sync-map.toml": _map_toml(
                    (
                        "skills/tools/cp2k/SKILL.md",
                        ["skills/tools/cp2k/references/knowledge/x.md"],
                    )
                )
            },
        )
        proc = _run(tmp_path, "--check")
        assert proc.returncode == 1
        assert "under skills/knowledge" in (proc.stdout + proc.stderr)

    def test_target_escape_rejected(self, tmp_path):
        """target 逃出 references/knowledge/（含 .. 与绝对路径）→ 拒绝。"""
        _tree(
            tmp_path,
            {
                "skills/knowledge/sync-map.toml": _map_toml(
                    ("skills/knowledge/x.md", ["../../outside.md"])
                ),
                "skills/knowledge/x.md": "x",
            },
        )
        proc = _run(tmp_path, "--check")
        assert proc.returncode == 1
        assert "'..'" in (proc.stdout + proc.stderr)

    def test_target_wrong_shape_rejected(self, tmp_path):
        """target 不是 skills/{procedures,tools}/<skill>/references/knowledge/<f> → 拒绝。"""
        _tree(
            tmp_path,
            {
                "skills/knowledge/sync-map.toml": _map_toml(
                    ("skills/knowledge/x.md", ["skills/tools/cp2k/references/other.md"])
                ),
                "skills/knowledge/x.md": "x",
            },
        )
        proc = _run(tmp_path, "--check")
        assert proc.returncode == 1
        assert "references/knowledge" in (proc.stdout + proc.stderr)

    def test_symlink_target_rejected(self, tmp_path):
        """symlink 目标 → 拒绝（不跟随写入）。"""
        src = "skills/knowledge/x.md"
        tgt = "skills/tools/cp2k/references/knowledge/x.md"
        _tree(
            tmp_path,
            {"skills/knowledge/sync-map.toml": _map_toml((src, [tgt])), src: "x"},
        )
        outside = tmp_path / "outside.md"
        outside.write_text("pwned", encoding="utf-8")
        (tmp_path / tgt).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / tgt).symlink_to(outside)
        proc = _run(tmp_path)
        assert proc.returncode == 1
        assert "symlink" in (proc.stdout + proc.stderr).lower()
        assert outside.read_text(encoding="utf-8") == "pwned"  # 未被覆盖

    def test_symlink_source_rejected(self, tmp_path):
        """symlink source → 拒绝。"""
        src = "skills/knowledge/x.md"
        tgt = "skills/tools/cp2k/references/knowledge/x.md"
        _tree(
            tmp_path,
            {"skills/knowledge/sync-map.toml": _map_toml((src, [tgt]))},
        )
        outside = tmp_path / "outside.md"
        outside.write_text("pwned", encoding="utf-8")
        (tmp_path / src).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / src).symlink_to(outside)
        proc = _run(tmp_path)
        assert proc.returncode == 1
        assert "symlink" in (proc.stdout + proc.stderr).lower()

    def test_atomic_copy_leaves_no_partial_file_on_failure(self, tmp_path):
        """原子写入：目标路径被文件占据时失败且不产生半成品（P0-1）。"""
        src = "skills/knowledge/x.md"
        tgt = "skills/tools/cp2k/references/knowledge/x.md"
        _tree(
            tmp_path,
            {
                "skills/knowledge/sync-map.toml": _map_toml((src, [tgt])),
                src: "x",
            },
        )
        # 让目标技能目录变成文件，迫使 mkdir 失败
        blocker = tmp_path / "skills" / "tools" / "cp2k"
        blocker.mkdir(parents=True, exist_ok=True)
        for child in blocker.rglob("*"):
            if child.is_file():
                child.unlink()
        blocker.rmdir()
        blocker.write_text("not a dir", encoding="utf-8")
        proc = _run(tmp_path)
        assert proc.returncode == 1
        # 不产生任何 .sync-*.tmp 残留
        leftovers = list(tmp_path.rglob(".sync-*.tmp"))
        assert leftovers == []
        # 且目标文件从未被写入
        assert not (tmp_path / tgt).exists()
