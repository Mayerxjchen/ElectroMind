"""v4 return_type 展示 — 同一次调用，四种投影形态。

`runner.run(..., return_type=...)` 支持四种投影：

    "event"    原始事件对象（默认）
    "text"     只保留可见文本，最简的字符串流
    "message"  Message 对象流，能直接塞回 Messages
    "acp"      NDJSON JSON-RPC 通知行，前端拿到就能解码

同样的问题跑四次，看看各自输出什么。

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.v4runner.return_types
"""

import asyncio
import os

from pagentv4 import DeepSeek, Runner

QUESTION = "用一句话解释 asyncio 是什么。"


async def demo(runner: Runner, return_type: str):
    print(f"\n=== return_type={return_type!r} ===")
    async for item in runner.run(QUESTION, return_type=return_type):
        if return_type == "text":
            print(item, end="", flush=True)
        else:
            print(repr(item))
    if return_type == "text":
        print()


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请先 export DEEPSEEK_API_KEY=<your-key>")

    runner = await Runner.open(
        "return-types-demo",
        DeepSeek("deepseek-v4-flash"),
        overrides={"backend": "local"},
        extra_system="回答不超过一句话。",
    )
    try:
        for kind in ("text", "message", "acp", "event"):
            await demo(runner, kind)
    finally:
        await runner.close()


if __name__ == "__main__":
    asyncio.run(main())
