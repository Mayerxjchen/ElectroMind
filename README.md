<p align="center">
  <img src="docs/public/logo.png" alt="pagent" width="420" />
</p>

# pagent (English)

[![CI](https://github.com/SyncLionPaw/pagent/actions/workflows/ruff.yml/badge.svg)](https://github.com/SyncLionPaw/pagent/actions/workflows/ruff.yml)
[![Coverage](https://codecov.io/gh/SyncLionPaw/pagent/graph/badge.svg)](https://app.codecov.io/gh/SyncLionPaw/pagent)

Language: [中文](./README.zh-CN.md) | [English](./README.en.md) · [Docs](https://synclionpaw.github.io/pagent/) · [For agents](./AGENTS.md) · [llms.txt](./llms.txt)

**pagent** is a small **async** Python library for an **Agent + tools** loop over **OpenAI-compatible Chat Completions**. Good for scripts, experiments, and teaching—transparent message history, your own tools.

## Documentation

**https://synclionpaw.github.io/pagent/** — install, quick start, tools, events, Wire, providers.

## Install

Requires **Python 3.11+**.

### pip

```bash
pip install pagent
pip install "pagent[search]"   # optional web_search tool
```

### uv

[uv](https://docs.astral.sh/uv/) is a fast Python package and project manager ([official docs](https://docs.astral.sh/uv/)).

```bash
uv pip install pagent
uv pip install "pagent[search]"

# or in a uv-managed project
uv add pagent
uv add "pagent[search]"
```

### uvx (terminal REPL)

```bash
export DEEPSEEK_API_KEY="your-key"
uvx pagent
uvx pagent --thread-id demo
```

### conda

```bash
conda activate your-env
pip install pagent
pip install "pagent[search]"
```

Conda envs usually install PyPI packages with **pip** inside the activated environment. Check `conda-forge` if you prefer a conda package when available.

## Quick start

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

`run()` returns `RunEnd`; use `.content` for the answer.

## Streaming & events

**One agent timeline** — pick an API by consumer (not two different event systems):

| API | You get | Best for |
|-----|---------|----------|
| `agent.run(prompt)` | Final `RunEnd` | No streaming |
| `agent.arun(prompt)` | Answer text `str` | Simple typing effect in scripts |
| `agent.arun_events(prompt)` | Python **`Event`** dataclasses | **In-process Python**: CLI, services, `match` / types |
| `agent.arun_wire(prompt)` | **NDJSON** lines (JSON-RPC 2.0) | **Cross-language / frontend**: SSE, WebSocket, TS `switch (method)` |

Wire serializes the same events as native `Event`; see [docs/events.md](docs/events.md) and [docs/wire.md](docs/wire.md).

Minimal event consumer (build your own UI or logs):

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

    async for event in agent.arun_events("What is 2 + 2?"):
        if isinstance(event, TextDelta):
            print(event.text, end="", flush=True)
        elif isinstance(event, ToolCallBegin):
            print(f"\n[calling {event.name}]", flush=True)
        elif isinstance(event, ToolResult):
            print(f" {event.content}", flush=True)
        elif isinstance(event, RunEnd):
            print(f"\n\n(done, {event.content!r})")


asyncio.run(main())
```

Common events: `TextDelta` (answer stream), `ReasoningDelta` (model thinking, if supported), `ToolCallBegin` / `ToolResult`, `RunEnd` (final result with `.content` and `.reasoning_content`).

Full list: [docs/events.md](docs/events.md). **Frontend / JSON:** [docs/wire.md](docs/wire.md) — each line is `{"jsonrpc":"2.0","method":"TextDelta","params":{...}}`.

```python
async for line in agent.arun_wire("Hello"):
    # send `line` over SSE / WebSocket (already ends with \n)
    ...
```

Runnable demos are grouped under `examples/`; start with `examples/README.md`.

## Models & API keys

| Class | Env var |
|-------|---------|
| `LLM("gpt-4o-mini")` | `OPENAI_API_KEY` |
| `DeepSeek()` | `DEEPSEEK_API_KEY` |
| `Ollama(...)`, `Vllm`, `Sglang` | optional provider keys |

```python
from pagent import DeepSeek, Ollama

llm = DeepSeek("deepseek-v4-flash")
llm = Ollama("llama3.2")
```

Server must expose OpenAI-compatible `/v1/chat/completions`.

## Examples

| Command | Description |
|---------|-------------|
| `uv run pagent` | Interactive pagentv4 terminal app |
| `uv run python -m examples.pagentv4.thread_based.conversation_only` | Thread-based conversation persistence |
| `uv run python -m examples.pagentv4.thread_based.code_runner` | CodeRunner with sandbox tools |
| `uv run python -m examples.pagentv4.runner.return_types` | `text` / `message` / `acp` / `event` projections |
| `uv run --with fastapi --with uvicorn python examples/wire_browser/server.py` | Wire NDJSON + browser UI |

Guide: [docs/reasoning.md](docs/reasoning.md). Full-stack wire demo: [examples/wire_browser/](examples/wire_browser/).

```bash
export DEEPSEEK_API_KEY="your-key"
uv run python -m examples.pagentv4.thread_based.conversation_only
```

## Optional built-in tools

```python
from pagent import Agent, LLM, Session, web_search

agent = Agent(LLM("gpt-4o-mini"), Session("..."), tools=[web_search])
```

See `clock`, `region` in `pagent.defaults`.

## Notes

- Requires an **OpenAI Chat Completions**–compatible API.
- A minimal embeddable loop—not a full coding-agent product with file edit/shell.
- Development & internals: [docs/development.md](docs/development.md)
