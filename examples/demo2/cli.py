"""Interactive CLI for :class:`pagent_live.LiveAgent` (duplex bus, ``ask_user``).

Usage:
    export DEEPSEEK_API_KEY="your-key"
    uv run examples/demo2/cli.py
"""

import asyncio
import os
import sys
from pathlib import Path

_DEMO2 = Path(__file__).resolve().parent
if str(_DEMO2) not in sys.path:
    sys.path.insert(0, str(_DEMO2))

from live_common import (  # noqa: E402
    CYAN,
    DIM,
    GREEN,
    RED,
    RESET,
    YELLOW,
    make_live_agent,
    print_banner,
    require_api_key,
    show_context,
    spinner,
)

from pagent import (  # noqa: E402
    ReasoningDelta,
    RunEnd,
    TextDelta,
    ToolCallBegin,
    ToolResult,
)
from pagent_live import HumanInputRequired, HumanReply, push_iwire  # noqa: E402

HELP_TEXT = """Commands:
  /help          show this help
  /reset         clear session history
  /stats         show current stats
  /context       show context window usage (/ctx)
  /effort        show current reasoning_effort
  /effort <val>  set reasoning_effort (e.g. low, medium, high, 0.5, none to clear)
  /verbose       toggle lifecycle events (TurnBegin, StepEnd, …)
  /exit          quit

When the model calls ask_user, you will be prompted; reply via push_iwire(agent.bus, HumanReply(...)).
"""


def preview_line(text: str, limit: int = 160) -> str:
    one_line = text.replace("\n", " ").strip()
    if len(one_line) > limit:
        return one_line[: limit - 1] + "…"
    return one_line


async def stream_reply(
    agent,
    user_input,
    prefix,
    run_kwargs,
    stop_spinner,
    spinner_task,
    *,
    verbose: bool,
):
    mode = None
    had_text = False
    had_tools = False

    def close_mode():
        nonlocal mode
        if mode is not None:
            print()
            mode = None

    async def stop_spinner_if_running():
        stop_spinner.set()
        if not spinner_task.done():
            await spinner_task

    async def begin_reasoning():
        nonlocal mode
        if mode == "reasoning":
            return
        await stop_spinner_if_running()
        if mode in ("answer", "tools"):
            print()
        print(f"{DIM}reasoning:{RESET} ", end="", flush=True)
        mode = "reasoning"

    async def begin_tools():
        nonlocal mode
        if mode == "tools":
            return
        await stop_spinner_if_running()
        if mode in ("reasoning", "answer"):
            print()
        mode = "tools"

    async def begin_answer():
        nonlocal mode
        if mode == "answer":
            return
        await stop_spinner_if_running()
        if mode in ("reasoning", "tools"):
            print()
        print(f"{prefix} ", end="", flush=True)
        mode = "answer"

    async def handle_event(event):
        if verbose and type(event).__name__ not in (
            "TextDelta",
            "ReasoningDelta",
            "ToolCallBegin",
            "ToolResult",
        ):
            close_mode()
            print(f"{DIM}  · {type(event).__name__}{RESET}", flush=True)
            return

        if isinstance(event, ReasoningDelta):
            await begin_reasoning()
            print(event.text, end="", flush=True)
        elif isinstance(event, ToolCallBegin):
            await begin_tools()
            nonlocal had_tools
            had_tools = True
            args = preview_line(event.arguments, 100)
            print(f"{DIM}  → {event.name}({args}){RESET}", flush=True)
        elif isinstance(event, HumanInputRequired):
            await stop_spinner_if_running()
            close_mode()
            print(f"\n{YELLOW}{event.question}{RESET}", flush=True)
            try:
                answer = await asyncio.to_thread(input, f"{GREEN}> {RESET}")
            except EOFError:
                answer = ""
            push_iwire(agent.bus, HumanReply(event.tool_call_id, answer.strip()))
        elif isinstance(event, ToolResult):
            await begin_tools()
            mark = f"{GREEN}✓{RESET}" if event.ok else f"{RED}✗{RESET}"
            body = preview_line(event.content, 200)
            print(f"{DIM}  {mark} {body}{RESET}", flush=True)
        elif isinstance(event, TextDelta):
            await begin_answer()
            nonlocal had_text
            had_text = True
            print(event.text, end="", flush=True)
        elif isinstance(event, RunEnd):
            if event.content and not had_text:
                await begin_answer()
                print(event.content, end="", flush=True)
                had_text = True
            elif not had_text and event.tool_calls:
                await begin_answer()
                print(
                    f"{YELLOW}[max turns ({agent.max_turns}): "
                    f"stopped while calling tools, no answer]{RESET}",
                    end="",
                    flush=True,
                )
            elif not had_text and not had_tools:
                print(f"{prefix} ", end="", flush=True)
                print(f"{YELLOW}(no content){RESET}", end="")

    async def drive_run():
        async for _ in agent.arun_events(user_input, **run_kwargs):
            pass

    run_task = asyncio.create_task(drive_run())
    idle_ticks = 0
    try:
        while True:
            event = await agent.bus.wait_owire(timeout=0.1)
            if event is not None:
                idle_ticks = 0
                await handle_event(event)
                continue
            if run_task.done() and agent.bus.owire.empty():
                break
            idle_ticks += 1
            if idle_ticks == 50:
                sys.stdout.write(f"{DIM}…{RESET}")
                sys.stdout.flush()
                idle_ticks = 0
        while (event := agent.bus.get_owire()) is not None:
            await handle_event(event)
    finally:
        await run_task

    await stop_spinner_if_running()
    close_mode()
    print()


async def main():
    require_api_key()
    workspace = os.path.realpath(os.getcwd())
    agent = make_live_agent(workspace)

    print_banner(
        model_id=agent.llm.model_id,
        cwd=workspace,
        tools_count=len(agent.tool_schemas),
    )

    run_kwargs = {}
    verbose = False

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
        if user_input == "/verbose":
            verbose = not verbose
            print(f"{CYAN}verbose = {verbose}{RESET}")
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
                agent,
                user_input,
                prefix,
                run_kwargs,
                stop_spinner,
                spinner_task,
                verbose=verbose,
            )
        except KeyboardInterrupt:
            stop_spinner.set()
            await spinner_task
            print(f"\n{RED}[interrupted]{RESET}")


if __name__ == "__main__":
    asyncio.run(main())
