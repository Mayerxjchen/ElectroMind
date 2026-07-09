"""v4 quick start — `Runner.create()` 尝鲜。

打开一个 thread，跑一轮，关掉。适合脚本和快速试模型。

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.pagentv4.runner.quickstart
"""

import asyncio
import os
import sys
from datetime import datetime

from pagentv4 import DeepSeek, Runner


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请先 export DEEPSEEK_API_KEY=<your-key>")

    thread_id = f"quickstart-{datetime.now():%Y%m%d-%H%M%S}"
    runner = await Runner.create(
        thread_id,
        DeepSeek("deepseek-v4-flash"),
        overrides={"backend": "local"},
        extra_system="你是一个简洁的助手，回答不超过两句。",
    )
    try:
        async for text in runner.run("用一句话解释什么是尾递归。", return_type="text"):
            sys.stdout.write(text)
            sys.stdout.flush()
        print()
    finally:
        await runner.close()


if __name__ == "__main__":
    asyncio.run(main())
