"""v4 工具调用 — 展示完整事件流。

Runner 会围绕 Agent 派生出一整套事件：
- TextDelta / ReasoningDelta        模型说话增量
- ToolCallBegin / ToolResult        工具调用与结果
- TurnBegin / TurnResult / TurnEnd  轮次调度

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.v4runner.tools
"""

import asyncio
import os
import sys

from pagentv4 import (
    DeepSeek,
    ReasoningDelta,
    Runner,
    TextDelta,
    ToolCallBegin,
    ToolResult,
    TurnBegin,
    TurnEnd,
    tool,
)

WEATHER = {
    "xiamen": "24°C, 多云",
    "beijing": "12°C, 晴",
    "shanghai": "18°C, 小雨",
}

CYAN = "\033[36m"
DIM = "\033[90m"
GREEN = "\033[32m"
RESET = "\033[0m"

QUESTION = (
    "厦门和北京的温差是多少？先分别查天气，再用计算器算差值的绝对值。"
    "最后一句话给出答案。"
)


@tool()
def get_weather(city: str) -> str:
    """查询城市天气。

    Args:
        city: 城市名，比如 Xiamen / Beijing。
    """
    key = city.strip().lower()
    return WEATHER.get(key, f"暂无 {city!r} 的天气数据；可尝试 Xiamen/Beijing/Shanghai")


@tool()
def calc(expression: str) -> str:
    """计算简单算术表达式。

    Args:
        expression: 只允许数字、+ - * / ( )、空格、abs。
    """
    allowed = set("0123456789+-*/(). abs")
    if not all(c in allowed for c in expression):
        return "error: 仅支持基础算术"
    return str(eval(expression, {"__builtins__": {}}, {"abs": abs}))


def use_color() -> bool:
    return sys.stdout.isatty()


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请先 export DEEPSEEK_API_KEY=<your-key>")

    color = use_color()
    runner = await Runner.open(
        "tools-demo",
        DeepSeek("deepseek-v4-flash"),
        overrides={"backend": "local"},
        extra_system="你是一个乐于使用工具的助手；答案要简短。",
        tools=[get_weather, calc],
    )

    print(f"Q: {QUESTION}\n")
    in_reasoning = False

    try:
        async for event in runner.run(QUESTION):
            if isinstance(event, TurnBegin):
                print(
                    f"{DIM if color else ''}── turn {event.turn} 开始 ──{RESET if color else ''}"
                )
                in_reasoning = False

            elif isinstance(event, ReasoningDelta):
                if not in_reasoning:
                    in_reasoning = True
                    if color:
                        sys.stdout.write(DIM)
                    sys.stdout.write("reasoning: ")
                sys.stdout.write(event.text)
                sys.stdout.flush()

            elif isinstance(event, ToolCallBegin):
                if in_reasoning and color:
                    sys.stdout.write(RESET)
                in_reasoning = False
                line = f"tool → {event.name}({event.arguments})"
                print(f"{CYAN}{line}{RESET}" if color else line)

            elif isinstance(event, ToolResult):
                mark = "ok" if event.ok else "fail"
                body = event.content.replace("\n", " ")
                print(
                    f"  {GREEN if color else ''}{mark}: {body}{RESET if color else ''}"
                )

            elif isinstance(event, TextDelta):
                if in_reasoning:
                    if color:
                        sys.stdout.write(RESET)
                    print()
                    in_reasoning = False
                sys.stdout.write(event.text)
                sys.stdout.flush()

            elif isinstance(event, TurnEnd):
                if in_reasoning and color:
                    sys.stdout.write(RESET)
                in_reasoning = False
                reason = f" ({event.stop_reason})" if event.stopped else ""
                print(
                    f"\n{DIM if color else ''}── turn {event.turn} 结束{reason} ──{RESET if color else ''}"
                )

        print(f"\n累计消息条数：{len(runner.messages.data)}")
    finally:
        await runner.close()


if __name__ == "__main__":
    asyncio.run(main())
