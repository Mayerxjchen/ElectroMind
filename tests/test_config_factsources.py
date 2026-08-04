"""配置事实源回归测试：四层合并（Default→User→Project→Local→CLI）、

legacy 一次性迁移、默认继承、单一内置默认。与 docs/superpowers/specs/
2026-08-03-identity-sweep-config-factsource.md 的实现约定对应。
"""

from __future__ import annotations

import shutil
import subprocess
import tarfile
import threading
import tomllib
import zipfile
from pathlib import Path

import pytest

import app
from app.config import (
    ensure_home_config,
    load_config,
    load_settings_sources,
    merge_settings,
    trust_project,
)
from electromind.paths import (
    activate_home,
    bundled_default_config,
    default_electromind_home,
    reset_home,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_NAME = "electromind.toml"


# -- legacy 一次性迁移 -----------------------------------------------------


def test_legacy_user_config_renamed_on_first_load(tmp_path, monkeypatch):
    """旧名 electromind.toml → 首次加载时改名为 config.toml，内容保留。"""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    home_dir = tmp_path / "home" / ".electromind"
    home_dir.mkdir(parents=True)
    legacy = home_dir / LEGACY_NAME
    legacy.write_text('[provider]\napi_key = "sk-legacy"\n', encoding="utf-8")
    activate_home("prod")
    try:
        config = load_config()
        assert config.api_key == "sk-legacy"
        assert legacy.exists() is False
        target = home_dir / "config.toml"
        assert target.is_file()
        assert target.read_text(encoding="utf-8") == (
            '[provider]\napi_key = "sk-legacy"\n'
        )
    finally:
        reset_home()


def test_new_config_wins_over_legacy(tmp_path, monkeypatch):
    """新旧同名同时存在 → config.toml 优先，旧文件原样保留且不再被读取。"""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    home_dir = tmp_path / "home" / ".electromind"
    home_dir.mkdir(parents=True)
    (home_dir / "config.toml").write_text(
        '[provider]\nmodel = "new-model"\n', encoding="utf-8"
    )
    legacy = home_dir / LEGACY_NAME
    legacy.write_text('[provider]\nmodel = "old-model"\n', encoding="utf-8")
    activate_home("prod")
    try:
        assert load_config().model == "new-model"
        assert legacy.read_text(encoding="utf-8") == (
            '[provider]\nmodel = "old-model"\n'
        )
    finally:
        reset_home()


def test_ensure_home_config_idempotent(tmp_path, monkeypatch):
    """重复调用不重复物化、不覆盖已有内容。"""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    activate_home("prod")
    try:
        first = ensure_home_config()
        second = ensure_home_config()
        assert first == second
        assert first.read_text(encoding="utf-8") == bundled_default_config().read_text(
            encoding="utf-8"
        )
    finally:
        reset_home()


def test_project_and_local_legacy_migrated(tmp_path, monkeypatch):
    """Project / Local scope 的旧名同样一次性改名，迁移后值生效。"""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    (proj / ".electromind").mkdir()
    legacy_proj = proj / ".electromind" / LEGACY_NAME
    legacy_proj.write_text('[provider]\nmodel = "proj-old"\n', encoding="utf-8")
    legacy_local = proj / ".electromind" / "electromind.local.toml"
    legacy_local.write_text('[provider]\nmodel = "local-old"\n', encoding="utf-8")

    sources = load_settings_sources(workdir=str(proj), include_project=True)
    merged, _ = merge_settings(sources)
    assert merged.model == "local-old"
    assert legacy_proj.exists() is False
    assert legacy_local.exists() is False
    assert (proj / ".electromind" / "config.toml").is_file()
    assert (proj / ".electromind" / "config.local.toml").is_file()


# -- 内置默认作为最低合并层 ------------------------------------------------


def test_partial_user_config_inherits_defaults(tmp_path, monkeypatch):
    """用户配置只写部分字段时，省略字段从内置默认继承（如默认 skill roots）。"""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    home_dir = tmp_path / "home" / ".electromind"
    home_dir.mkdir(parents=True)
    (home_dir / "config.toml").write_text(
        '[provider]\napi_key = "sk-minimal"\n', encoding="utf-8"
    )
    activate_home("prod")
    try:
        config = load_config()
        assert config.api_key == "sk-minimal"
        # 省略 [skills] → 继承内置默认 roots，而不是空列表。
        assert config.skill_roots == ("{electromind_home}/skills",)
        assert config.resolved_skill_dirs() == (f"{default_electromind_home()}/skills",)
        # 其余省略字段同样继承默认。
        assert config.image == "electromind:latest"
        assert config.resolved_assistant_label() == "electromind"
    finally:
        reset_home()


def test_explicit_empty_skills_roots_wins_over_default(tmp_path, monkeypatch):
    """显式空表 = 不扫描任何目录，不回落内置默认。"""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    home_dir = tmp_path / "home" / ".electromind"
    home_dir.mkdir(parents=True)
    (home_dir / "config.toml").write_text("[skills]\nroots = []\n", encoding="utf-8")
    activate_home("prod")
    try:
        assert load_config().resolved_skill_roots() == ()
    finally:
        reset_home()


def test_trusted_project_overrides_default_layer(tmp_path, monkeypatch):
    """信任后 Project 配置覆盖内置默认（回归 P1 合并顺序）。"""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    (proj / ".electromind").mkdir()
    (proj / ".electromind" / "config.toml").write_text(
        '[provider]\nmodel = "proj-model"\n', encoding="utf-8"
    )
    trust_project(proj)
    assert load_config(workdir=str(proj)).model == "proj-model"


# -- 原子物化（临时文件 + fsync + no-replace 发布） -------------------------


def test_atomic_write_publishes_complete_content(tmp_path):
    """正常发布：目标内容完整、无临时文件残留、权限 0600。"""
    from app.config import _atomic_write_text

    target = tmp_path / "config.toml"
    content = "x" * 10_000  # 超长内容也必须一次性完整
    assert _atomic_write_text(target, content) is True
    assert target.read_text(encoding="utf-8") == content
    assert target.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob("*.tmp*"))


