"""electromind home 两模式：生产 ~/.pagent / 开发 <root>/.pagent。"""

from __future__ import annotations

from electromind.ithread.local import default_threads_root
from electromind.paths import (
    activate_home,
    find_home_config,
    resolve_electromind_home,
)


def test_prod_mode_uses_user_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    activate_home("prod")
    assert resolve_electromind_home() == (home / ".electromind").resolve()
    assert default_threads_root() == (home / ".electromind" / "threads").resolve()


def test_dev_mode_uses_project_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    root = tmp_path / "proj"
    root.mkdir()
    activate_home("dev", root)
    assert resolve_electromind_home() == (root / ".electromind").resolve()
    assert default_threads_root() == (root / ".electromind" / "threads").resolve()


def test_dev_mode_defaults_root_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    activate_home("dev")
    assert resolve_electromind_home() == (tmp_path / ".electromind").resolve()


def test_dev_mode_ignores_root_pagent_toml(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "proj"
    root.mkdir()
    (root / "electromind.toml").write_text("[provider]\nmodel = 'x'\n", encoding="utf-8")
    activate_home("dev", root)
    # 只认 <root>/.electromind/electromind.toml；根目录遗留的 electromind.toml 不再被采用。
    assert find_home_config() is None
    (root / ".electromind").mkdir()
    (root / ".electromind" / "electromind.toml").write_text("", encoding="utf-8")
    assert find_home_config() == root / ".electromind" / "electromind.toml"


def test_default_is_user_home_without_activation(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("ELECTROMIND_HOME", raising=False)
    assert resolve_electromind_home() == (home / ".electromind").resolve()


def test_electromind_home_env_overrides_default(tmp_path, monkeypatch):
    explicit_home = tmp_path / "fixed-home"
    monkeypatch.setenv("ELECTROMIND_HOME", str(explicit_home))
    assert resolve_electromind_home() == explicit_home.resolve()
