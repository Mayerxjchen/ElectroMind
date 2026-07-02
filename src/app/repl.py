from __future__ import annotations

import asyncio
import sys
from datetime import datetime

from pagentv4 import (
    DeepSeek,
    ReasoningDelta,
    Runner,
    TextDelta,
    ToolCallBegin,
    ToolResult,
)

from .config import ReplConfig, build_parser, config_from_args

EXTRA_SYSTEM = "你是 pagent 。回答简短直接。"

# ANSI — basic 8-color, keep output readable not decorative
CYAN = "\033[36m"
DIM = "\033[90m"
GREEN = "\033[32m"
RED = "\033[31m"
BLUE = "\033[34m"
YELLOW = "\033[33m"
RESET = "\033[0m"

INNER = 54  # chars between │ borders


def shorten(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    head = max(1, (width - 1) // 2)
    tail = max(1, width - head - 1)
    return f"{text[:head]}…{text[-tail:]}"


def c(text: str, code: str, *, on: bool) -> str:
    return f"{code}{text}{RESET}" if on else text


def row(key: str, value: str, *, color: bool, value_code: str = "") -> str:
    label = f"{key:<8}"
    slot = INNER - len(label)
    text = shorten(value, slot)
    if value_code:
        text = c(text, value_code, on=color)
    line = f"│ {c(label, DIM, on=color)}{text:<{slot}} │"
    if color:
        return c(line, DIM, on=True)
    return f"│ {label}{text:<{slot}} │"


def format_sandbox_line(runner: Runner) -> str:
    thread = runner.thread
    backend = thread.spec.backend
    if backend == "ssh":
        alias = thread.spec.ssh_host or "?"
        conn = (runner.sandbox.spec.connection or {}) if runner.sandbox.spec else {}
        user = conn.get("user", "")
        host = conn.get("host", "")
        target = f"{user}@{host}" if user and host else alias
        return f"ssh · {alias} · {target}"
    if backend in ("docker", "podman"):
        image = thread.spec.image or "?"
        return f"{backend} · {image} · {runner.sandbox.home}"
    return f"local · {runner.sandbox.home}"


def format_banner(runner: Runner, *, color: bool) -> str:
    thread = runner.thread
    status = "新建" if thread.created else "续聊"
    status_color = YELLOW if thread.created else GREEN

    model = thread.spec.model or "deepseek-v4-flash"
    sandbox = format_sandbox_line(runner)
    workdir = runner.sandbox.workdir
    turns = sum(1 for m in runner.messages.data if m.role == "user")
    skills = ", ".join(runner.skills.names()) or "—"

    bar = "─" * (INNER - 6)
    top = c(f"╭─ pagent {bar}╮", CYAN, on=color)
    bottom = c(f"╰{'─' * (INNER + 2)}╯", DIM, on=color)

    lines = [
        top,
        row("thread", f"{thread.id} · {status}", color=color, value_code=status_color),
        row("model", model, color=color),
        row("sandbox", sandbox, color=color),
        row("workdir", workdir, color=color),
        row("turns", f"{turns} prior · max {runner.agent.max_turns}", color=color),
        row("skills", skills, color=color),
        bottom,
    ]

    if thread.spec.backend == "ssh":
        lines.insert(
            5,
            row("messages", str(thread.root / "messages.jsonl"), color=color),
        )

    if thread.ignored_overrides:
        ignored = ", ".join(thread.ignored_overrides)
        note = shorten(f"spec 已冻结，忽略：{ignored}", INNER)
        lines.append(c(f"  {note}", DIM, on=color))

    lines.append(c("  /exit  /pwd  /ls  /skills  /history", BLUE, on=color))
    lines.append("")
    return "\n".join(lines)


async def render_turn(runner: Runner, user_input: str, *, color: bool) -> None:
    in_reasoning = False
    async for event in runner.run(user_input):
        if isinstance(event, ReasoningDelta):
            if not in_reasoning:
                in_reasoning = True
                if color:
                    sys.stdout.write(DIM)
                sys.stdout.write("reasoning: ")
            sys.stdout.write(event.text)
            sys.stdout.flush()

        elif isinstance(event, ToolCallBegin):
            if in_reasoning:
                if color:
                    sys.stdout.write(RESET)
                print()
            in_reasoning = False
            line = f"tool → {event.name}({event.arguments})"
            print(f"{CYAN}{line}{RESET}" if color else line)

        elif isinstance(event, ToolResult):
            body = event.content.replace("\n", " ")
            if len(body) > 200:
                body = body[:200] + "…"
            mark = "ok" if event.ok else "fail"
            palette = GREEN if event.ok else RED
            print(f"  {palette}{mark}{RESET}: {body}" if color else f"  {mark}: {body}")

        elif isinstance(event, TextDelta):
            if in_reasoning:
                if color:
                    sys.stdout.write(RESET)
                print()
                in_reasoning = False
            sys.stdout.write(event.text)
            sys.stdout.flush()

    if in_reasoning and color:
        sys.stdout.write(RESET)
    print()


async def open_runner(config: ReplConfig) -> Runner:
    api_key = config.resolved_api_key()
    if not api_key:
        raise SystemExit(
            "需要 API Key：在 pagent.toml [provider] 设置 api_key，或 export DEEPSEEK_API_KEY"
        )

    thread_id = config.thread_id or f"thread-{datetime.now():%Y%m%d-%H%M%S}"
    provider_kwargs = {"apikey": api_key}
    if config.provider_base_url:
        provider_kwargs["base_url"] = config.provider_base_url
    provider = DeepSeek(config.resolved_model(), **provider_kwargs)
    return await Runner.open(
        thread_id,
        provider,
        overrides=config.thread_overrides(),
        extra_system=EXTRA_SYSTEM,
        max_turns=config.resolved_max_turns(),
        skill_roots=config.resolved_skill_roots(),
    )


async def handle_command(cmd: str, runner: Runner, *, color: bool) -> bool:
    if cmd in ("/exit", "/quit"):
        return True
    if cmd == "/pwd":
        print(runner.sandbox.workdir)
        return False
    if cmd == "/ls":
        entries = await runner.sandbox.files.list(runner.sandbox.home)
        for entry in entries:
            tag = "d" if entry.is_dir else "f"
            print(f"  {tag} {entry.name}")
        return False
    if cmd == "/skills":
        if not runner.skills.names():
            print("(no skills loaded)")
            return False
        for skill in runner.skills.list():
            print(f"  {skill.name}: {skill.description}")
        return False
    if cmd == "/history":
        for message in runner.messages.data:
            preview = str(message.content)[:80].replace("\n", " ")
            print(f"  [{message.role}] {preview}")
        return False
    print(f"unknown command: {cmd}")
    return False


async def prompt(color: bool) -> str | None:
    marker = f"{BLUE}you>{RESET} " if color else "you> "
    try:
        return await asyncio.to_thread(input, marker)
    except (EOFError, KeyboardInterrupt):
        return None


def say_goodbye(*, color: bool) -> None:
    print(c("bye", DIM, on=color), flush=True)


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


async def run_repl(config: ReplConfig, *, color: bool | None = None) -> int:
    use_color = sys.stdout.isatty() if color is None else color
    runner: Runner | None = None
    exit_code = 0
    try:
        runner = await open_runner(config)
        print(format_banner(runner, color=use_color), flush=True)

        while True:
            line = await prompt(use_color)
            if line is None:
                print()
                say_goodbye(color=use_color)
                break
            line = line.strip()
            if not line:
                continue
            if line.startswith("/"):
                if await handle_command(line, runner, color=use_color):
                    say_goodbye(color=use_color)
                    break
                continue
            try:
                await render_turn(runner, line, color=use_color)
            except KeyboardInterrupt:
                print()
                say_goodbye(color=use_color)
                break
    except BaseException as exc:
        if isinstance(exc, SystemExit):
            raise
        if isinstance(exc, KeyboardInterrupt):
            print()
            say_goodbye(color=use_color)
        else:
            message = format_fatal_error(exc, phase="start")
            print(c(message, RED, on=use_color), file=sys.stderr, flush=True)
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
                    print(c(message, RED, on=use_color), file=sys.stderr, flush=True)
                    exit_code = 1
    return exit_code


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    config = config_from_args(parser.parse_args(argv))
    try:
        code = asyncio.run(run_repl(config))
    except KeyboardInterrupt:
        print()
        raise SystemExit(0) from None
    raise SystemExit(code)