def test_atomic_write_failure_leaves_no_partial_file(tmp_path, monkeypatch):
    """写临时文件失败（如磁盘满）→ 目标路径不存在、临时文件被清理。"""
    from app.config import _atomic_write_text

    target = tmp_path / "config.toml"

    def boom(_fd):
        raise OSError("disk full")

    monkeypatch.setattr("app.config.os.fsync", boom)
    with pytest.raises(OSError):
        _atomic_write_text(target, "content")
    assert not target.exists()  # 最终文件名从未出现
    assert not list(tmp_path.glob("*.tmp*"))


def test_atomic_write_no_replace_keeps_concurrent_content(tmp_path):
    """发布竞态：另一进程先发布了 target → 本调用不覆盖，内容保持。"""
    from app.config import _atomic_write_text

    target = tmp_path / "config.toml"
    target.write_text('[provider]\nmodel = "concurrent"\n', encoding="utf-8")
    published = _atomic_write_text(target, '[provider]\nmodel = "other"\n')
    assert published is False
    assert target.read_text(encoding="utf-8") == '[provider]\nmodel = "concurrent"\n'
    assert not list(tmp_path.glob("*.tmp*"))


def test_concurrent_materialization_single_complete_result(tmp_path):
    """同进程双线程并发物化（mkstemp 唯一临时名）：恰有一个发布成功。

    不伪造 PID：临时文件唯一性由 ``tempfile.mkstemp`` 保证，线程间不争用。
    """
    from app.config import _atomic_write_text
    from electromind.paths import bundled_default_config

    target = tmp_path / "config.toml"
    content = bundled_default_config().read_text(encoding="utf-8")

    results: list[bool] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        barrier.wait()
        results.append(_atomic_write_text(target, content))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == [False, True]  # 恰好一个发布成功
    assert target.read_text(encoding="utf-8") == content  # 完整内容
    assert not list(tmp_path.glob("*.tmp*"))


