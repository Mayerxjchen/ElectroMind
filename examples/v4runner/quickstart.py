"""v4 quick start — 一行 `run_agent()` 尝鲜。

演示 pagentv4 最简用法：不管理 Runner，也不管理 Messages，
`run_agent` 内部临时创建一次 Messages 跑完就丢。
适合脚本、REPL、快速试模型。

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.v4runner.quickstart
"""

import asyncio
import os
import sys

from pagentv4 import Agent, DeepSeek, run_agent


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请先 export DEEPSEEK_API_KEY=<your-key>")

    agent = Agent(
        DeepSeek("deepseek-v4-flash"),
        system="你是一个简洁的助手，回答不超过两句。",
    )

    async for text in run_agent(
        agent, "用一句话解释什么是尾递归。", return_type="text"
    ):
        sys.stdout.write(text)
        sys.stdout.flush()
    print()


if __name__ == "__main__":
    asyncio.run(main())
