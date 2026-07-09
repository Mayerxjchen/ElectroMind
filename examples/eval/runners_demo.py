"""当前 Runner 用法示例。

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.eval.runners_demo
"""

from __future__ import annotations

import asyncio
import os

from pagentv4 import (
    AgentCore,
    ChatRunner,
    CodeRunner,
    DeepSeek,
    VanillaRunner,
    tool,
)


@tool()
def calc(expression: str) -> str:
    """计算简单算术表达式。"""
    allowed = set("0123456789+-*/(). ")
    if not all(c in allowed for c in expression):
        return "error: 仅支持基础算术"
    return str(eval(expression, {"__builtins__": {}}, {}))


ARTICLE = """
李青云连斩两名魔教护法，又在谷底击退了追兵。
"""


async def collect_text(runner, prompt: str) -> str:
    return "".join([text async for text in runner.run(prompt, return_type="text")])


async def demo_vanilla() -> None:
    runner = VanillaRunner(
        AgentCore(
            DeepSeek("deepseek-v4-flash"),
            system="根据给定文章回答问题，只输出数字。",
        )
    )
    ans = await collect_text(runner, ARTICLE + "\n请问主角总共消灭了几个对手？")
    print("[VanillaRunner]", ans)


async def demo_chat() -> None:
    runner = ChatRunner(
        AgentCore(
            DeepSeek("deepseek-v4-flash"),
            system="你是助手，算题时先用 calc。",
            tools=[calc],
            max_turns=4,
        ),
        thread_id="eval-chat-demo",
    )
    try:
        ans = await collect_text(runner, "123 加 456 等于多少？")
        print("[ChatRunner]", ans)
    finally:
        await runner.close()


async def demo_code() -> None:
    runner = CodeRunner(
        AgentCore(
            DeepSeek("deepseek-v4-flash"),
            system="在 workspace 完成任务，回答简短。",
            max_turns=4,
        ),
        thread_id="eval-code-demo",
        backend="local",
    )
    try:
        ans = await collect_text(runner, "列出 /home/agent 下的文件名，用一句话总结。")
        print("[CodeRunner]", ans)
    finally:
        await runner.close()


async def main() -> None:
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请先 export DEEPSEEK_API_KEY=<your-key>")

    await demo_vanilla()
    await demo_chat()
    await demo_code()


if __name__ == "__main__":
    asyncio.run(main())
