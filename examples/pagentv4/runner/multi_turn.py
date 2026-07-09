"""v4 多轮对话 — `Runner.create()` + 多次 `runner.run()`。

同一个 thread 里反复跑，messages 自动累积、持久化。

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.pagentv4.runner.multi_turn
"""

import asyncio
import os
import sys

from pagentv4 import DeepSeek, Runner, TextDelta

TURNS = [
    "你先记住一个数：42。",
    "把它乘以 2，然后减去 1。",
    "最开始我让你记住的那个数是多少？",
]


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请先 export DEEPSEEK_API_KEY=<your-key>")

    runner = await Runner.create(
        "multi-turn-demo",
        DeepSeek("deepseek-v4-flash"),
        overrides={"backend": "local"},
        extra_system="你是一个记性好的助手，回答简短。",
    )
    try:
        for question in TURNS:
            print(f"\nQ: {question}")
            print("A: ", end="", flush=True)
            async for event in runner.run(question):
                if isinstance(event, TextDelta):
                    sys.stdout.write(event.text)
                    sys.stdout.flush()
            print()

        print(f"\n累计消息条数：{len(runner.messages.data)}")
    finally:
        await runner.close()


if __name__ == "__main__":
    asyncio.run(main())
