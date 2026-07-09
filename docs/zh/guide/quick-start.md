# 快速开始

语言： [中文](/zh/guide/quick-start) | [English](/guide/quick-start) | [日本語](/ja/guide/quick-start) | [四川话](/sc/guide/quick-start)

前置：[安装](./install)（Python 3.11+，pip / uv / conda）。

## 最小示例

```python
import asyncio
import os

from pagent import Agent, DeepSeek, Session, tool


@tool()
def get_weather(city: str) -> str:
    """查询城市天气。"""
    return f"{city} 今天晴。"


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请先设置 DEEPSEEK_API_KEY")

    agent = Agent(
        llm=DeepSeek("deepseek-v4-flash"),
        session=Session("你是简洁助手，需要时用工具。"),
        tools=[get_weather],
        max_turns=8,
    )

    result = await agent.run("厦门天气怎么样？")
    print(result.content)


asyncio.run(main())
```

`run()` 返回 **`RunEnd`**，用 `.content` 取回答。

## 流式 API

| API | 返回 | 场景 |
|-----|------|------|
| `agent.run()` | `RunEnd` | 不要流式 |
| `agent.arun()` | `str` 片段 | 只要答案打字机 |
| `agent.arun_events()` | `Event` 对象 | Python UI、测试 |
| `agent.arun_wire()` | NDJSON 行 | 浏览器、VS Code 插件 |

下一步：[模型与 API Key](./providers) · [事件流](/zh/events) · [Wire 协议](/zh/wire)

## 示例（需 clone 仓库）

```bash
git clone https://github.com/SyncLionPaw/pagent.git
cd pagent
export DEEPSEEK_API_KEY="your-key"

uv run pagent
uv run python -m examples.pagentv4.thread_based.conversation_only
uv run python -m examples.pagentv4.thread_based.code_runner
uv run --with fastapi --with uvicorn python examples/wire_browser/server.py
```

| 示例 | 说明 |
|------|------|
| [`examples/README.md`](https://github.com/SyncLionPaw/pagent/blob/main/examples/README.md) | 分类示例索引 |
| [`examples/pagentv4/thread_based`](https://github.com/SyncLionPaw/pagent/tree/main/examples/pagentv4/thread_based) | ChatRunner / CodeRunner 示例 |
| [`examples/pagentv4/runner`](https://github.com/SyncLionPaw/pagent/tree/main/examples/pagentv4/runner) | Runner.create 示例 |
| [wire_browser](https://github.com/SyncLionPaw/pagent/tree/main/examples/wire_browser) | FastAPI + 浏览器 |
