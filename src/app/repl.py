from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime

from prompt_toolkit.formatted_text import ANSI

from pagentv4 import DeepSeek, Runner
from pagentv4.tools import HARNESS_WEB_TOOLS

from .clean import clean_pagent, format_clean_report
from .config import ReplConfig, build_parser, config_from_args
from .render import (
    BLUE,
    DIM,
    RED,
    RESET,
    c,
    format_banner,
    print_command_header,
    print_command_result,
    render_turn,
)
from .terminal import emit, emit_prompt
from .tool_permit import build_app_tool_hooks

EXTRA_SYSTEM = (
    "你是 pagent，一名严谨的工程师。回答保持简洁、直接、准确；不要输出表情符号；"
    "不要使用寒暄、口号或不必要的解释。"
)


def read_prompt_line(*, color: bool, user_label: str = "you") -> str:
    message = ANSI(f"{BLUE}{user_label}> {RESET}") if color else f"{user_label}> "
    return emit_prompt(message)


async def open_runner(config: ReplConfig) -> Runner:
    api_key = config.resolved_api_key()
    if not api_key:
        raise SystemExit(
            "需要 API Key：运行交互式 pagent 完成 setup，"
            "或写入 ~/.pagent/pagent.toml，或 export DEEPSEEK_API_KEY"
        )

    thread_id = config.thread_id or f"thread-{datetime.now():%Y%m%d-%H%M%S}"
    provider_kwargs = {"apikey": api_key}
    if config.provider_base_url:
        provider_kwargs["base_url"] = config.provider_base_url
    provider = DeepSeek(config.resolved_model(), **provider_kwargs)
    return await Runner.create(
        thread_id,
        provider,
        overrides=config.thread_overrides(),
        extra_system=EXTRA_SYSTEM,
        max_turns=config.resolved_max_turns(),
        skill_roots=config.resolved_skill_roots(),
        tools=HARNESS_WEB_TOOLS,
        tool_hooks=build_app_tool_hooks(auto=config.permission_auto()),
    )


def split_prefixed_command(line: str) -> tuple[str, str] | None:
    if line.startswith("!!"):
        return ("sandbox", line[2:].strip())
    if line.startswith("!"):
        return ("host", line[1:].strip())
    return None


async def run_sandbox_command(command: str, runner: Runner, *, color: bool) -> None:
    print_command_header("sandbox", command, color=color)
    result = await runner.sandbox.commands.run(command)
    print_command_result(result.stdout, result.stderr, result.exit_code, color=color)


