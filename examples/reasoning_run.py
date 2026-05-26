"""Non-streaming: read ``reasoning_content`` from ``agent.run`` → ``RunEnd``.

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run examples/reasoning_run.py
    uv run examples/reasoning_run.py --zh   # 鸡兔同笼（中文）
"""

import asyncio
import sys

from reasoning_common import (
    DIM,
    GREEN,
    RESET,
    make_agent,
    pick_question,
    require_api_key,
    use_color,
)


async def main():
    require_api_key()
    question, zh = pick_question(sys.argv)
    agent = make_agent(zh=zh)
    end = await agent.run(question, reasoning_effort="medium")

    print(f"Q: {question}\n")
    if end.reasoning_content:
        label = f"{DIM}reasoning{RESET}: " if use_color() else "reasoning: "
        print(f"{label}{end.reasoning_content}\n")
    answer_label = f"{GREEN}answer{RESET}: " if use_color() else "answer: "
    print(f"{answer_label}{end.content}\n")

    last = agent.session.messages[-1]
    if last.get("reasoning_content"):
        print(
            f"(session assistant message also has reasoning_content, "
            f"{len(last['reasoning_content'])} chars)"
        )


if __name__ == "__main__":
    asyncio.run(main())
