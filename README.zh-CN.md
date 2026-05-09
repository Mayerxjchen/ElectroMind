# pagent（中文）

[![CI](https://github.com/SyncLionPaw/pagent/actions/workflows/ruff.yml/badge.svg)](https://github.com/SyncLionPaw/pagent/actions/workflows/ruff.yml)

语言切换： [中文](./README.zh-CN.md) | [English](./README.en.md)

轻量 **async** agent core（OpenAI-compatible Chat Completions）。

## 核心能力

- `Session`：对话消息缓冲（`session += {...}` / `reset()`）
- `LLM`：对 `AsyncOpenAI` 的薄封装（无状态）
- Providers：`DeepSeek`、`Ollama`、`Vllm`、`Sglang`
- `@tool()` / `FunctionTool`：把 Python 函数转为 tool schema
- `Agent`：多轮工具调用循环，直到无 tool calls 或达到 `max_turns`
- 默认工具：`clock`、`region`（地区线索，非 GPS）

## 安装

```bash
pip install pagent
```

从源码安装：

```bash
cd pagent
uv sync
pip install -e .
```

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
        max_turns=8,
    )

    result = await agent.run("What's the weather in Xiamen?")
    print(result.content)
    print(agent.stats)


asyncio.run(main())
```

## 环境变量

- `LLM(...)` 默认读取 `OPENAI_API_KEY`
- `DeepSeek(...)` 默认读取 `DEEPSEEK_API_KEY`
- 本地 provider 可选：`OLLAMA_API_KEY` / `VLLM_API_KEY` / `SGLANG_API_KEY`（未设置时使用占位 key）

## DeepSeek

- 文档： [DeepSeek API Docs](https://api-docs.deepseek.com/zh-cn/)
- `base_url`: `https://api.deepseek.com`
- 默认模型： `deepseek-v4-flash`

```python
from pagent import DeepSeek

llm = DeepSeek()  # or DeepSeek("deepseek-v4-pro")
```

高级参数可通过 `request_kwargs` 透传给 `chat.completions.create`。

## 本地部署

只要服务提供 OpenAI-compatible `/v1/chat/completions`，即可直接使用：

- `Ollama`: `http://127.0.0.1:11434/v1`
- `Vllm`: `http://127.0.0.1:8000/v1`
- `Sglang`: `http://127.0.0.1:30000/v1`

```python
from pagent import Ollama

llm = Ollama("llama3.2")
```

## 维护者：发布到 PyPI

仓库内置：`.github/workflows/publish.yml`（release 发布触发）。

建议使用 Trusted Publishing（OIDC）：

- Docs: <https://docs.pypi.org/trusted-publishers/>

## 说明

本库假设后端兼容 OpenAI Chat Completions。若 API 形状差异较大，请在网关侧适配或重写 `LLM.invoke`。
