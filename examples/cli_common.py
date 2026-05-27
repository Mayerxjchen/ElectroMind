"""Shared helpers for ``examples/cli.py`` and ``examples/cli_events.py``."""

import asyncio
import os
import sys

import pagent
from pagent import (
    BACKEND_TIKTOKEN,
    DEFAULT_TOOLS,
    Agent,
    DeepSeek,
    Session,
    bash,
    count_tokens_detail,
    format_context,
    readfile,
)

CLI_TOOLS = [*DEFAULT_TOOLS, readfile, bash]

CONTEXT_MAX = int(os.getenv("PAGENT_CONTEXT_MAX", "128000"))

RESET = "\033[0m"
GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

BANNER_WIDTH = 76
LEFT_COL = 38
RIGHT_COL = 30
MASCOT = (
    "  .---.",
    "  | P |",
    "  '---'",
)


def cli_system_prompt(workspace: str, *, advanced: bool = False) -> str:
    base = f"You are a helpful assistant.\nWorkspace root: {workspace}\n"
    if not advanced:
        return base
    return (
        base + "readfile accepts absolute paths, paths relative to the workspace root, "
        "or ~/...; tilde and environment variables in paths are expanded. "
        "Each call returns up to 500 code points; use offset to read the next window. "
        "bash runs whitelisted commands in the workspace; currently only ls "
        "(paths must stay under the workspace root)."
    )


def make_agent(workspace: str, *, advanced: bool = False) -> Agent:
    return Agent(
        llm=DeepSeek("deepseek-v4-flash"),
        session=Session(cli_system_prompt(workspace, advanced=advanced)),
        tools=CLI_TOOLS,
        max_turns=8,
    )


def require_api_key():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("Please set DEEPSEEK_API_KEY first.")


def _fit(text, width):
    if len(text) > width:
        return text[: width - 1] + "…"
    return text.ljust(width)


def _banner_row(left, right="", *, use_color, left_color=None, right_color=None):
    left_cell = _fit(left, LEFT_COL)
    right_cell = _fit(right, RIGHT_COL)
    if use_color:
        if left_color:
            left_cell = f"{left_color}{left_cell}{RESET}"
        if right_color:
            right_cell = f"{right_color}{right_cell}{RESET}"
        return f"{CYAN}│{RESET} {left_cell} {CYAN}│{RESET} {right_cell} {CYAN}│{RESET}"
    return f"│ {left_cell} │ {right_cell} │"


def print_banner(*, model_id, cwd, tools_count, subtitle: str = ""):
    use_color = sys.stdout.isatty()
    inner = BANNER_WIDTH - 2
    title = f"─ pagent v{pagent.__version__} "
    top = "┌" + title + "─" * (inner - len(title)) + "┐"
    bottom = "└" + "─" * inner + "┘"

    if use_color:
        top = f"{CYAN}{top}{RESET}"
        bottom = f"{CYAN}{bottom}{RESET}"

    tips_header = "Tips for getting started"
    tips = (
        "• /help — show commands",
        "• /context — token usage",
        "• /reset — clear session",
        "• /stats — run statistics",
        "• Set DEEPSEEK_API_KEY",
    )
    model_line = f'Model: DeepSeek("{model_id}")'
    cwd_line = f"cwd: {cwd}"
    tools_line = f"Tools: {tools_count}"
    mode_line = subtitle or ""

    rows = [
        ("Welcome!", tips_header, GREEN, YELLOW),
        ("", tips[0], None, None),
        (MASCOT[0], tips[1], CYAN, None),
        (MASCOT[1], tips[2], CYAN, None),
        (MASCOT[2], tips[3], CYAN, None),
        ("", tips[4], None, None),
        (model_line, "Recent activity", None, YELLOW),
        (cwd_line, "No recent activity", None, None),
        (tools_line, mode_line, None, None),
    ]

    print(top)
    for left, right, lc, rc in rows:
        print(
            _banner_row(left, right, use_color=use_color, left_color=lc, right_color=rc)
        )
    print(bottom)
    print()


def show_context(agent: Agent):
    detail = count_tokens_detail(
        agent.session.messages,
        tools=agent.tool_schemas,
        model="gpt-4o",
        backend=BACKEND_TIKTOKEN,
        max_tokens=CONTEXT_MAX,
    )
    print(format_context(detail))


async def spinner(prefix, stop_event):
    i = 0
    while not stop_event.is_set():
        frame = SPINNER_FRAMES[i % len(SPINNER_FRAMES)]
        sys.stdout.write(f"\r{prefix} {frame}")
        sys.stdout.flush()
        i += 1
        await asyncio.sleep(0.08)
    sys.stdout.write("\r" + " " * (len(prefix) + 2) + "\r")
    sys.stdout.flush()
