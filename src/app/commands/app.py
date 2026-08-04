"""``electromind app [PATH]``：启动桌面应用。

桌面应用位于 ``editors/desktop``（仓库内），通过 ``npm start`` 启动。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from app.exitcodes import EXIT_CLI, EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="electromind app", description="启动 Electron 桌面应用"
    )
    parser.add_argument(
        "path", nargs="?", default=None, help="项目目录（默认当前目录）"
    )
    return parser


def _desktop_dir() -> Path | None:
    env = os.environ.get("ELECTROMIND_DESKTOP_DIR")
    if env:
        return Path(env)
    # 仓库内路径：<repo>/editors/desktop
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "editors" / "desktop"
        if (candidate / "package.json").is_file():
            return candidate
    return None


def run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    desktop = _desktop_dir()
    if desktop is None:
        print(
            "未找到桌面应用目录（editors/desktop）。"
            "可用 ELECTROMIND_DESKTOP_DIR 指定。",
            file=sys.stderr,
        )
        return EXIT_CLI

    cwd = os.path.abspath(args.path) if args.path else os.getcwd()
    try:
        process = subprocess.Popen(
            ["npm", "start"],
            cwd=os.fspath(desktop),
            env={**os.environ, "ELECTROMIND_CWD": cwd},
        )
    except OSError as exc:
        print(f"启动失败: {exc}", file=sys.stderr)
        return EXIT_CLI
    print(f"桌面应用启动中（PID {process.pid}），项目目录: {cwd}")
    return EXIT_OK
