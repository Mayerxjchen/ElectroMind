"""服务端环境自检：backend 可用性、electromind home 路径与占用、api_key 是否配置。

desktop 现在在 Electron 主进程用 execFileSync 探测本机（docker/podman/uv/home 占用）。
搬到远程后前端够不到 server 的机器，改由 server 执行本自检，经 ``environment_check``
命令下发。只探测"server 所在机器"的环境，与传输无关。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from electromind.paths import resolve_electromind_home

from .config import load_config


def cli_on_path(name: str) -> bool:
    return shutil.which(name) is not None


def detect_container_runtime() -> str | None:
    if cli_on_path("docker"):
        return "docker"
    if cli_on_path("podman"):
        return "podman"
    return None


def dir_size_bytes(path: Path) -> int:
    if not path.is_dir():
        return 0
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            stat = entry.stat()
            total += stat.st_size
    return total


def environment_check(*, include_disk: bool = False) -> dict:
    """收集 server 机器环境。include_disk 统计 home 占用（偏慢，按需开）。"""
    home = resolve_electromind_home()
    config = load_config()
    check = {
        "uv_installed": cli_on_path("uv"),
        "docker_installed": cli_on_path("docker"),
        "podman_installed": cli_on_path("podman"),
        "container_runtime": detect_container_runtime(),
        "api_key_configured": bool(config.resolved_api_key()),
        "data_home_path": str(home),
        "data_home_exists": home.is_dir(),
    }
    if include_disk:
        check["data_home_bytes"] = dir_size_bytes(home)
    return check
