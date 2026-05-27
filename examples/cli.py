"""Minimal interactive CLI — streams answer text via ``agent.arun()``.

Usage:
    export DEEPSEEK_API_KEY="your-key"
    uv run examples/cli.py

For tool/reasoning visibility, use ``examples/cli_events.py``.
"""

import asyncio
import os

from cli_common import (
    CYAN,
    GREEN,
    RED,
    RESET,
    YELLOW,
    make_agent,
    print_banner,
    require_api_key,
    show_context,
    spinner,
)

HELP_TEXT = """Commands:
  /help          show this help
  /reset         clear session history
  /stats         show current stats
  /context       show context window usage (/ctx)
  /effort        show current reasoning_effort
  /effort <val>  set reasoning_effort (e.g. low, medium, high, 0.5, none to clear)
  /exit          quit
"""


async def stream_reply(
    agent, user_input, prefix, run_kwargs, stop_spinner, spinner_task
):
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
        last_message = agent.session.messages[-1] if agent.session.messages else {}
        print(f"{prefix} ", end="", flush=True)
        if last_message.get("role") == "assistant" and last_message.get("tool_calls"):
            print(f"{YELLOW}[tool call, no visible text]{RESET}", end="")
        else:
            print(f"{YELLOW}(no content){RESET}", end="")
    print()


async def main():
    require_api_key()
    workspace = os.path.realpath(os.getcwd())
    agent = make_agent(workspace, advanced=False)

    print_banner(
        model_id=agent.llm.model_id,
        cwd=workspace,
        tools_count=len(agent.tool_schemas),
        subtitle="mode: text (arun)",
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
            await stream_reply(
                agent, user_input, prefix, run_kwargs, stop_spinner, spinner_task
            )
        except KeyboardInterrupt:
            stop_spinner.set()
            await spinner_task
            print(f"\n{RED}[interrupted]{RESET}")


if __name__ == "__main__":
    asyncio.run(main())