async def run_host_command(command: str, *, color: bool) -> None:
    print_command_header("host", command, color=color)
    shell = os.environ.get("SHELL") or "/bin/zsh"
    process = await asyncio.create_subprocess_exec(
        shell,
        "-lc",
        command,
        cwd=os.getcwd(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_raw, stderr_raw = await process.communicate()
    stdout = stdout_raw.decode("utf-8", errors="replace")
    stderr = stderr_raw.decode("utf-8", errors="replace")
    print_command_result(stdout, stderr, process.returncode or 0, color=color)


async def handle_prefixed_command(
    line: str,
    runner: Runner,
    *,
    color: bool,
) -> bool:
    parsed = split_prefixed_command(line)
    if parsed is None:
        return False

    target, command = parsed
    if not command:
        emit(c("empty command", RED, on=color))
        return True

    if target == "sandbox":
        await run_sandbox_command(command, runner, color=color)
        return True

    await run_host_command(command, color=color)
    return True


async def handle_command(cmd: str, runner: Runner, *, color: bool) -> bool:
    del color
    if cmd in ("/exit", "/quit"):
        return True
    if cmd == "/pwd":
        emit(runner.sandbox.workdir)
        return False
    if cmd == "/ls":
        entries = await runner.sandbox.files.list(runner.sandbox.home)
        for entry in entries:
            tag = "d" if entry.is_dir else "f"
            emit(f"  {tag} {entry.name}")
        return False
    if cmd == "/skills":
        if not runner.skills.names():
            emit("(no skills loaded)")
            return False
        for skill in runner.skills.list():
            emit(f"  {skill.name}: {skill.description}")
        return False
    if cmd == "/history":
        for message in runner.messages.data:
            preview = str(message.content)[:80].replace("\n", " ")
            emit(f"  [{message.role}] {preview}")
        return False
    emit(f"unknown command: {cmd}")
    return False


async def prompt(color: bool, *, user_label: str = "you") -> str | None:
    try:
        return await asyncio.to_thread(
            read_prompt_line, color=color, user_label=user_label
        )
    except (EOFError, KeyboardInterrupt):
        return None


def say_goodbye(*, color: bool) -> None:
    emit(c("bye", DIM, on=color), flush=True)


def format_fatal_error(exc: BaseException, *, phase: str) -> str:
    """Human-readable fatal error; keep traceback out of the REPL by default."""
    label = "关闭" if phase == "close" else "启动"
    name = type(exc).__name__
    module = type(exc).__module__ or ""
    if "asyncssh" in module or name.startswith("SFTP") or name == "DisconnectError":
        hint = (
            "请检查 SSH 别名、网络，以及远端 workdir 是否可写。"
            if phase == "start"
            else "SSH 连接可能已断开。"
        )
        return f"pagent {label}失败（SSH 沙箱）: {exc}\n  {hint}"
    if isinstance(exc, (FileNotFoundError, KeyError, ValueError)):
        return f"pagent {label}失败: {exc}"
    if isinstance(exc, OSError):
        return f"pagent {label}失败: {exc}"
    return f"pagent {label}失败: {name}: {exc}"


async def run_blocking_repl(config: ReplConfig, *, color: bool | None = None) -> int:
    use_color = sys.stdout.isatty() if color is None else color
    runner: Runner | None = None
    exit_code = 0
    had_user_turn = False
    try:
        runner = await open_runner(config)
        emit(format_banner(runner, color=use_color), flush=True)

        while True:
            line = await prompt(use_color, user_label=config.resolved_user_label())
            if line is None:
                emit()
                say_goodbye(color=use_color)
                break
            line = line.strip()
            if not line:
                continue
            if await handle_prefixed_command(line, runner, color=use_color):
                continue
            if line.startswith("/"):
                if await handle_command(line, runner, color=use_color):
                    say_goodbye(color=use_color)
                    break
                continue
            try:
                await render_turn(
                    runner,
                    line,
                    color=use_color,
                    user_label=config.resolved_user_label(),
                    assistant_label=config.resolved_assistant_label(),
                    permit_auto=config.permission_auto(),
                )
                had_user_turn = True
            except KeyboardInterrupt:
                emit()
                say_goodbye(color=use_color)
                break
    except BaseException as exc:
        if isinstance(exc, SystemExit):
            raise
        if isinstance(exc, KeyboardInterrupt):
            emit()
            say_goodbye(color=use_color)
        else:
            message = format_fatal_error(exc, phase="start")
            emit(c(message, RED, on=use_color), file=sys.stderr, flush=True)
            exit_code = 1
    finally:
        if runner is not None:
            try:
                await runner.close()
            except BaseException as exc:
                if isinstance(exc, SystemExit):
                    raise
                if exit_code == 0:
                    message = format_fatal_error(exc, phase="close")
                    emit(c(message, RED, on=use_color), file=sys.stderr, flush=True)
                    exit_code = 1
            keep = {runner.thread.id} if had_user_turn else set()
            report = clean_pagent(keep_thread_ids=keep)
            clean_message = format_clean_report(report)
            if clean_message:
                emit(c(clean_message, DIM, on=use_color), flush=True)
    return exit_code


async def run_repl(config: ReplConfig, *, color: bool | None = None) -> int:
    """TTY 默认底栏固定输入；管道/重定向或 ``--blocking`` 用阻塞模式。"""
    if sys.stdout.isatty() and not config.blocking:
        from .concurrent_repl import run_concurrent_repl

        return await run_concurrent_repl(config, color=color)
    return await run_blocking_repl(config, color=color)


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = config_from_args(args)
    if not config.resolved_api_key() and not args.wire:
        # 交互 REPL：缺 Key 时引导写入 ~/.pagent；--wire 由宿主（插件）先做 setup。
        from .setup import interactive_setup

        interactive_setup()
        config = config_from_args(args)
    if args.wire:
        from .wire import run_wire

        raise SystemExit(asyncio.run(run_wire(config)))
    try:
        code = asyncio.run(run_repl(config))
    except KeyboardInterrupt:
        emit()
        raise SystemExit(0) from None
    raise SystemExit(code)
