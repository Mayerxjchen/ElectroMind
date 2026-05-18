import asyncio
import os
import sys

from pagent import DEFAULT_TOOLS, Agent, DeepSeek, Session

RESET = "\033[0m"
GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

HELP_TEXT = """Commands:
  /help   show this help
  /reset  clear session history
  /stats  show current stats
  /exit   quit
"""


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

    print(f"{CYAN}pagent CLI (streaming){RESET}")
    print(f"{YELLOW}Type /help for commands.{RESET}")

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

        prefix = f"{CYAN}Assistant>{RESET}"
        stop_spinner = asyncio.Event()
        spinner_task = asyncio.create_task(spinner(prefix, stop_spinner))
        try:
            has_token = False
            async for token in agent.arun(user_input):
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
