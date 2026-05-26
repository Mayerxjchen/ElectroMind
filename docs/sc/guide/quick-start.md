# 赶紧上手

语言：四川话 | [English](/guide/quick-start) | [普通话](/zh/guide/quick-start) | [日本語](/ja/guide/quick-start)

## 安装

```bash
pip install pagent
pip install "pagent[search]"   # 可选 web_search
```

clone 了仓库用 [uv](https://github.com/astral-sh/uv)：

```bash
uv sync --group dev --extra search
uv run python -c "import pagent; print(pagent.__version__)"
```

## 最小例子

```python
import asyncio
import os

from pagent import Agent, DeepSeek, Session, tool


@tool()
def get_weather(city: str) -> str:
    """查城市天气。"""
    return f"{city} 今天晴，巴适。"


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("先把 DEEPSEEK_API_KEY 设起噻")

    agent = Agent(
        llm=DeepSeek("deepseek-v4-flash"),
        session=Session("你是简洁助手，要得时候用工具。"),
        tools=[get_weather],
        max_turns=8,
    )

    result = await agent.run("厦门天气咋个样？")
    print(result.content)


asyncio.run(main())
```

`run()` 返回 **`RunEnd`**，答案用 `.content` 取。

## 流式 API

| API | 返回啥子 | 啥时候用 |
|-----|----------|----------|
| `agent.run()` | `RunEnd` | 莫要流式 |
| `agent.arun()` | `str` 片段 | 只要答案打字机效果 |
| `agent.arun_events()` | `Event` 对象 | Python UI、测试 |
| `agent.arun_wire()` | NDJSON 行 | 浏览器、VS Code 插件 |

下一步：[模型跟 API Key](./providers) · [事件流](../events) · [Wire 协议](../wire)

## 示例（要 clone 仓库）

```bash
git clone https://github.com/SyncLionPaw/pagent.git
cd pagent
export DEEPSEEK_API_KEY="your-key"

uv run examples/cli.py
uv run examples/simple_qa.py
uv run examples/reasoning_stream.py --zh
uv run --with fastapi --with uvicorn python examples/wire_demo/server.py
```

| 脚本 | 说明 |
|------|------|
| [cli.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/cli.py) | 交互 CLI，`/context` |
| [simple_qa.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/simple_qa.py) | 工具调用 |
| [reasoning_stream.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/reasoning_stream.py) | 脑壳转 + 回答流 |
| [wire_demo](https://github.com/SyncLionPaw/pagent/tree/main/examples/wire_demo) | FastAPI + 浏览器 |
