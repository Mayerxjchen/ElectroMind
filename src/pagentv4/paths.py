"""pagent 数据根：二选一，配置 / thread / skills 共用同一目录。

A. ``<cwd>/.pagent`` —— 项目目录下已有 ``.pagent/``（或遗留的 ``./pagent.toml``）
B. ``~/.pagent`` —— 否则用用户级目录

不要混用：选中哪个 home，``pagent.toml``、``threads/``、``skills/`` 都在它下面。
"""

from __future__ import annotations

import os
from pathlib import Path

USER_PAGENT_HOME = Path("~/.pagent")
PROJECT_PAGENT_DIRNAME = ".pagent"
LEGACY_PROJECT_CONFIG = "pagent.toml"
HOME_CONFIG_NAME = "pagent.toml"


def user_pagent_home() -> Path:
    return USER_PAGENT_HOME.expanduser()


def resolve_pagent_home(cwd: str | Path | None = None) -> Path:
    """解析当前生效的 pagent home（A 项目 / B 用户）。"""
    explicit = os.getenv("PAGENT_HOME")
    if explicit and explicit.strip():
        return Path(explicit).expanduser().resolve()
    base = Path(cwd) if cwd is not None else Path(os.getcwd())
    project = base / PROJECT_PAGENT_DIRNAME
    if project.is_dir():
        return project.resolve()
    # 遗留：项目根仍放 pagent.toml 时，视为项目模式，数据进 .pagent/
    if (base / LEGACY_PROJECT_CONFIG).is_file():
        return project.resolve()
    return user_pagent_home().resolve()


def default_pagent_home() -> Path:
    return resolve_pagent_home()


def home_config_path(cwd: str | Path | None = None) -> Path:
    """``{home}/pagent.toml``；项目模式若尚未迁移，见 ``find_home_config``。"""
    return resolve_pagent_home(cwd) / HOME_CONFIG_NAME


def find_home_config(cwd: str | Path | None = None) -> Path | None:
    """当前 home 下的配置文件；项目模式兼容根目录遗留 ``pagent.toml``。"""
    base = Path(cwd) if cwd is not None else Path(os.getcwd())
    home = resolve_pagent_home(base)
    primary = home / HOME_CONFIG_NAME
    if primary.is_file():
        return primary
    if home == (base / PROJECT_PAGENT_DIRNAME).resolve():
        legacy = base / LEGACY_PROJECT_CONFIG
        if legacy.is_file():
            return legacy
    return None
