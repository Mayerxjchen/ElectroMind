"""SKILL-8 tests: built-in skill delivery — wheel/venv bundle and empty env."""

import shutil
from pathlib import Path

import pytest

from electromind.skills.builtin import (
    builtin_kind_for,
    builtin_roots,
    builtin_skill_roots,
)
from electromind.skills.scopes import discover_candidate_sources, load_candidates

REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_bundle(root: Path) -> Path:
    """Create a minimal builtin bundle (procedures/ + tools/ + knowledge/)."""
    root.mkdir(parents=True, exist_ok=True)
    tool = root / "tools" / "cp2k"
    tool.mkdir(parents=True)
    (tool / "SKILL.md").write_text(
        "---\nname: cp2k\ndescription: CP2K runner\n---\nRun cp2k.\n",
        encoding="utf-8",
    )
    proc = root / "procedures" / "workflow"
    proc.mkdir(parents=True)
    (proc / "SKILL.md").write_text(
        "---\nname: workflow\ndescription: A workflow\n---\nDo work.\n",
        encoding="utf-8",
    )
    kn = root / "knowledge"
    kn.mkdir(parents=True, exist_ok=True)
    (kn / "ref.md").write_text("# Ref\n", encoding="utf-8")
    return root


def _flat_roots(bundle: Path) -> tuple[Path, Path]:
    return (bundle / "procedures", bundle / "tools")


