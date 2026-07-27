<p align="center">
  <img src="docs/public/logo.png" alt="pagent" width="420" />
</p>

# pagent（中文）

[![CI](https://github.com/SyncLionPaw/pagent/actions/workflows/ruff.yml/badge.svg)](https://github.com/SyncLionPaw/pagent/actions/workflows/ruff.yml)
[![Coverage](https://codecov.io/gh/SyncLionPaw/pagent/graph/badge.svg)](https://app.codecov.io/gh/SyncLionPaw/pagent)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

语言： [中文](./README.zh-CN.md) | [English](./README.en.md) · [文档站](https://synclionpaw.github.io/pagent/) · [给 Agent 看](./AGENTS.md) · [llms.txt](./llms.txt)

**pagent** 是一个轻量的 **async** Python 库：用 OpenAI 兼容的 Chat Completions API 跑 **Agent + 工具** 循环。适合脚本、实验和教学——消息列表透明、工具自己写。

## 文档

**https://synclionpaw.github.io/pagent/** — 安装、快速开始、工具、事件流、Wire、各厂商 API。

## 安装

需要 **Python 3.11+**。

### pip

```bash
pip install pagent

# 可选：内置 web_search 工具
pip install "pagent[search]"
```

### uv

[uv](https://docs.astral.sh/uv/) 是极速 Python 包与项目管理工具，不了解请看 [官方文档](https://docs.astral.sh/uv/)。

```bash
uv pip install pagent
uv pip install "pagent[search]"

# 或在已有 uv 项目中
uv add pagent
uv add "pagent[search]"
```

### conda

```bash
# 先进入你的环境
conda activate your-env

pip install pagent
pip install "pagent[search]"
```

Conda 生态里通常用 **pip 安装 PyPI 包**（在激活的环境中执行即可）。若使用 `conda-forge`，以频道里是否提供 `pagent` 为准。

## 快速开始

```python
import asyncio
import os

from pagent import Agent, LLM, Session, tool


@tool()
def get_weather(city: str) -> str:
    """Return a fake weather summary for the city."""
    return f"It's sunny in {city} today."


async def main() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("Please set OPENAI_API_KEY first.")

    agent = Agent(
        llm=LLM("gpt-4o-mini"),
        session=Session("You are a concise assistant. Use tools when needed."),
        tools=[get_weather],
        max_turns=24,
    )

    result = await agent.run("What's the weather in Xiamen?")
    print(result.content)
    print(agent.stats)


asyncio.run(main())
```

`run()` 返回 `RunEnd`，用 `.content` 取回答。

## 流式输出与事件

**同一套 Agent 时间线**，按场景选 API（不是两套事件定义）：

| API | 得到什么 | 适合 |
|-----|----------|------|
| `agent.run(prompt)` | 最终 `RunEnd` | 不要流式、只要结果 |
| `agent.arun(prompt)` | 答案文本 `str` | 脚本里只要打字机效果 |
| `agent.arun_events(prompt)` | Python **`Event`** dataclass | **Python 内**消费：CLI、服务、`match` / 类型检查 |
| `agent.arun_wire(prompt)` | **NDJSON** 行（JSON-RPC 2.0） | **跨语言 / 前端**：SSE、WebSocket、TS 按 `method` 分支 |

Wire 是 Event 的 JSON 序列化；字段含义见 [docs/events.zh-CN.md](docs/events.zh-CN.md)，线格式见 [docs/wire.zh-CN.md](docs/wire.zh-CN.md)。

消费事件流的最小示例（可接自己的 UI 或日志）：

```python
import asyncio

from pagent import (
    Agent,
    LLM,
    RunEnd,
    Session,
    TextDelta,
    ToolCallBegin,
    ToolResult,
)


async def main():
    agent = Agent(LLM("gpt-4o-mini"), Session("You are helpful."), tools=[])

    async for event in agent.arun_events("2 + 3 等于多少？"):
        if isinstance(event, TextDelta):
            print(event.text, end="", flush=True)
        elif isinstance(event, ToolCallBegin):
            print(f"\n[调用工具 {event.name}]", flush=True)
        elif isinstance(event, ToolResult):
            print(f" {event.content}", flush=True)
        elif isinstance(event, RunEnd):
            print(f"\n\n(结束: {event.content!r})")


asyncio.run(main())
```

常见事件：`TextDelta`（回答流）、`ReasoningDelta`（思考流，视模型而定）、`ToolCallBegin` / `ToolResult`、`RunEnd`（完整结果，含 `.content`、`.reasoning_content`）。

事件一览：[docs/events.zh-CN.md](docs/events.zh-CN.md)。**前端 / JSON：** [docs/wire.zh-CN.md](docs/wire.zh-CN.md) — 每行形如 `{"jsonrpc":"2.0","method":"TextDelta","params":{...}}`。

```python
async for line in agent.arun_wire("你好"):
    # 经 SSE / WebSocket 发送 line（已带末尾 \n）
    ...
```

可运行示例：`examples/reasoning_stream.py`、`examples/cli.py`（内部用 `arun` 打文本）。

## 模型与 API Key

| 用法 | 环境变量 |
|------|----------|
| `LLM("gpt-4o-mini")` | `OPENAI_API_KEY` |
| `DeepSeek()` | `DEEPSEEK_API_KEY` |
| `Ollama("llama3.2")` 等本地服务 | 可选 `OLLAMA_API_KEY` 等 |

```python
from pagent import DeepSeek, Ollama

llm = DeepSeek("deepseek-v4-flash")   # 默认模型见 DeepSeek 文档
llm = Ollama("llama3.2")             # http://127.0.0.1:11434/v1
```

本地服务需暴露 OpenAI 兼容的 `/v1/chat/completions`。也支持 `Vllm`、`Sglang`。

## 示例

| 命令 | 说明 |
|------|------|
| `uv run examples/cli.py` | 交互式 CLI（需 `DEEPSEEK_API_KEY`），支持 `/context` 看上下文占用 |
| `uv run examples/simple_qa.py` | 工具调用 |
| `uv run examples/reasoning_run.py` | 读取模型的思考过程（非流式） |
| `uv run examples/reasoning_stream.py` | 流式输出思考 + 回答 |
| `uv run --with fastapi --with uvicorn python examples/wire_demo/server.py` | Wire NDJSON + 浏览器单页 UI |

思考过程（`reasoning_content`）说明：[docs/reasoning.zh-CN.md](docs/reasoning.zh-CN.md)。Wire 全栈 demo：[examples/wire_demo/](examples/wire_demo/)。

```bash
export DEEPSEEK_API_KEY="your-key"
uv run examples/reasoning_stream.py --zh   # 中文鸡兔同笼题
```

## 内置工具（可选）

```python
from pagent import Agent, LLM, Session, web_search

agent = Agent(
    LLM("gpt-4o-mini"),
    Session("事实不确定时用 web_search。"),
    tools=[web_search],  # 需 pip install "pagent[search]"
)
```

还有 `clock`、`region` 等，见 `pagent.defaults`。

## 说明

- 需要 **OpenAI Chat Completions** 兼容接口。
- 适合嵌入自己的小循环；不是带文件编辑/终端的完整编程 Agent 产品。
- 参与开发、内部实现：[docs/development.zh-CN.md](docs/development.zh-CN.md)

## 许可证

[MIT](./LICENSE)
