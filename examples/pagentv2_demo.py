"""pagentv2 demo — streaming ``arun()`` on harder prompts.

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.pagentv2_demo

deepseek-v4-flash streams ``reasoning_content`` first, then ``content``.
This demo prints both as they arrive (like examples/reasoning_stream.py).
"""

import asyncio
import os
import sys

from pagentv2 import Agent, DeepSeek, ReasoningDelta, TextDelta, TurnResult

HARD_QUESTIONS = [
    (
        "三个逻辑学家去酒吧。酒保问：你们都要啤酒吗？"
        "第一位说：我不知道。第二位也说：我不知道。"
        "第三位说：是的，我们都要啤酒。"
        "酒保为什么会笑？第一位现在能推断出自己要什么吗？逐步推理。"
    ),
    (
        "一个家庭有两个孩子，已知至少一个是男孩。"
        "两个孩子都是男孩的概率是多少？"
        "很多人答 1/2，请说明为什么错了，并给出正确答案。"
    ),
    ("不能用乘法运算符，如何用加法算出 17×23？给出一种清晰算法，并手算验证结果。"),
    (
        "两根不均匀的绳子，每根烧完恰好 60 分钟（但各段燃烧速度不同）。"
        "如何用它们测出 45 分钟？只说明操作步骤，不要跳步。"
    ),
]

RUN_QUESTION = (
    "下面 Python 代码输出什么？只给最终数字，并一句话说明原因。\n"
    "def f(n):\n"
    "    return n if n < 2 else f(n - 1) + f(n - 2)\n"
    "print(f(10))"
)

GRAY = "\033[90m"
RESET = "\033[0m"


def use_color() -> bool:
    return sys.stdout.isatty()


async def stream_reply(agent: Agent, question: str) -> str:
    print(f"\n{'─' * 60}")
    print(f"Q: {question}")
    if use_color():
        sys.stdout.write(GRAY)
    print("reasoning: ", end="", flush=True)

    parts: list[str] = []
    answer_started = False

    async for event in agent.arun(question, reasoning_effort="medium"):
        if isinstance(event, ReasoningDelta):
            sys.stdout.write(event.text)
            sys.stdout.flush()

        elif isinstance(event, TextDelta):
            if not answer_started:
                answer_started = True
                if use_color():
                    sys.stdout.write(RESET)
                print("\nanswer: ", end="", flush=True)
            parts.append(event.text)
            sys.stdout.write(event.text)
            sys.stdout.flush()

    if use_color() and not answer_started:
        sys.stdout.write(RESET)

    print()
    return "".join(parts)


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit(
            "Please set DEEPSEEK_API_KEY: export DEEPSEEK_API_KEY='your-key'"
        )

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    agent = Agent(
        DeepSeek("deepseek-v4-flash"),
        system=(
            "You are a rigorous problem solver. "
            "For logic and math, reason step by step before the final answer."
        ),
    )

    for question in HARD_QUESTIONS:
        await stream_reply(agent, question)

    result = None
    async for event in agent.arun(RUN_QUESTION, reasoning_effort="medium"):
        if isinstance(event, TurnResult):
            result = event
    print(f"\n{'─' * 60}")
    print(f"Q: {RUN_QUESTION}")
    print(f"A: {result.content if result else ''}")

    print(f"\nMessages in session: {len(agent.messages)}")


if __name__ == "__main__":
    asyncio.run(main())
