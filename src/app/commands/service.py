"""``electromind service`` 子命令：start | status | stop | logs。

Harness Service = 常驻 HTTP 后端（复用 wire 的命令核心与 Harness 协议），
供 Desktop / VS Code / 脚本通过 ``ServiceAgentClient`` 接入。

- PID 文件：``{home}/service.pid``
- 日志：``{home}/service.log``（未指定 --log-file 时）
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from app.exitcodes import EXIT_CLI, EXIT_OK, EXIT_SERVICE

SERVICE_PID_NAME = "service.pid"
SERVICE_LOG_NAME = "service.log"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8848


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="electromind service", description="Harness Service 进程管理"
    )
    parser.add_argument(
        "action", choices=("start", "status", "stop", "logs"), help="服务动作"
    )
    parser.add_argument(
        "--host", default=DEFAULT_HOST, help=f"监听地址（默认 {DEFAULT_HOST}）"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"监听端口（默认 {DEFAULT_PORT}）",
    )
    parser.add_argument(
        "--log-file", default=None, help="日志文件（默认 {home}/service.log）"
    )
    return parser


def _home() -> Path:
    from electromind.paths import default_electromind_home

    return default_electromind_home()


def _pid_path() -> Path:
    return _home() / SERVICE_PID_NAME


def _log_path(args) -> Path:
    if args.log_file:
        return Path(args.log_file).expanduser()
    return _home() / SERVICE_LOG_NAME


def _read_pid() -> int | None:
    path = _pid_path()
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.action == "start":
        return _start(args)
    if args.action == "status":
        return _status()
    if args.action == "stop":
        return _stop()
    if args.action == "logs":
        return _logs(args)
    return EXIT_CLI


def _start(args) -> int:
    pid = _read_pid()
    if pid is not None and _alive(pid):
        print(f"service 已在运行（PID {pid}）", file=sys.stderr)
        return EXIT_CLI

    log_path = _log_path(args)
    _home().mkdir(parents=True, exist_ok=True)
    log_fp = open(log_path, "ab")

    # 后台启动 HTTP 后端（wire 命令核心 + Harness 协议）
    src_root = str(Path(__file__).resolve().parents[2])
    env = os.environ.copy()
    existing_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src_root + (":" + existing_path if existing_path else "")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "app",
            "--http",
            "--host",
            args.host,
            "--port",
            str(args.port),
        ],
        cwd=os.getcwd(),
        env=env,
        stdout=log_fp,
        stderr=log_fp,
        start_new_session=True,
    )
    _pid_path().write_text(str(process.pid), encoding="utf-8")
    log_fp.close()

    # 等 /health 就绪
    import urllib.request

    url = f"http://{args.host}:{args.port}/health"
    deadline = time.monotonic() + 10
    ok = False
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                ok = True
                break
        except Exception:
            if process.poll() is not None:
                break
            time.sleep(0.2)
    if not ok:
        print(f"service 启动失败（{url} 不可达）；日志: {log_path}", file=sys.stderr)
        return EXIT_SERVICE
    print(f"service 已启动: http://{args.host}:{args.port}（PID {process.pid}）")
    print(f"日志: {log_path}")
    return EXIT_OK


def _status() -> int:
    pid = _read_pid()
    if pid is None:
        print("service 未运行")
        return EXIT_OK
    if _alive(pid):
        print(f"service 运行中（PID {pid}）")
        return EXIT_OK
    print(f"service 已退出（PID {pid} 不存活）；移除陈旧 PID 文件")
    _pid_path().unlink(missing_ok=True)
    return EXIT_OK


def _stop() -> int:
    pid = _read_pid()
    if pid is None:
        print("service 未运行")
        return EXIT_OK
    if not _alive(pid):
        print(f"service 已退出（PID {pid}）")
        _pid_path().unlink(missing_ok=True)
        return EXIT_OK
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        print(f"停止失败: {exc}", file=sys.stderr)
        return EXIT_SERVICE
    deadline = time.monotonic() + 5
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    if _alive(pid):
        print("服务未在 5s 内退出，强制终止", file=sys.stderr)
        os.kill(pid, signal.SIGKILL)
    _pid_path().unlink(missing_ok=True)
    print(f"service 已停止（PID {pid}）")
    return EXIT_OK


def _logs(args) -> int:
    path = _log_path(args)
    if not path.is_file():
        print(f"日志不存在: {path}", file=sys.stderr)
        return EXIT_CLI
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"读取失败: {exc}", file=sys.stderr)
        return EXIT_CLI
    print(text[-4000:] or "(空日志)")
    return EXIT_OK
