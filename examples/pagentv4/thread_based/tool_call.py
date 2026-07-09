"""带工具调用的 ChatRunner，展示完整事件流。

用自定义工具查询天气和做算术，ChatRunner 负责：
- 事件流（TextDelta / ToolCallBegin / ToolResult / TurnBegin / TurnEnd）
- conversation 持久化（每次 run 结束自动 flush）

`@tool()` 会把函数名、类型注解和 docstring 转成 LLM tool schema：
参数名会成为 JSON schema property，类型注解决定 JSON type，docstring 会作为
tool description。函数返回值会作为 tool result 文本写回模型上下文。

Usage:
    export DEEPSEEK_API_KEY="your-key-here"
    uv run python -m examples.pagentv4.thread_based.tool_call
"""

import asyncio
import os
import sys

from pagentv4 import (
    AgentCore,
    ChatRunner,
    DeepSeek,
    ReasoningDelta,
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
    return WEATHER.get(key, f"暂无 {city!r} 的天气数据")


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
    agent = AgentCore(
        DeepSeek("deepseek-v4-flash"),
        system="你是一个乐于使用工具的助手；答案要简短。",
        tools=[get_weather, calc],
    )
    runner = ChatRunner(agent, thread_id="tool-call-demo")

    print(f"Q: {QUESTION}\n")
    in_reasoning = False

    try:
        # 不传 return_type 时默认返回 event 流，适合展示推理、工具调用和 turn 边界。
        async for event in runner.run(QUESTION):
            if isinstance(event, TurnBegin):
                print(
                    f"{DIM if color else ''}── turn {event.turn} ──{RESET if color else ''}"
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
        # close 会释放 store / sandbox 等资源；thread 数据仍保留在磁盘上。
        await runner.close()


if __name__ == "__main__":
    asyncio.run(main())
