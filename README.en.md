# pagent (English)

[![CI](https://github.com/SyncLionPaw/pagent/actions/workflows/ruff.yml/badge.svg)](https://github.com/SyncLionPaw/pagent/actions/workflows/ruff.yml)

Language: [中文](./README.zh-CN.md) | [English](./README.en.md)

Lightweight **async** agent core for OpenAI-compatible Chat Completions.

## Core Features

- `Session`: conversation message buffer (`session += {...}` / `reset()`)
- `LLM`: thin stateless wrapper over `AsyncOpenAI`
- Providers: `DeepSeek`, `Ollama`, `Vllm`, `Sglang`
- `@tool()` / `FunctionTool`: convert Python callables into tool schemas
- `Agent`: multi-turn tool loop until no tool calls or `max_turns` reached
- Built-in tools: `clock`, `region` (locale/timezone hints, not GPS)

## Install

```bash
pip install pagent
```

From source:

```bash
cd pagent
uv sync
pip install -e .
```

## Quick Start

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

## Environment Variables

- `LLM(...)` reads `OPENAI_API_KEY` by default
- `DeepSeek(...)` reads `DEEPSEEK_API_KEY` by default
- Local providers can use `OLLAMA_API_KEY` / `VLLM_API_KEY` / `SGLANG_API_KEY` (dummy key is used when missing)

## DeepSeek

- Docs: [DeepSeek API Docs](https://api-docs.deepseek.com/zh-cn/)
- `base_url`: `https://api.deepseek.com`
- default model: `deepseek-v4-flash`

```python
from pagent import DeepSeek

llm = DeepSeek()  # or DeepSeek("deepseek-v4-pro")
```

Advanced fields can be passed through `request_kwargs` to `chat.completions.create`.

## Local Deployment

If your server exposes OpenAI-compatible `/v1/chat/completions`, it should work directly:

- `Ollama`: `http://127.0.0.1:11434/v1`
- `Vllm`: `http://127.0.0.1:8000/v1`
- `Sglang`: `http://127.0.0.1:30000/v1`

```python
from pagent import Ollama

llm = Ollama("llama3.2")
```

## Maintainer: Publish to PyPI

Included workflow: `.github/workflows/publish.yml` (triggered by GitHub release publish).

Recommended: Trusted Publishing (OIDC).

- Docs: <https://docs.pypi.org/trusted-publishers/>

## Notes

This library assumes OpenAI Chat Completions compatibility. If your backend API shape differs significantly, adapt at the gateway layer or override `LLM.invoke`.
