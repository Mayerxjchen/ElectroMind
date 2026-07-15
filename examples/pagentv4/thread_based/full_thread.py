"""完整 thread 生命周期：thread 目录 + sandbox + 会话持久化。

用 Runner.create() 打开一个 thread，自动创建：
- ~/.pagent/threads/<thread_id>/thread.toml  配置
- ~/.pagent/threads/<thread_id>/workspace/   沙箱工作目录
- 会话文件                                  对话历史

Runner.create() 会把 sandbox 描述、skills 提示和用户 system 拼成最终 system
prompt。thread.toml 里的 [agent].system 优先；没有配置时使用 extra_system。

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.pagentv4.thread_based.full_thread
"""

import asyncio
import os
import sys
from datetime import datetime

from pagentv4 import DeepSeek, Runner, TextDelta


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请先 export DEEPSEEK_API_KEY=<your-key>")

    thread_id = f"demo-{datetime.now():%Y%m%d-%H%M%S}"

    runner = await Runner.create(
        thread_id,
        DeepSeek("deepseek-v4-flash"),
        overrides={"backend": "local"},
        # 这里给用户自定义 system；thread.toml 里配置了 [agent].system 时会优先用配置。
        extra_system="你是一个简洁的助手，回答不超过两句。",
    )

    print(f"thread 目录: {runner.thread.root}")
    print(f"workspace:   {runner.thread.workspace_path}")
    print(f"spec:        {runner.thread.spec_path}")
    print()

    try:
        print("Q: 列出当前工作目录的文件")
        print("A: ", end="", flush=True)
        async for event in runner.run("列出当前工作目录的文件", return_type="event"):
            if isinstance(event, TextDelta):
                sys.stdout.write(event.text)
                sys.stdout.flush()
        print()

        print("\nQ: 在工作目录创建一个 hello.txt 并写入内容")
        print("A: ", end="", flush=True)
        async for event in runner.run(
            "在工作目录创建一个 hello.txt，写入 'Hello from Runner!'",
            return_type="event",
        ):
            if isinstance(event, TextDelta):
                sys.stdout.write(event.text)
                sys.stdout.flush()
        print()

        print(f"\n累计消息条数：{len(runner.messages.data)}")
    finally:
        # close 会关闭 sandbox；thread 目录、workspace 和 messages 会保留。
        await runner.close()
        print("runner 已关闭，thread 数据保留在磁盘上。")


if __name__ == "__main__":
    asyncio.run(main())
