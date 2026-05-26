# 快速开始

语言： [中文](/zh/guide/quick-start) | [English](/guide/quick-start) | [日本語](/ja/guide/quick-start) | [四川话](/sc/guide/quick-start)

## 安装

```bash
pip install pagent
pip install "pagent[search]"   # 可选 web_search
```

在 clone 的仓库里用 [uv](https://docs.astral.sh/uv/)：

::: info 不了解 uv 是什么？
请看 [**uv 官方文档**](https://docs.astral.sh/uv/) — 极速 Python 包与项目管理工具（[Astral](https://astral.sh/) / Ruff 团队出品），可替代 pip、poetry 等常见工作流。
:::

```bash
uv sync --group dev --extra search
uv run python -c "import pagent; print(pagent.__version__)"
```

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

uv run examples/cli.py
uv run examples/simple_qa.py
uv run examples/reasoning_stream.py --zh
uv run --with fastapi --with uvicorn python examples/wire_demo/server.py
```

| 脚本 | 说明 |
|------|------|
| [cli.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/cli.py) | 交互 CLI，`/context` |
| [simple_qa.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/simple_qa.py) | 工具调用 |
| [reasoning_stream.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/reasoning_stream.py) | 思考 + 回答流 |
| [wire_demo](https://github.com/SyncLionPaw/pagent/tree/main/examples/wire_demo) | FastAPI + 浏览器 |
