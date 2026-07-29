"""pagent 数据根：两种模式二选一，配置 / thread / skills 共用同一目录。

- 生产模式（默认）：``~/.electromind`` —— 面向用户。
- 开发模式：``<root>/.electromind`` —— 面向开发，``root`` 一般是 ``.``。

模式由入口层调用 ``activate_home(...)`` 显式定一次（单一事实源），
下游全部经 ``default_electromind_home()`` 读取。不做「cwd 下有没有 .electromind」的猜测。

不要混用：选中哪个 home，``electromind.toml``、``threads/``、``skills/`` 都在它下面。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

USER_ELECTROMIND_HOME = Path("~/.electromind")
PROJECT_PAGENT_DIRNAME = ".electromind"
HOME_CONFIG_NAME = "electromind.toml"

Mode = Literal["prod", "dev"]

_active_home: Path | None = None


def user_electromind_home() -> Path:
    return USER_ELECTROMIND_HOME.expanduser()


def project_electromind_home(root: str | Path = ".") -> Path:
    return (Path(root).expanduser() / PROJECT_PAGENT_DIRNAME).resolve()


def activate_home(mode: Mode, root: str | Path = ".") -> Path:
    """入口层调用一次，显式选定本进程的 electromind home。

    - ``mode="prod"``：``~/.electromind``
    - ``mode="dev"``：``<root>/.electromind``（``root`` 默认 ``.``）

    返回选定的 home，方便入口打印。
    """
    global _active_home
    _active_home = (
        user_electromind_home().resolve() if mode == "prod" else project_electromind_home(root)
    )
    return _active_home


def reset_home() -> None:
    """清空已激活的 home（主要给测试用）。"""
    global _active_home
    _active_home = None


def resolve_electromind_home(cwd: str | Path | None = None) -> Path:
    """解析当前生效的 electromind home。

    优先级：``activate_home`` 设定值 → ``ELECTROMIND_HOME`` 环境变量 → ``~/.electromind``。
    """
    if _active_home is not None:
        return _active_home
    explicit = os.getenv("ELECTROMIND_HOME")
    if explicit and explicit.strip():
        return Path(explicit).expanduser().resolve()
    return user_electromind_home().resolve()


def default_electromind_home() -> Path:
    return resolve_electromind_home()


def home_config_path(cwd: str | Path | None = None) -> Path:
    """``{home}/electromind.toml``。"""
    return resolve_electromind_home(cwd) / HOME_CONFIG_NAME


def find_home_config(cwd: str | Path | None = None) -> Path | None:
    """当前 home 下的配置文件；只认 ``{home}/electromind.toml`` 这一个位置。"""
    primary = resolve_electromind_home(cwd) / HOME_CONFIG_NAME
    return primary if primary.is_file() else None
