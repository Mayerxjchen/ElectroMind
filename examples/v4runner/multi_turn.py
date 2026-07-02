"""v4 多轮对话 — 手动持有 `Runner` + `Messages`。

`run_agent` 每次都从零开始；如果需要跨轮记忆，
就要显式创建一个 `Runner` 和一个 `Messages` 容器，
让每次 `runner.arun(...)` 都往同一个容器里追加。

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.v4runner.multi_turn
"""

import asyncio
import os
import sys

from pagentv4 import Agent, DeepSeek, Messages, Runner, TextDelta

TURNS = [
    "你先记住一个数：42。",
    "把它乘以 2，然后减去 1。",
    "最开始我让你记住的那个数是多少？",
]


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请先 export DEEPSEEK_API_KEY=<your-key>")

    agent = Agent(
        DeepSeek("deepseek-v4-flash"),
        system="你是一个记性好的助手，回答简短。",
    )
    runner = Runner()
    messages = Messages()

    for question in TURNS:
        print(f"\nQ: {question}")
        print("A: ", end="", flush=True)
        async for event in runner.arun(agent, question, messages):
            if isinstance(event, TextDelta):
                sys.stdout.write(event.text)
                sys.stdout.flush()
        print()

    print(f"\n累计消息条数：{len(messages.data)}")


if __name__ == "__main__":
    asyncio.run(main())
