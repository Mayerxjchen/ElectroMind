"""pagentv2 tools demo — multi-turn ``arun()`` with tool calls.

The model may call tools across several turns; ``arun()`` streams the full
timeline: ``ToolCallBegin`` → ``ToolResult`` → more text → ``TurnResult``.

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.pagentv2_tools
"""

import asyncio
import os
import sys

from pagentv2 import (
    Agent,
    DeepSeek,
    ReasoningDelta,
    TextDelta,
    ToolCallBegin,
    ToolResult,
    TurnBegin,
    TurnEnd,
    tool,
)

WEATHER = {
    "xiamen": "24°C, cloudy",
    "beijing": "12°C, clear",
    "shanghai": "18°C, light rain",
}

CYAN = "\033[36m"
DIM = "\033[90m"
GREEN = "\033[32m"
RESET = "\033[0m"
YELLOW = "\033[33m"

QUESTION = (
    "厦门和北京的温差是多少？先分别查天气，再用计算器算出差值的绝对值。"
    "最后一句话给出答案。"
)


@tool()
def get_weather(city: str) -> str:
    """Look up weather for a city.

    Args:
        city: City name, e.g. Xiamen or Beijing.
    """
    key = city.strip().lower()
    return WEATHER.get(key, f"no data for {city!r}; try Xiamen, Beijing, Shanghai")


@tool()
def calc(expression: str) -> str:
    """Evaluate a simple arithmetic expression.

    Args:
        expression: Digits, + - * / ( ) and spaces only, e.g. ``abs(24 - 12)``.
    """
    allowed = set("0123456789+-*/(). abs")
    if not all(c in allowed for c in expression):
        return "error: only basic arithmetic"
    try:
        return str(eval(expression, {"__builtins__": {}}, {"abs": abs}))
    except Exception as exc:
        return f"error: {exc}"


def use_color() -> bool:
    return sys.stdout.isatty()


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit(
            "Please set DEEPSEEK_API_KEY: export DEEPSEEK_API_KEY='your-key'"
        )

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    color = use_color()
    agent = Agent(
        DeepSeek("deepseek-v4-flash"),
        system="You are a helpful assistant. Use tools when needed; be concise.",
        tools=[get_weather, calc],
    )

    print(f"Q: {QUESTION}\n")

    turns = 0
    answer = ""
    turn_text: list[str] = []
    in_reasoning = False

    async for event in agent.arun(QUESTION):
        if isinstance(event, TurnBegin):
            turn_text = []
            in_reasoning = False

        elif isinstance(event, ReasoningDelta):
            if not in_reasoning:
                in_reasoning = True
                if color:
                    sys.stdout.write(DIM)
                print("reasoning: ", end="", flush=True)
            sys.stdout.write(event.text)
            sys.stdout.flush()

        elif isinstance(event, ToolCallBegin):
            if in_reasoning and color:
                sys.stdout.write(RESET)
            in_reasoning = False
            prefix = (
                f"{CYAN}tool → {event.name}({event.arguments}){RESET}"
                if color
                else (f"tool → {event.name}({event.arguments})")
            )
            print(prefix)

        elif isinstance(event, ToolResult):
            mark = "ok" if event.ok else "fail"
            line = event.content.replace("\n", " ")
            if color:
                tone = GREEN if event.ok else YELLOW
                print(f"  {tone}{mark}: {line}{RESET}")
            else:
                print(f"  {mark}: {line}")

        elif isinstance(event, TextDelta):
            if in_reasoning:
                if color:
                    sys.stdout.write(RESET)
                print()
                in_reasoning = False
            sys.stdout.write(event.text)
            sys.stdout.flush()
            turn_text.append(event.text)

        elif isinstance(event, TurnEnd):
            if in_reasoning and color:
                sys.stdout.write(RESET)
            in_reasoning = False
            turns += 1
            if event.stop_reason == "no_tool_calls":
                answer = "".join(turn_text)
            if color:
                print(f"\n{DIM}── turn {turns} done ──{RESET}")
            else:
                print(f"\n── turn {turns} done ──")

    print(f"\nAnswer: {answer}")
    print(f"Turns: {turns}  |  Messages: {len(agent.messages)}")


if __name__ == "__main__":
    asyncio.run(main())
