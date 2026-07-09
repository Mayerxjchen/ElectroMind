"""VanillaRunner 最简 demo：纯内存，无持久化。

适合一次性对话、测试、脚本。对话结束消息就消失。

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.pagentv4.vanilla.basic
"""

import asyncio
import os
import sys

from pagentv4 import AgentCore, DeepSeek, TextDelta, VanillaRunner, tool


@tool()
def get_weather(city: str) -> str:
    """查询城市天气。

    Args:
        city: 城市名，比如 Xiamen / Beijing。
    """
    weathers = {"xiamen": "24°C 多云", "beijing": "12°C 晴", "shanghai": "18°C 小雨"}
    return weathers.get(city.strip().lower(), f"暂无 {city!r} 的天气数据")


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请先 export DEEPSEEK_API_KEY=<your-key>")

    agent = AgentCore(
        DeepSeek("deepseek-v4-flash"),
        system="你是一个简洁的助手。",
        tools=[get_weather],
    )
    runner = VanillaRunner(agent)

    questions = [
        "北京天气怎么样？",
        "那上海呢？",
    ]

    for q in questions:
        print(f"\nQ: {q}")
        print("A: ", end="", flush=True)
        async for event in runner.run(q, return_type="event"):
            if isinstance(event, TextDelta):
                sys.stdout.write(event.text)
                sys.stdout.flush()
        print()

    print(f"\n消息条数：{len(runner.messages.data)}（退出后消息不保留）")


if __name__ == "__main__":
    asyncio.run(main())
