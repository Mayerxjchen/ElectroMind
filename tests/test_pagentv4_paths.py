"""pagent home 二选一：项目 .pagent / 用户 ~/.pagent。"""

from __future__ import annotations

from pagentv4.ithread.local import default_threads_root
from pagentv4.paths import find_home_config, resolve_pagent_home


def test_resolve_user_home_when_no_project(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    cwd = tmp_path / "proj"
    cwd.mkdir()
    assert resolve_pagent_home(cwd) == (home / ".pagent").resolve()
    monkeypatch.chdir(cwd)
    assert default_threads_root() == (home / ".pagent" / "threads").resolve()


def test_resolve_project_home_when_dotpagent_exists(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    cwd = tmp_path / "proj"
    (cwd / ".pagent").mkdir(parents=True)
    assert resolve_pagent_home(cwd) == (cwd / ".pagent").resolve()
    monkeypatch.chdir(cwd)
    assert default_threads_root() == (cwd / ".pagent" / "threads").resolve()


def test_legacy_root_pagent_toml_selects_project_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    cwd = tmp_path / "proj"
    cwd.mkdir()
    (cwd / "pagent.toml").write_text("[provider]\nmodel = 'x'\n", encoding="utf-8")
    assert resolve_pagent_home(cwd) == (cwd / ".pagent").resolve()
    assert find_home_config(cwd) == cwd / "pagent.toml"
