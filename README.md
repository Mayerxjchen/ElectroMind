# pagent

轻量 **async** agent core（OpenAI-compatible Chat Completions）。

Lightweight **async** agent core for OpenAI-compatible Chat Completions.

## 核心能力 | Core Features

- `Session`: 对话消息缓冲（`session += {...}` / `reset()`）  
  `Session`: conversation message buffer (`session += {...}` / `reset()`)
- `LLM`: 对 `AsyncOpenAI` 的薄封装（无状态）  
  `LLM`: thin stateless wrapper over `AsyncOpenAI`
- Providers: `DeepSeek`, `Ollama`, `Vllm`, `Sglang`
- `@tool()` / `FunctionTool`: 函数转工具 schema  
  `@tool()` / `FunctionTool`: convert Python callables into tool schemas
- `Agent`: 多轮工具调用循环，直到无 tool calls 或达到 `max_turns`  
  `Agent`: multi-turn tool loop until no tool calls or `max_turns` reached
- 默认工具：`clock`、`region`（地区线索，非 GPS）  
  Built-in tools: `clock`, `region` (locale/timezone hints, not GPS)

## 安装 | Install

```bash
pip install pagent
```

From source:

```bash
cd pagent
uv sync
pip install -e .
```

## 快速开始 | Quick Start

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

## 环境变量 | Environment Variables

- `LLM(...)` 默认读取 `OPENAI_API_KEY`。
- `DeepSeek(...)` 默认读取 `DEEPSEEK_API_KEY`。
- 本地 provider 可选：`OLLAMA_API_KEY` / `VLLM_API_KEY` / `SGLANG_API_KEY`（未设置时使用占位 key）。

- `LLM(...)` reads `OPENAI_API_KEY` by default.
- `DeepSeek(...)` reads `DEEPSEEK_API_KEY` by default.
- Local providers can use `OLLAMA_API_KEY` / `VLLM_API_KEY` / `SGLANG_API_KEY` (dummy key is used when missing).

## DeepSeek

- 文档 / Docs: [DeepSeek API Docs](https://api-docs.deepseek.com/zh-cn/)
- `base_url`: `https://api.deepseek.com`
- 默认模型 / default model: `deepseek-v4-flash`

```python
from pagent import DeepSeek

llm = DeepSeek()  # or DeepSeek("deepseek-v4-pro")
```

高级参数可通过 `request_kwargs` 透传给 `chat.completions.create`。  
Advanced fields can be passed through `request_kwargs`.

## 本地部署 | Local Deployment

只要服务提供 OpenAI-compatible `/v1/chat/completions`，即可直接使用。  
If your server exposes OpenAI-compatible `/v1/chat/completions`, it should work directly.

- `Ollama`: `http://127.0.0.1:11434/v1`
- `Vllm`: `http://127.0.0.1:8000/v1`
- `Sglang`: `http://127.0.0.1:30000/v1`

```python
from pagent import Ollama

llm = Ollama("llama3.2")
```

## 默认工具 | Built-in Tools

```python
from pagent import DEFAULT_TOOLS

# DEFAULT_TOOLS == [clock, region]
```

- `clock`: ISO time (UTC/local)
- `region`: locale/timezone hints from OS settings (no GPS, no IP geolocation)

## 自定义 Provider | Custom Provider

```python
from pagent import LLM

llm = LLM(
    "your-model-id",
    base_url="https://your-gateway.example.com/v1",
    apikey="your-key",
)
```

## 维护者：发布到 PyPI | Maintainer: Publish to PyPI

仓库内置：`.github/workflows/publish.yml`（release 发布触发）。  
Included workflow: `.github/workflows/publish.yml` (triggered by GitHub release publish).

建议使用 Trusted Publishing（OIDC）：  
Recommended: Trusted Publishing (OIDC).

- Docs: <https://docs.pypi.org/trusted-publishers/>

## 说明 | Notes

本库假设后端兼容 OpenAI Chat Completions。若 API 形状差异较大，请在网关侧适配或重写 `LLM.invoke`。  
This library assumes OpenAI Chat Completions compatibility. If the API shape differs significantly, adapt at the gateway layer or override `LLM.invoke`.
