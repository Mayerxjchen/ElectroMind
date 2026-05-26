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
    count_tokens_detail,
    format_context,
)

CONTEXT_MAX = int(os.getenv("PAGENT_CONTEXT_MAX", "128000"))

RESET = "\033[0m"
GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

HELP_TEXT = """Commands:
  /help          show this help
  /reset         clear session history
  /stats         show current stats
  /context       show context window usage (/ctx)
  /effort        show current reasoning_effort
  /effort <val>  set reasoning_effort (e.g. low, medium, high, 0.5, none to clear)
  /exit          quit
"""

BANNER_WIDTH = 76
LEFT_COL = 38
RIGHT_COL = 30
MASCOT = (
    "  .---.",
    "  | P |",
    "  '---'",
)


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


def print_banner(*, version, model_id, cwd, tools_count):
    use_color = sys.stdout.isatty()
    inner = BANNER_WIDTH - 2
    title = f"─ pagent v{version} "
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

    rows = [
        ("Welcome!", tips_header, GREEN, YELLOW),
        ("", tips[0], None, None),
        (MASCOT[0], tips[1], CYAN, None),
        (MASCOT[1], tips[2], CYAN, None),
        (MASCOT[2], tips[3], CYAN, None),
        ("", tips[4], None, None),
        (model_line, "Recent activity", None, YELLOW),
        (cwd_line, "No recent activity", None, None),
        (tools_line, "", None, None),
    ]

    print(top)
    for left, right, lc, rc in rows:
        print(
            _banner_row(left, right, use_color=use_color, left_color=lc, right_color=rc)
        )
    print(bottom)
    print()


def show_context(agent):
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


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("Please set DEEPSEEK_API_KEY first.")

    agent = Agent(
        llm=DeepSeek("deepseek-v4-flash"),
        session=Session("You are a concise helpful assistant."),
        tools=DEFAULT_TOOLS,
        max_turns=8,
    )

    print_banner(
        version=pagent.__version__,
        model_id=agent.llm.model_id,
        cwd=os.getcwd(),
        tools_count=len(agent.tool_schemas),
    )

    run_kwargs = {}

    while True:
        try:
            user_input = input(f"\n{GREEN}You>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{YELLOW}Bye.{RESET}")
            return

        if not user_input:
            continue
        if user_input == "/exit":
            print(f"{YELLOW}Bye.{RESET}")
            return
        if user_input == "/help":
            print(HELP_TEXT)
            continue
        if user_input == "/reset":
            agent.reset()
            print(f"{YELLOW}Session reset.{RESET}")
            continue
        if user_input == "/stats":
            print(f"{CYAN}{agent.stats}{RESET}")
            continue
        if user_input in ("/context", "/ctx"):
            show_context(agent)
            continue
        if user_input.startswith("/effort"):
            parts = user_input.split(None, 1)
            if len(parts) == 1:
                val = run_kwargs.get("reasoning_effort")
                print(f"{CYAN}reasoning_effort = {val!r}{RESET}")
            elif parts[1].strip().lower() == "none":
                run_kwargs.pop("reasoning_effort", None)
                print(f"{YELLOW}reasoning_effort cleared{RESET}")
            else:
                raw = parts[1].strip()
                try:
                    run_kwargs["reasoning_effort"] = float(raw)
                except ValueError:
                    run_kwargs["reasoning_effort"] = raw
                print(
                    f"{CYAN}reasoning_effort = {run_kwargs['reasoning_effort']!r}{RESET}"
                )
            continue

        prefix = f"{CYAN}Assistant>{RESET}"
        stop_spinner = asyncio.Event()
        spinner_task = asyncio.create_task(spinner(prefix, stop_spinner))
        try:
            has_token = False
            async for token in agent.arun(user_input, **run_kwargs):
                if not has_token:
                    stop_spinner.set()
                    await spinner_task
                    print(f"{prefix} ", end="", flush=True)
                has_token = True
                print(token, end="", flush=True)
            stop_spinner.set()
            await spinner_task
            if not has_token:
                last_message = (
                    agent.session.messages[-1] if agent.session.messages else {}
                )
                print(f"{prefix} ", end="", flush=True)
                if last_message.get("role") == "assistant" and last_message.get(
                    "tool_calls"
                ):
                    print(f"{YELLOW}[tool call, no visible text]{RESET}", end="")
                else:
                    print(f"{YELLOW}(no content){RESET}", end="")
            print()
        except KeyboardInterrupt:
            stop_spinner.set()
            await spinner_task
            print(f"\n{RED}[interrupted]{RESET}")


if __name__ == "__main__":
    asyncio.run(main())