class TestBuiltinRoots:
    def test_no_agents_md_marker_branch_in_src(self):
        """A+ W5：src 下不得存在 AGENTS.md marker 发现分支（唯一发现协议）。"""
        import re

        src = REPO_ROOT / "src"
        marker_patterns = [
            re.compile(r'\(root\s*/\s*"AGENTS\.md"\)\.exists\(\)'),
            re.compile(r'\(root\s*/\s*"AGENTS\.md"\)\.is_file\(\)'),
            re.compile(r"STRUCTURED_MARKER"),
        ]
        hits: list[str] = []
        for path in src.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for pattern in marker_patterns:
                if pattern.search(text):
                    hits.append(f"{path.relative_to(REPO_ROOT)}")
        assert hits == [], f"AGENTS.md marker 发现分支残留: {hits}"

    def test_builtin_skill_roots_shape(self, tmp_path):
        """A+ W5：内置 skills 提供两个普通扁平根，无 marker 要求。"""
        roots = builtin_skill_roots(tmp_path)
        assert roots == (
            tmp_path / "skills" / "procedures",
            tmp_path / "skills" / "tools",
        )

    def test_repo_bundle_found_in_dev(self):
        """开发环境：仓库根 skills/ 的扁平根作为 builtin root 被发现。"""
        roots = builtin_roots()
        assert len(roots) >= 2
        assert any(r.name == "procedures" for r in roots)
        assert any(r.name == "tools" for r in roots)

    def test_flat_roots_need_no_agents_marker(self, tmp_path, monkeypatch):
        """A+ W5：没有 AGENTS.md marker 也能发现扁平根。"""
        bundle = _make_bundle(tmp_path / "skills")
        import sys

        monkeypatch.setattr(sys, "prefix", str(tmp_path))
        roots = builtin_roots()
        procedures, tools = _flat_roots(bundle)
        assert procedures.resolve() in roots
        assert tools.resolve() in roots

    def test_installed_venv_location(self, tmp_path, monkeypatch):
        """安装产物：<sys.prefix>/skills 的扁平根被发现（uv_build data 位）。"""
        bundle = _make_bundle(tmp_path / "skills")
        import sys

        monkeypatch.setattr(sys, "prefix", str(tmp_path))
        roots = builtin_roots()
        procedures, tools = _flat_roots(bundle)
        assert procedures.resolve() in roots
        assert tools.resolve() in roots

    def test_empty_environment_no_roots(self, tmp_path, monkeypatch):
        """空环境：无任何 bundle 时返回空 tuple（发现测试）。"""
        import sys

        monkeypatch.setattr(sys, "prefix", str(tmp_path / "noprefix"))
        # Remove repo fallback by hiding the real source tree
        monkeypatch.setattr(
            "electromind.skills.builtin._candidate_builtin_bases",
            lambda: [tmp_path / "none", tmp_path / "skills_data"],
        )
        assert builtin_roots() == ()

    def test_wheel_data_layout_venv_root(self, tmp_path, monkeypatch):
        """真实 wheel 布局：uv_build data 把 bundle 内容散装到 venv 根。

        构建出的 wheel 其 ``<pkg>.data/data/`` 直接含 procedures/、tools/
        （安装到 ``<sys.prefix>`` 根）—— ``builtin_roots()`` 必须发现扁平根。
        """
        import sys
        import zipfile

        # 1. Build the real wheel (best-effort; skip if uv unavailable)
        wheel = tmp_path / "wheel"
        import subprocess

        build = subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(wheel)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if build.returncode != 0:
            pytest.skip(f"uv build unavailable: {build.stderr[:200]}")

        wheels = list(wheel.glob("*.whl"))
        assert len(wheels) == 1
        # A+ W6: wheel 数据区不含顶层 knowledge/
        import zipfile as _zipfile

        with _zipfile.ZipFile(wheels[0]) as zf:
            data_names = [
                n for n in zf.namelist() if ".data/data/" in n and "/skills/" in n
            ]
            assert not any("knowledge/" in n for n in data_names), (
                f"wheel 不得携带顶层 knowledge/: {data_names}"
            )
        # 2. Extract ONLY the .data/data portion into a fake venv root
        #    (data dir name is `<dist>-<version>.data/data/`)
        fake_prefix = tmp_path / "venv"
        with zipfile.ZipFile(wheels[0]) as zf:
            data_prefix = next(
                (n for n in zf.namelist() if n.endswith(".data/data/")), None
            )
            assert data_prefix is not None, "wheel has no .data/data section"
            for name in zf.namelist():
                if name.startswith(data_prefix) and not name.endswith("/"):
                    rel = name[len(data_prefix) :]
                    dest = fake_prefix / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(zf.read(name))

        assert (fake_prefix / "procedures").is_dir()
        assert (fake_prefix / "tools").is_dir()

        # A+ W6: 运行时 wheel 不含顶层 knowledge/（作者事实源，非运行依赖）
        assert not (fake_prefix / "knowledge").is_dir()

        # 3. Discovery from the venv-root layout must find the flat roots
        monkeypatch.setattr(sys, "prefix", str(fake_prefix))
        roots = builtin_roots()
        assert (fake_prefix / "procedures").resolve() in roots
        assert (fake_prefix / "tools").resolve() in roots

        # 4. And candidates load with cp2k etc.
        sources = discover_candidate_sources(
            None, cwd=str(fake_prefix), builtin_roots=roots
        )
        candidates = load_candidates(sources)
        names = {c.descriptor.name for c in candidates}
        assert "cp2k" in names

    def test_sdist_keeps_full_skills_bundle(self, tmp_path):
        """A+ W6：sdist 保留完整 skills/（作者分发，含 knowledge/ 事实源）。"""
        import subprocess
        import tarfile

        dist = tmp_path / "dist"
        build = subprocess.run(
            ["uv", "build", "--sdist", "--out-dir", str(dist)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if build.returncode != 0:
            pytest.skip(f"uv build unavailable: {build.stderr[:200]}")
        sdists = list(dist.glob("*.tar.gz"))
        assert len(sdists) == 1
        names = tarfile.open(sdists[0]).getnames()
        assert any(
            n.endswith("skills/knowledge/electronic-structure.md") for n in names
        )
        assert any(n.endswith("skills/knowledge/sync-map.toml") for n in names)
        assert any(n.endswith("skills/tools/cp2k/SKILL.md") for n in names)
        # 各 skill 的 committed runtime copies 也随 sdist 分发
        assert any(
            n.endswith("skills/tools/cp2k/references/knowledge/electronic-structure.md")
            for n in names
        )

    def test_kind_for(self, tmp_path):
        bundle = _make_bundle(tmp_path / "bundle")
        assert builtin_kind_for(bundle / "tools", bundle / "tools" / "cp2k") == "tool"
        assert (
            builtin_kind_for(bundle / "procedures", bundle / "procedures" / "workflow")
            == "procedure"
        )


class TestBuiltinDiscovery:
    def test_builtin_scope_discovered(self, tmp_path):
        """扁平 root → scope='builtin', dialect='builtin', read_only。"""
        bundle = _make_bundle(tmp_path / "bundle")
        sources = discover_candidate_sources(
            None, cwd=str(tmp_path), builtin_roots=_flat_roots(bundle)
        )
        builtin_src = [s for s in sources if s.scope == "builtin"]
        assert len(builtin_src) == 2  # one source per flat root
        assert all(s.dialect == "builtin" for s in builtin_src)
        assert all(s.read_only is True for s in builtin_src)

    def test_builtin_candidates_load(self, tmp_path):
        bundle = _make_bundle(tmp_path / "bundle")
        sources = discover_candidate_sources(
            None, cwd=str(tmp_path), builtin_roots=_flat_roots(bundle)
        )
        candidates = load_candidates(sources)
        names = {c.descriptor.name for c in candidates}
        assert "cp2k" in names
        assert "workflow" in names
        # knowledge/ is never a skill
        assert "ref" not in names
        # builtin candidates default to trusted
        assert all(c.trust_state == "trusted" for c in candidates)

    def test_builtin_qualified_id(self, tmp_path):
        bundle = _make_bundle(tmp_path / "bundle")
        sources = discover_candidate_sources(
            None, cwd=str(tmp_path), builtin_roots=_flat_roots(bundle)
        )
        candidates = load_candidates(sources)
        cp2k = next(c for c in candidates if c.descriptor.name == "cp2k")
        # RFC 命名约定：builtin:procedure:cp2k 风格（单数 kind）。
        assert cp2k.skill_id == "builtin:tool:cp2k"

    def test_repo_bundle_as_builtin(self):
        """真实仓库 skills/ 的两个扁平根可发现内置科学 Skill。"""
        sources = discover_candidate_sources(
            None,
            cwd=str(REPO_ROOT),
            builtin_roots=(
                REPO_ROOT / "skills" / "procedures",
                REPO_ROOT / "skills" / "tools",
            ),
        )
        candidates = load_candidates(sources)
        names = {c.descriptor.name for c in candidates}
        assert "cp2k" in names
        assert "vasp" in names
        assert "lammps" in names


class TestUvToolInstallSmoke:
    """SKILL-8 收尾：uv tool 安装（真实 venv）后 builtin 可发现。"""

    def test_uv_tool_install_smoke(self, tmp_path):
        """``uv tool install`` 到隔离 UV_TOOL_DIR → 真实安装 venv 的 builtin 可发现。

        端到端验证 SKILL-8 产物：构建 wheel → ``uv tool install`` 到临时工具
        目录（``UV_TOOL_DIR`` / ``UV_TOOL_BIN_DIR``，uv 0.11 替代已删除的
        ``--root`` 的隔离机制）→ 用**安装 venv 自己的解释器**（cwd 指向临时
        目录，杜绝源码 fallback）运行 builtin 发现。

        硬断言：安装 rc==0、输出 ``CP2K True``、builtin root 位于临时安装
        前缀。构建 / 安装 / 检查任一步失败都直接失败（仅 uv 缺失时 skip）。
        """
        import json
        import os
        import subprocess

        if not shutil.which("uv"):
            pytest.skip("uv not available")

        # 1) 构建 wheel —— 失败即硬失败。
        wheel_dir = tmp_path / "wheel"
        wheel_dir.mkdir()
        build = subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(wheel_dir)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert build.returncode == 0, f"uv build failed:\n{build.stderr[-500:]}"
        wheels = list(wheel_dir.glob("*.whl"))
        assert len(wheels) == 1, f"期望恰好一个 wheel，得到 {wheels}"

        # 2) uv tool install 到隔离目录（真实安装，不污染用户 ~/.local）。
        tools_dir = tmp_path / "tools"
        bin_dir = tmp_path / "bin"
        env = {
            **os.environ,
            "UV_TOOL_DIR": str(tools_dir),
            "UV_TOOL_BIN_DIR": str(bin_dir),
        }
        install = subprocess.run(
            ["uv", "tool", "install", "--force", str(wheels[0])],
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert install.returncode == 0, (
            f"uv tool install failed:\n{install.stderr[-500:]}"
        )

        # 3) 定位并执行真实安装 venv 的解释器（工具 venv 名为 electromind）。
        #    Windows 的 venv 解释器在 Scripts/ 下，POSIX 在 bin/ 下。
        venv_root = tools_dir / "electromind"
        installed_python = venv_root / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        assert installed_python.is_file(), f"安装 venv 解释器不存在: {installed_python}"
        code = (
            "import json, sys; "
            "from electromind.skills.builtin import builtin_roots; "
            "from electromind.skills.scopes import discover_candidate_sources, "
            "load_candidates; "
            "print('PREFIX', json.dumps(sys.prefix)); "
            "print('ROOTS', json.dumps([str(r) for r in builtin_roots()])); "
            "sources = discover_candidate_sources(None, cwd='.'); "
            "cands = load_candidates(sources); "
            "print('CP2K', any(c.descriptor.name == 'cp2k' for c in cands))"
        )
        run = subprocess.run(
            [str(installed_python), "-c", code],
            cwd=str(tmp_path),  # 不在仓库内运行，杜绝源码 fallback
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert run.returncode == 0, f"安装环境检查失败:\n{run.stderr[-500:]}"
        assert "CP2K True" in run.stdout, (
            f"真实安装未发现 cp2k（builtin 未随 wheel 安装？）:\n{run.stdout}"
        )

        def _json_line(prefix: str) -> str:
            return next(
                (
                    line[len(prefix) :]
                    for line in run.stdout.splitlines()
                    if line.startswith(prefix)
                ),
                "",
            )

        # 子进程用 JSON 传路径（跨平台字符串），父进程 json.loads 解析，无 eval。
        prefix_raw = _json_line("PREFIX ")
        assert prefix_raw, f"缺少 PREFIX 行:\n{run.stdout}"
        assert json.loads(prefix_raw) == str(venv_root.resolve()), (
            f"运行的不是安装 venv 解释器:\n{run.stdout}"
        )
        roots_raw = _json_line("ROOTS ")
        assert roots_raw, f"builtin_roots 未输出:\n{run.stdout}"
        # builtin root 必须位于临时安装前缀（resolve 归一 /var↔/private/var）。
        install_prefix = tmp_path.resolve()
        for item in json.loads(roots_raw):
            assert str(Path(item).resolve()).startswith(str(install_prefix)), (
                f"builtin root 不在临时安装前缀: {item}"
            )
