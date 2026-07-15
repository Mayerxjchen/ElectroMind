"""最简用法：只要 conversation 持久化，不要 sandbox。

ChatRunner 会先打开 thread，再使用 thread 里的 conversation 保存消息。

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.pagentv4.thread_based.conversation_only
"""

import asyncio
import os
import sys

from pagentv4 import AgentCore, ChatRunner, DeepSeek


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请先 export DEEPSEEK_API_KEY=<your-key>")

    agent = AgentCore(
        DeepSeek("deepseek-v4-flash"),
        system="你是一个简洁的助手，回答不超过两句。",
    )
    runner = ChatRunner(agent, thread_id="conversation-demo")

    questions = [
        "请记住一个数：42",
        "那个数乘以 2 是多少？",
    ]

    try:
        for question in questions:
            print(f"\nQ: {question}")
            print("A: ", end="", flush=True)
            async for text in runner.run(question, return_type="text"):
                sys.stdout.write(text)
                sys.stdout.flush()
            print()
    finally:
        # close 会释放 store / sandbox 等资源；thread 数据仍保留在磁盘上。
        await runner.close()

    print(
        "\n对话已保存到 ~/.pagent/threads/conversation-demo/messages.jsonl，"
        f"消息条数：{len(runner.messages.data)}"
    )


if __name__ == "__main__":
    asyncio.run(main())
