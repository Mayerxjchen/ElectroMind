"""CodeRunner demo —— 带 sandbox 的对话。

CodeRunner 自动注入 sandbox tools（读文件、写文件、执行命令），
agent 可以直接操作本地文件系统。

CodeRunner 可以直接构造；第一次 run 前会自动打开 sandbox。
`backend` 可选 local / docker / podman / ssh；这里用 local，workspace 在
`~/.pagent/threads/code-demo/workspace/`。

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.pagentv4.thread_based.code_runner
"""

import asyncio
import os
import sys

from pagentv4 import AgentCore, CodeRunner, DeepSeek


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请先 export DEEPSEEK_API_KEY=<your-key>")

    agent = AgentCore(
        DeepSeek("deepseek-v4-flash"),
        system="你是一个代码助手，能读写文件和执行命令。回答简短。",
    )
    runner = CodeRunner(
        agent,
        backend="local",
        thread_id="code-demo",
    )

    print(f"thread_id: {runner.thread.id}")
    print(f"messages: {runner.thread.messages_storage_path}")
    print(f"workspace: {runner.thread.workspace_path}")
    print()

    questions = [
        "列出当前目录的文件",
        "创建一个 hello.py，写入一个打印 hello world 的函数，然后执行它",
    ]

    try:
        for q in questions:
            print(f"Q: {q}")
            print("A: ", end="", flush=True)
            async for text in runner.run(q, return_type="text"):
                sys.stdout.write(text)
                sys.stdout.flush()
            print("\n")
    finally:
        # close 会关闭 sandbox；thread 目录、workspace 和 messages 会保留。
        await runner.close()

    print(f"消息条数：{len(runner.messages.data)}，conversation 已持久化。")


if __name__ == "__main__":
    asyncio.run(main())