def test_atomic_write_fail_closed_without_hardlink(tmp_path, monkeypatch):
    """硬链不支持的极端文件系统：fail-closed，保留临时文件，绝不 rename 覆盖。"""
    from app.config import _atomic_write_text

    target = tmp_path / "config.toml"
    target.write_text('[provider]\nmodel = "user-config"\n', encoding="utf-8")

    def no_hardlink(src, dst):
        raise OSError(95, "Operation not supported")

    monkeypatch.setattr("app.config.os.link", no_hardlink)
    with pytest.raises(OSError, match="不支持硬链"):
        _atomic_write_text(target, '[provider]\nmodel = "other"\n')
    # 用户配置未被覆盖，临时文件保留供诊断/恢复。
    assert target.read_text(encoding="utf-8") == '[provider]\nmodel = "user-config"\n'
    leftovers = list(tmp_path.glob("*.tmp*"))
    assert len(leftovers) == 1
    assert leftovers[0].read_text(encoding="utf-8") == '[provider]\nmodel = "other"\n'


# -- 单一内置默认 ----------------------------------------------------------


def test_single_bundled_config_fact_source():
    """唯一内置默认位于 electromind 包内；src/app 与 src/template 无默认 toml。

    uv_build 收集模块目录（module-name = ["electromind", "app"]）内的全部文件，
    因此该资源随 wheel / sdist 一起发布（standalone 另经 --collect-data 收集）。
    """
    bundled = bundled_default_config()
    assert bundled.is_file()
    assert bundled.name == "default-config.toml"
    assert bundled.parent.name == "resources"
    assert bundled.parent.parent.name == "electromind"

    app_dir = Path(app.__file__).parent
    assert not list(app_dir.glob("*.toml"))
    src_root = Path(app.__file__).parent.parent
    assert not (src_root / "template").exists()


def test_built_archives_contain_default_config(tmp_path):
    """实际构建 wheel / sdist 并硬断言成员；再从 wheel 解包读取并解析默认配置。

    构建后端下限锁在 uv_build 0.9.0（0.8.x 的 sdist 收集缺陷会概率性缺整个
    src/ 目录，产物安装直接失败）；此处对两种 archive 都是硬断言，缺陷复发
    即红。``scripts/ci-check.sh`` 与 ``scripts/release.sh`` 另设同款产物门禁。
    """
    if shutil.which("uv") is None:
        pytest.skip("需要 uv 才能构建发布产物")

    out = tmp_path / "dist"
    out.mkdir()
    subprocess.run(
        ["uv", "build", "--out-dir", str(out)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = sorted(out.glob("*.whl"))
    sdists = sorted(out.glob("*.tar.gz"))
    assert wheels, "uv build 未产出 wheel"
    assert sdists, "uv build 未产出 sdist"

    # wheel 成员：默认配置在包内，且 app/ 下不再携带任何默认 toml。
    with zipfile.ZipFile(wheels[0]) as zf:
        names = set(zf.namelist())
        assert "electromind/resources/default-config.toml" in names
        assert not any(
            name.startswith("app/") and name.endswith(".toml") for name in names
        )

    # sdist 成员：源码树里的默认配置必须在 sdist 中（0.8.x 缺陷的回归点）。
    with tarfile.open(sdists[0]) as tf:
        sdist_names = tf.getnames()
    assert any(
        name.endswith("src/electromind/resources/default-config.toml")
        for name in sdist_names
    ), "sdist 缺少默认配置（模块目录未收集？uv_build 缺陷复发）"

    # 从 wheel 解包（= 安装内容）读取并解析默认配置。
    site = tmp_path / "site"
    with zipfile.ZipFile(wheels[0]) as zf:
        zf.extractall(site)
    installed = site / "electromind" / "resources" / "default-config.toml"
    assert installed.is_file()
    with installed.open("rb") as fp:
        data = tomllib.load(fp)
    assert data["repl"]["assistant_label"] == "electromind"
    assert data["sandbox"]["container"]["image"] == "electromind:latest"
