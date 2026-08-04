"""electromind 数据根与配置路径：两种模式二选一，配置 / thread / skills 共用同一目录。

- 生产模式（默认）：``~/.electromind`` —— 面向用户。
- 开发模式：``<root>/.electromind`` —— 面向开发，``root`` 一般是 ``.``。

模式由入口层调用 ``activate_home(...)`` 显式定一次（单一事实源），
下游全部经 ``default_electromind_home()`` 读取。不做「cwd 下有没有 .electromind」的猜测。

不要混用：选中哪个 home，``config.toml``、``threads/``、``skills/`` 都在它下面。

配置事实源只有四层（低 → 高）：
  1. 包内内置默认 ``src/electromind/resources/default-config.toml``
  2. ``{home}/config.toml``（用户设置）
  3. ``<project>/.electromind/config.toml``（项目设置，仅受信任项目）
  4. ``<project>/.electromind/config.local.toml``（本机私有设置）
外加 ``--config <file>`` 显式叠加。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

USER_ELECTROMIND_HOME = Path("~/.electromind")
PROJECT_ELECTROMIND_DIRNAME = ".electromind"

# 配置文件名（用户 / 项目 scope 共用）。
HOME_CONFIG_NAME = "config.toml"
# 本机私有设置（项目 scope）。
LOCAL_CONFIG_NAME = "config.local.toml"
# 旧配置文件名：一次性迁移用（见 app.config.ensure_home_config）。
LEGACY_HOME_CONFIG_NAME = "electromind.toml"
LEGACY_LOCAL_CONFIG_NAME = "electromind.local.toml"
# 包内唯一内置默认配置文件名（src/electromind/resources/ 下）。
BUNDLED_CONFIG_NAME = "default-config.toml"

Mode = Literal["prod", "dev"]

_active_home: Path | None = None


def user_electromind_home() -> Path:
    return USER_ELECTROMIND_HOME.expanduser()


def project_electromind_home(root: str | Path = ".") -> Path:
    return (Path(root).expanduser() / PROJECT_ELECTROMIND_DIRNAME).resolve()


def bundled_default_config() -> Path:
    """包内唯一内置默认配置（``src/electromind/resources/default-config.toml``）。

    用户 / 项目 home 缺 ``config.toml`` 时由入口层物化这份内容。
    """
    return Path(__file__).resolve().parent / "resources" / BUNDLED_CONFIG_NAME


def activate_home(mode: Mode, root: str | Path = ".") -> Path:
    """入口层调用一次，显式选定本进程的 electromind home。

    - ``mode="prod"``：``~/.electromind``
    - ``mode="dev"``：``<root>/.electromind``（``root`` 默认 ``.``）

    返回选定的 home，方便入口打印。
    """
    global _active_home
    _active_home = (
        user_electromind_home().resolve()
        if mode == "prod"
        else project_electromind_home(root)
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
    """``{home}/config.toml``。"""
    return resolve_electromind_home(cwd) / HOME_CONFIG_NAME


def find_home_config(cwd: str | Path | None = None) -> Path | None:
    """当前 home 下的配置文件；只认 ``{home}/config.toml`` 这一个位置。"""
    primary = resolve_electromind_home(cwd) / HOME_CONFIG_NAME
    return primary if primary.is_file() else None
