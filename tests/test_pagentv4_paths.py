"""pagent home 两模式：生产 ~/.pagent / 开发 <root>/.pagent。"""

from __future__ import annotations

from pagentv4.ithread.local import default_threads_root
from pagentv4.paths import (
    activate_home,
    find_home_config,
    resolve_pagent_home,
)


def test_prod_mode_uses_user_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    activate_home("prod")
    assert resolve_pagent_home() == (home / ".pagent").resolve()
    assert default_threads_root() == (home / ".pagent" / "threads").resolve()


def test_dev_mode_uses_project_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    root = tmp_path / "proj"
    root.mkdir()
    activate_home("dev", root)
    assert resolve_pagent_home() == (root / ".pagent").resolve()
    assert default_threads_root() == (root / ".pagent" / "threads").resolve()


def test_dev_mode_defaults_root_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    activate_home("dev")
    assert resolve_pagent_home() == (tmp_path / ".pagent").resolve()


def test_dev_mode_ignores_root_pagent_toml(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pagent.toml").write_text("[provider]\nmodel = 'x'\n", encoding="utf-8")
    activate_home("dev", root)
    # 只认 <root>/.pagent/pagent.toml；根目录遗留的 pagent.toml 不再被采用。
    assert find_home_config() is None
    (root / ".pagent").mkdir()
    (root / ".pagent" / "pagent.toml").write_text("", encoding="utf-8")
    assert find_home_config() == root / ".pagent" / "pagent.toml"


def test_default_is_user_home_without_activation(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("PAGENT_HOME", raising=False)
    assert resolve_pagent_home() == (home / ".pagent").resolve()


def test_pagent_home_env_overrides_default(tmp_path, monkeypatch):
    explicit_home = tmp_path / "fixed-home"
    monkeypatch.setenv("PAGENT_HOME", str(explicit_home))
    assert resolve_pagent_home() == explicit_home.resolve()
