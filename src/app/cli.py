"""``app.cli:main`` — CLI 唯一入口：参数解析与命令分发。

分层边界（见 docs/superpowers/specs/2026-08-01-cli-professional-refactor.md）：

- 本模块：解析 argv、打印弃用告警、分派到 commands/
- commands/：每个顶层命令的应用逻辑
- repl / render / terminal：TTY 交互体验
- output/：人类输出与机器输出（print mode）
- wire / http_server：既有后端模式（Desktop/插件兼容）
"""

from __future__ import annotations

import asyncio
import sys

from .cli_parser import SUBCOMMANDS, build_parser, deprecation_warnings
from .exitcodes import EXIT_CANCELLED, EXIT_CLI, EXIT_OK, EXIT_UNKNOWN


def print_version() -> int:
    print(print_version_text())
    return EXIT_OK


def print_completion(shell: str) -> int:
    """生成 bash / zsh / fish 补全脚本（从 parser 动态提取 flag 清单）。"""
    if shell not in ("bash", "zsh", "fish"):
        print(f"不支持的 shell: {shell}（支持 bash|zsh|fish）", file=sys.stderr)
        return EXIT_CLI
    from .completion import completion_script

    print(completion_script(shell), end="")
    return EXIT_OK


def dispatch_subcommand(name: str, rest: list[str], *, options=None) -> int:
    """顶层子命令分派；每个命令模块负责自己的 parser 与退出码。"""
    if name == "session":
        from .commands import session

        return session.run(rest)
    if name == "config":
        from .commands import config

        return config.run(rest, options=options)
    if name == "skills":
        from .commands import skills

        return skills.run(rest)
    if name == "doctor":
        from .commands import doctor

        return doctor.run(rest)
    if name == "version":
        return print_version()
    if name == "completion":
        return print_completion(rest[0] if rest else "bash")
    if name == "app":
        from .commands import app

        return app.run(rest)
    if name == "service":
        from .commands import service

        return service.run(rest)
    return EXIT_CLI


def _run_print_mode(config, options) -> int:
    from .commands import print_mode

    return asyncio.run(print_mode.run(config, options))


def _run_interactive(config, options) -> int:
    from .commands import interactive

    return interactive.run(config, options)


def _detach_subcommand_flags(argv: list[str], subcommand: str) -> list[str]:
    """子命令位置之后的顶层已知 flag（--port/--host）重新传给子命令。

    顶层 parser 会吞掉这些 flag（如 service start --port X 的 --port），
    但子命令模式下的语义属于子命令，需原样附加回子命令 argv。
    """
    try:
        idx = argv.index(subcommand)
    except ValueError:
        return []
    extras: list[str] = []
    tokens = argv[idx + 1 :]
    for i, token in enumerate(tokens):
        if token in ("--port", "--host") and i + 1 < len(tokens):
            extras += [token, tokens[i + 1]]
    return extras


def _emit_deprecations(warnings: list[str]) -> None:
    for warning in warnings:
        print(f"警告: {warning}", file=sys.stderr)


def print_about() -> int:
    """--about：Logo + 版本（Logo 不再出现在默认启动界面）。"""
    from .render import format_logo

    color = sys.stdout.isatty()
    print(format_logo(color=color))
    print(f"ElectroMind {print_version_text()}")
    return EXIT_OK


def print_version_text() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("electromind")
    except PackageNotFoundError:
        pass
    import tomllib
    from pathlib import Path

    candidate = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        data = tomllib.loads(candidate.read_text(encoding="utf-8"))
        project_version = data.get("project", {}).get("version")
        if isinstance(project_version, str) and project_version:
            return project_version
    except (OSError, tomllib.TOMLDecodeError):
        pass
    return "0.0.0+unknown"


def _dispatch(
    args, argv: list[str], unknown: list[str] | None = None, *, parser=None
) -> None:
    """参数解析后的命令分派（不捕获异常；由 main 统一处理错误输出）。"""
    unknown = unknown or []
    # ---- 既有后端模式（Desktop / 插件兼容，行为不变） ----
    from .config import config_from_args

    if args.wire or args.http:
        config = config_from_args(args)
        if args.wire:
            from .wire import run_wire

            raise SystemExit(asyncio.run(run_wire(config)))
        from .http_server import run_http

        raise SystemExit(run_http(config, host=args.host, port=args.port))

    # ---- 顶层子命令（electromind session ... 等） ----
    # 子命令自己的 flag（如 config --scope、service --port）由子命令 parser 处理：
    # parse_known_args 把未知 flag 留出来；顶层已知 flag 在子命令位置时也归子命令。
    prompt = list(args.prompt or ())
    if prompt and prompt[0] in SUBCOMMANDS and not args.print_mode:
        from .config import RunOptions

        options = RunOptions.from_args(args)
        rest = (
            list(prompt[1:]) + _detach_subcommand_flags(argv, prompt[0]) + list(unknown)
        )
        raise SystemExit(dispatch_subcommand(prompt[0], rest, options=options))
    if unknown:
        # 主路径：未知 flag 明确报错（exit 2）
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")

    # ---- 主路径：交互 / 非交互 ----
    from .config import RunOptions

    options = RunOptions.from_args(args)
    config = config_from_args(args)

    if args.print_mode:
        raise SystemExit(_run_print_mode(config, options))
    raise SystemExit(_run_interactive(config, options))


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args, unknown = parser.parse_known_args(argv)
    _emit_deprecations(deprecation_warnings(argv, args))

    # ---- --version / --about：版本与 Logo（启动界面不再显示 Logo） ----
    if args.version:
        raise SystemExit(print_version())
    if args.about:
        raise SystemExit(print_about())

    # ---- 错误处理契约：默认无完整 traceback；--debug 才输出 ----
    try:
        _dispatch(args, argv, unknown, parser=parser)
    except KeyboardInterrupt:
        raise SystemExit(EXIT_CANCELLED) from None
    except SystemExit:
        raise
    except Exception as exc:
        if args.debug:
            import traceback

            traceback.print_exc()
        print(f"内部错误: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_UNKNOWN) from None
