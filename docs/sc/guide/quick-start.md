# 赶紧上手（架势搞起）

语言：四川话 | [English](/guide/quick-start) | [普通话](/zh/guide/quick-start) | [日本語](/ja/guide/quick-start)

前置：[安装](./install)（Python 3.11+，pip / uv / conda），装 **归一** 了再往下搞哈。

## 最小例子

给你 **警个醒**：`DEEPSEEK_API_KEY` / `OPENAI_API_KEY` 先搁到位，再跑代码。

```python
import asyncio
import os

from pagent import Agent, DeepSeek, Session, tool


@tool()
def get_weather(city: str) -> str:
    """查城市天气。"""
    return f"{city} 今天晴，巴适得板。"


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("先把 DEEPSEEK_API_KEY 设起噻，莫搞忘咯。")

    agent = Agent(
        llm=DeepSeek("deepseek-v4-flash"),
        session=Session("你是简洁助手，要得时候用工具嘛。"),
        tools=[get_weather],
        max_turns=24,
    )

    result = await agent.run("厦门天气咋个样？")
    print(result.content)


asyncio.run(main())
```

`run()` 返回 **`RunEnd`**，答案用 `.content` 取，晓得不。

## 流式 API

| API | 返回啥子 | 啥时候用 |
|-----|----------|----------|
| `agent.run()` | `RunEnd` | 莫要流式，一次拿完 |
| `agent.arun()` | `str` 片段 | 只要答案打字机效果，安逸 |
| `agent.arun_events()` | `Event` 对象 | Python UI、测试，过程看得清 |
| `agent.arun_wire()` | NDJSON 行 | 浏览器、VS Code 插件 |

跑通了算 **归一** 一步。下一步：[模型跟 API Key](./providers) · [事件流](../events) · [Wire 协议](../wire)

## 示例（要 clone 仓库哈）

按顺序 **过一道**，利索点儿嘛：

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
