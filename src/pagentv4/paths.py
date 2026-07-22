"""pagent 数据根：两种模式二选一，配置 / thread / skills 共用同一目录。

- 生产模式（默认）：``~/.pagent`` —— 面向用户。
- 开发模式：``<root>/.pagent`` —— 面向开发，``root`` 一般是 ``.``。

模式由入口层调用 ``activate_home(...)`` 显式定一次（单一事实源），
下游全部经 ``default_pagent_home()`` 读取。不做「cwd 下有没有 .pagent」的猜测。

不要混用：选中哪个 home，``pagent.toml``、``threads/``、``skills/`` 都在它下面。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

USER_PAGENT_HOME = Path("~/.pagent")
PROJECT_PAGENT_DIRNAME = ".pagent"
HOME_CONFIG_NAME = "pagent.toml"

Mode = Literal["prod", "dev"]

_active_home: Path | None = None


def user_pagent_home() -> Path:
    return USER_PAGENT_HOME.expanduser()


def project_pagent_home(root: str | Path = ".") -> Path:
    return (Path(root).expanduser() / PROJECT_PAGENT_DIRNAME).resolve()


def activate_home(mode: Mode, root: str | Path = ".") -> Path:
    """入口层调用一次，显式选定本进程的 pagent home。

    - ``mode="prod"``：``~/.pagent``
    - ``mode="dev"``：``<root>/.pagent``（``root`` 默认 ``.``）

    返回选定的 home，方便入口打印。
    """
    global _active_home
    _active_home = (
        user_pagent_home().resolve() if mode == "prod" else project_pagent_home(root)
    )
    return _active_home


def reset_home() -> None:
    """清空已激活的 home（主要给测试用）。"""
    global _active_home
    _active_home = None


def resolve_pagent_home(cwd: str | Path | None = None) -> Path:
    """解析当前生效的 pagent home。

    优先级：``activate_home`` 设定值 → ``PAGENT_HOME`` 环境变量 → ``~/.pagent``。
    """
    if _active_home is not None:
        return _active_home
    explicit = os.getenv("PAGENT_HOME")
    if explicit and explicit.strip():
        return Path(explicit).expanduser().resolve()
    return user_pagent_home().resolve()


def default_pagent_home() -> Path:
    return resolve_pagent_home()


def home_config_path(cwd: str | Path | None = None) -> Path:
    """``{home}/pagent.toml``。"""
    return resolve_pagent_home(cwd) / HOME_CONFIG_NAME


def find_home_config(cwd: str | Path | None = None) -> Path | None:
    """当前 home 下的配置文件；只认 ``{home}/pagent.toml`` 这一个位置。"""
    primary = resolve_pagent_home(cwd) / HOME_CONFIG_NAME
    return primary if primary.is_file() else None
