"""Streaming: ``ReasoningDelta`` then ``TextDelta`` via ``agent.arun_events``.

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run examples/reasoning_stream.py
    uv run examples/reasoning_stream.py --zh   # 鸡兔同笼（中文）
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

from pagent import ReasoningDelta, RunEnd, TextDelta


async def main():
    require_api_key()
    question, zh = pick_question(sys.argv)
    agent = make_agent(zh=zh)

    print(f"Q: {question}\n")
    if use_color():
        print(f"{DIM}reasoning{RESET}: ", end="", flush=True)
    else:
        print("reasoning: ", end="", flush=True)

    answer_started = False
    async for event in agent.arun_events(question, reasoning_effort="medium"):
        if isinstance(event, ReasoningDelta):
            print(event.text, end="", flush=True)
        elif isinstance(event, TextDelta):
            if not answer_started:
                answer_started = True
                if use_color():
                    print(f"\n{RESET}{GREEN}answer{RESET}: ", end="", flush=True)
                else:
                    print("\nanswer: ", end="", flush=True)
            print(event.text, end="", flush=True)
        elif isinstance(event, RunEnd):
            print()


if __name__ == "__main__":
    asyncio.run(main())
