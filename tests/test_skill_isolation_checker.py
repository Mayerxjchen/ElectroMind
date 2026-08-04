"""W2 tests: skill isolation checker + markdown reference closure.

Design: docs/superpowers/specs/2026-08-04-skill-aplus-self-contained-design.md
(W2 / 约束 3、10) — 扫描面 SKILL.md / references/** / scripts/** / examples**；
上下文感知（Markdown 链接、代码路径字面量、shell 命令参数、已知模板变量、
自然语言 prose），避免对说明性文本误报。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check-skill-isolation.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True
    )


def _skill(root: Path, name: str = "foo", files: dict[str, str] | None = None) -> Path:
    """Create a skill dir under *root*; returns its path."""
    skill = root / "skills" / "tools" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test skill\n---\n# Foo\n",
        encoding="utf-8",
    )
    for rel, content in (files or {}).items():
        p = skill / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return skill


# ---------------------------------------------------------------------------
# Markdown：链接闭包 + 上下文感知
# ---------------------------------------------------------------------------


class TestMarkdownClosure:
    def test_clean_skill_passes(self, tmp_path):
        """干净 skill：in-skill 链接、代码路径、prose 全部通过。"""
        skill = _skill(
            tmp_path,
            files={
                "references/running.md": "# Running\n",
                "examples/README.md": "Run `uv run ../scripts/check.py`.\n",
                "SKILL.md": (
                    "# Foo\n\n"
                    "See [running](references/running.md).\n\n"
                    "Use `references/running.md` for details.\n\n"
                    "The tools/ directory is not part of this skill; "
                    "knowledge/ is never binding.\n"
                ),
            },
        )
        proc = _run(str(skill))
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_link_escaping_skill_root(self, tmp_path):
        """链接逃逸 skill 根（../../.. 越界）→ 失败。"""
        skill = _skill(
            tmp_path, files={"SKILL.md": "# Foo\n\n[outside](../../../outside.md)\n"}
        )
        proc = _run(str(skill))
        assert proc.returncode == 1

    def test_link_to_missing_file(self, tmp_path):
        """链接目标在 skill 内但不存在（闭包破坏）→ 失败。"""
        skill = _skill(
            tmp_path, files={"SKILL.md": "# Foo\n\n[x](references/missing.md)\n"}
        )
        proc = _run(str(skill))
        assert proc.returncode == 1
        assert "not found" in (proc.stdout + proc.stderr).lower()

    def test_absolute_link_rejected(self, tmp_path):
        """绝对路径链接（/etc/...）→ 失败。"""
        skill = _skill(tmp_path, files={"SKILL.md": "# Foo\n\n[x](/etc/passwd)\n"})
        proc = _run(str(skill))
        assert proc.returncode == 1

    def test_reference_style_link_closure(self, tmp_path):
        """引用式链接 [id]: dest 同样参与闭包检查。"""
        skill = _skill(
            tmp_path,
            files={
                "references/running.md": "# Running\n",
                "SKILL.md": ("# Foo\n\n[running][r]\n\n[r]: references/running.md\n"),
            },
        )
        assert _run(str(skill)).returncode == 0
        (skill / "references" / "running.md").unlink()
        proc = _run(str(skill))
        assert proc.returncode == 1

    def test_link_relative_from_deep_dir_in_skill(self, tmp_path):
        """深层目录的相对链接可向上解析到 skill 内 → 通过。"""
        skill = _skill(
            tmp_path,
            files={
                "references/volumetric-visualization.md": "# VV\n",
                "references/knowledge/foo.md": (
                    "# Foo\n\n[vol](../volumetric-visualization.md)\n"
                ),
            },
        )
        assert _run(str(skill)).returncode == 0

    def test_fenced_code_block_not_parsed_as_links(self, tmp_path):
        """代码块内的 [x](missing.md) 是代码，不参与链接闭包。"""
        skill = _skill(
            tmp_path,
            files={
                "SKILL.md": (
                    "# Foo\n\n```python\n"
                    'print("see [fake](references/missing.md)")\n'
                    "```\n"
                )
            },
        )
        assert _run(str(skill)).returncode == 0

    def test_external_links_skipped(self, tmp_path):
        """外部 URL 链接（http/mailto）不参与闭包。"""
        skill = _skill(
            tmp_path,
            files={
                "SKILL.md": (
                    "# Foo\n\n"
                    "[manual](https://manual.example.com/run.md)\n\n"
                    "<mailto:help@example.com>\n"
                )
            },
        )
        assert _run(str(skill)).returncode == 0


class TestMarkdownContexts:
    def test_code_span_collection_ref_rejected(self, tmp_path):
        """代码 span 中的 `knowledge/foo.md`（根相对 collection 引用）→ 失败。"""
        skill = _skill(
            tmp_path,
            files={"SKILL.md": "# Foo\n\nscience: `knowledge/foo.md`\n"},
        )
        proc = _run(str(skill))
        assert proc.returncode == 1
        assert "knowledge" in (proc.stdout + proc.stderr).lower()

    def test_in_skill_reference_prefix_passes(self, tmp_path):
        """`references/knowledge/foo.md` 是 in-skill 路径 → 通过。"""
        skill = _skill(
            tmp_path,
            files={"SKILL.md": "# Foo\n\nscience: `references/knowledge/foo.md`\n"},
        )
        assert _run(str(skill)).returncode == 0

    def test_prose_collection_mention_not_flagged(self, tmp_path):
        """说明性文本中的 tools/、procedures/、knowledge/ 不误报。"""
        skill = _skill(
            tmp_path,
            files={
                "SKILL.md": (
                    "# Foo\n\n"
                    "The procedures/ and tools/ collections ship extra skills; "
                    "knowledge/ is shared reference material and never binding.\n"
                )
            },
        )
        assert _run(str(skill)).returncode == 0

    def test_skills_root_template_rejected(self, tmp_path):
        """`{skills_root}` 模板变量 → 失败。"""
        skill = _skill(
            tmp_path,
            files={"SKILL.md": "# Foo\n\nmount at `{skills_root}`\n"},
        )
        proc = _run(str(skill))
        assert proc.returncode == 1
        assert "skills_root" in (proc.stdout + proc.stderr).lower()

    def test_file_uri_rejected(self, tmp_path):
        """`file:///` URI → 失败。"""
        skill = _skill(
            tmp_path,
            files={"SKILL.md": "# Foo\n\nsee file:///etc/hosts\n"},
        )
        proc = _run(str(skill))
        assert proc.returncode == 1

    def test_user_absolute_paths_rejected(self, tmp_path):
        """/Users/... 与 /home/... → 失败（禁止具体用户路径）。"""
        skill = _skill(
            tmp_path,
            files={
                "SKILL.md": (
                    "# Foo\n\n"
                    "a: /Users/chenxuanjie/projects/x\n"
                    "b: /home/zhang/cluster\n"
                )
            },
        )
        proc = _run(str(skill))
        assert proc.returncode == 1


# ---------------------------------------------------------------------------
# 代码：Python / Shell / 示例数据
# ---------------------------------------------------------------------------


class TestCodeContexts:
    def test_python_escape_literal(self, tmp_path):
        """Python 字符串字面量 `../../../../x` 越界 → 失败。"""
        skill = _skill(
            tmp_path,
            files={
                "references/knowledge/foo.md": "# ok\n",
                "scripts/run.py": '#!/usr/bin/env python3\nP = "../../../../outside.txt"\n',
            },
        )
        proc = _run(str(skill))
        assert proc.returncode == 1

    def test_python_in_skill_relative_passes(self, tmp_path):
        """Python 字符串 `../data` 在允许深度内 → 通过。"""
        skill = _skill(
            tmp_path,
            files={
                "scripts/run.py": '#!/usr/bin/env python3\nP = "../data/input.json"\n'
            },
        )
        assert _run(str(skill)).returncode == 0

    def test_python_collection_path_literal(self, tmp_path):
        """`Path("skills/tools/cp2k/...")` collection 引用 → 失败。"""
        skill = _skill(
            tmp_path,
            files={
                "scripts/run.py": (
                    "#!/usr/bin/env python3\n"
                    "from pathlib import Path\n"
                    'P = Path("skills/tools/cp2k/scripts/parse_cp2k.py")\n'
                )
            },
        )
        proc = _run(str(skill))
        assert proc.returncode == 1

    def test_python_local_path_literal_passes(self, tmp_path):
        """`Path("references/knowledge/x.md")` in-skill → 通过。"""
        skill = _skill(
            tmp_path,
            files={
                "scripts/run.py": (
                    "#!/usr/bin/env python3\n"
                    "from pathlib import Path\n"
                    'P = Path("references/knowledge/x.md")\n'
                )
            },
        )
        assert _run(str(skill)).returncode == 0

    def test_python_cross_skill_import(self, tmp_path):
        """跨 skill import（tools.cp2k / skills.tools）→ 失败。"""
        skill = _skill(
            tmp_path,
            files={
                "scripts/run.py": (
                    "#!/usr/bin/env python3\nimport tools.cp2k.scripts.parse_cp2k\n"
                )
            },
        )
        proc = _run(str(skill))
        assert proc.returncode == 1
        assert "import" in (proc.stdout + proc.stderr).lower()

    def test_python_local_import_passes(self, tmp_path):
        """本 skill 内 import → 通过。"""
        skill = _skill(
            tmp_path,
            files={
                "scripts/parse_cp2k.py": "# local\n",
                "scripts/run.py": (
                    "#!/usr/bin/env python3\nimport parse_cp2k\nfrom . import x\n"
                ),
            },
        )
        assert _run(str(skill)).returncode == 0

    def test_shell_user_project_relative_passes(self, tmp_path):
        """Shell 参数 `../is/CONTCAR`（用户计算目录，允许深度内）→ 通过。"""
        skill = _skill(
            tmp_path,
            files={
                "references/vtst-neb-dimer.md": (
                    "# NEB\n\n```bash\nnebmake.pl ../is/CONTCAR ../fs/CONTCAR 4\n```\n"
                )
            },
        )
        assert _run(str(skill)).returncode == 0

    def test_shell_comment_ignored(self, tmp_path):
        """Shell 注释中的 collection 提及 → 通过。"""
        skill = _skill(
            tmp_path,
            files={
                "scripts/run.sh": "#!/usr/bin/env bash\n# see knowledge/ for science\ncp input.inp output/\n"
            },
        )
        assert _run(str(skill)).returncode == 0

    def test_example_json_user_data_paths(self, tmp_path):
        """示例数据中 `../00.data/...`（用户数据目录）→ 通过。"""
        skill = _skill(
            tmp_path,
            files={
                "examples/input.json": (
                    '{"systems": ["../00.data/training_data"], "numb_steps": 1}\n'
                )
            },
        )
        assert _run(str(skill)).returncode == 0

    def test_example_collection_path_rejected(self, tmp_path):
        """示例数据中 `skills/knowledge/x.md` → 失败。"""
        skill = _skill(
            tmp_path,
            files={"examples/input.json": '{"path": "skills/knowledge/x.md"}\n'},
        )
        proc = _run(str(skill))
        assert proc.returncode == 1


# ---------------------------------------------------------------------------
# 全量扫描 / 健壮性
# ---------------------------------------------------------------------------


class TestScanAll:
    def test_name_directory_mismatch_reported(self, tmp_path):
        """A+ W3：frontmatter name ≠ 目录名 → 违规、退出 1。"""
        skill = _skill(tmp_path)
        (skill / "SKILL.md").write_text(
            "---\nname: other-name\ndescription: Test\n---\n# Foo\n",
            encoding="utf-8",
        )
        proc = _run(str(skill))
        assert proc.returncode == 1
        assert "does not match directory" in (proc.stdout + proc.stderr)

    def test_broken_skill_found_in_scan_all(self, tmp_path):
        """默认全量扫描：坏 skill 被报出、好 skill 通过，退出 1。"""
        _skill(tmp_path, name="good")
        _skill(
            tmp_path,
            name="bad",
            files={"SKILL.md": "# Bad\n\n[x](references/missing.md)\n"},
        )
        proc = _run("--repo", str(tmp_path))
        assert proc.returncode == 1
        out = proc.stdout + proc.stderr
        assert "bad" in out
        assert "good" not in out.split("bad:")[0]

    def test_clean_repo_passes(self, tmp_path):
        """全量扫描干净仓库 → 退出 0。"""
        _skill(tmp_path, name="good", files={"references/running.md": "# R\n"})
        proc = _run("--repo", str(tmp_path))
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_binary_example_skipped(self, tmp_path):
        """二进制文件（含 NUL）跳过，不崩溃。"""
        skill = _skill(tmp_path)
        blob = skill / "examples" / "data.bin"
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(b"\x00\x01\x02\xff")
        assert _run(str(skill)).returncode == 0

    def test_unparseable_python_skipped(self, tmp_path):
        """语法错误的 Python 文件跳过（隔离检查不背语法错误）。"""
        skill = _skill(
            tmp_path,
            files={"scripts/broken.py": "def (\n"},
        )
        assert _run(str(skill)).returncode == 0

    def test_missing_skill_dir_reports(self, tmp_path):
        """不存在的 skill 目录 → 明确错误、退出 1。"""
        proc = _run(str(tmp_path / "skills" / "tools" / "ghost"))
        assert proc.returncode == 1


# ---------------------------------------------------------------------------
# P1-3: placeholder 前缀漏检 + symlink 拒绝
# ---------------------------------------------------------------------------


class TestPlaceholderAndSymlinks:
    def test_repo_root_placeholder_collection_ref_rejected(self, tmp_path):
        """`{repo_root}/tools/...`（跨 skill collection 引用）→ 失败。"""
        skill = _skill(
            tmp_path,
            files={
                "references/task-protocol.md": (
                    "# T\n\n`uv run {repo_root}/tools/vasp/scripts/check_inputs.py`\n"
                )
            },
        )
        proc = _run(str(skill))
        assert proc.returncode == 1
        assert "collection reference" in (proc.stdout + proc.stderr).lower()

    def test_repo_root_placeholder_dotdot_escape_rejected(self, tmp_path):
        """`{repo_root}/../scripts/...`（placeholder 后逃逸）→ 失败。"""
        skill = _skill(
            tmp_path,
            files={
                "references/task-protocol.md": (
                    "# T\n\n`uv run {repo_root}/../scripts/check_pre_submit.py`\n"
                )
            },
        )
        proc = _run(str(skill))
        assert proc.returncode == 1
        assert "placeholder" in (proc.stdout + proc.stderr).lower()

    def test_repo_root_placeholder_own_script_passes(self, tmp_path):
        """`{repo_root}/scripts/own.py`（skill 内部模板）→ 通过。"""
        skill = _skill(
            tmp_path,
            files={
                "references/task-protocol.md": (
                    "# T\n\n`uv run {repo_root}/scripts/check_pre_submit.py .research T1`\n"
                )
            },
        )
        proc = _run(str(skill))
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_symlink_in_skill_tree_rejected(self, tmp_path):
        """skill 树内 symlink → 失败（P1-3 逃逸向量）。"""
        skill = _skill(tmp_path)
        outside = tmp_path / "outside.md"
        outside.write_text("secret", encoding="utf-8")
        link = skill / "references" / "leak.md"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(outside)
        proc = _run(str(skill))
        assert proc.returncode == 1
        assert "symlink" in (proc.stdout + proc.stderr).lower()


class TestBareMdClosure:
    def test_deleted_root_doc_reference_rejected(self, tmp_path):
        """code span 引用不存在的文档（如已删的 STRUCTURE.md）→ 失败。"""
        skill = _skill(
            tmp_path,
            files={
                "examples/README.md": (
                    "# Examples\n\nFull conventions in `STRUCTURE.md`.\n"
                )
            },
        )
        proc = _run(str(skill))
        assert proc.returncode == 1
        assert "missing file reference" in (proc.stdout + proc.stderr)

    def test_existing_in_skill_doc_passes(self, tmp_path):
        """code span 引用的文档存在于 skill 内 → 通过。"""
        skill = _skill(
            tmp_path,
            files={
                "references/running.md": "# Running\n",
                "examples/README.md": "See `running.md`.\n",
            },
        )
        assert _run(str(skill)).returncode == 0

    def test_generated_output_name_passes(self, tmp_path):
        """生成物/约定名（expected-output.md 等）不参与存在性检查。"""
        skill = _skill(
            tmp_path,
            files={
                "examples/README.md": (
                    "# Examples\n\nEach example has `expected-output.md`.\n"
                )
            },
        )
        assert _run(str(skill)).returncode == 0
