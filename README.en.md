# pagent (English)

[![CI](https://github.com/SyncLionPaw/pagent/actions/workflows/ruff.yml/badge.svg)](https://github.com/SyncLionPaw/pagent/actions/workflows/ruff.yml)

Language: [中文](./README.zh-CN.md) | [English](./README.en.md)

**pagent** is a small **async** Python library: one `Agent` loop over **OpenAI-compatible Chat Completions** (`messages` + function tools). It is meant for research prototypes and scripts where you want to see the full message list and own the tools—not a productized coding agent or a large framework.

## What we implement

| Area | Behavior |
|------|----------|
| **Conversation** | `Session` holds API-shaped message dicts; append with `session += {...}`; `reset()`; `save_to_file()` |
| **Model call** | `LLM.invoke(messages, tools=...)` — stateless; you build history in `Session` |
| **Providers** | `LLM`, `DeepSeek`, `Ollama`, `Vllm`, `Sglang` (OpenAI SDK + `base_url`) |
| **Tools** | `@tool()` / `FunctionTool` — docstring → JSON schema; `to_openai_tools()` |
| **Agent loop** | User message → model → optional tool calls → tool results in session → repeat until no tools or `max_turns` |
| **Stats** | `AgentStats` — per-run token counts and turn count |
| **Built-in tools** | `clock`, `region` (locale/timezone hints, not GPS); optional `web_search` via extra `search` |
| **Prompt helper** | `JUDGER_SYSTEM` — example system prompt for judge-style tasks |
| **Experimental** | `pagent.memory.Memory` — append-only text lines (not exported from top-level `pagent`) |

Typical flow:

```text
user → [Session] → LLM → assistant (+ tool_calls?) → run tools → tool messages → LLM → … → final text
```

## What we do not implement

These are **out of scope** on purpose; add them in your app or pick another tool:

- **Streaming** — `LLM.invoke` uses `stream=False` only; no token stream API on `Agent.run`
- **Parallel / async tools** — tool calls run sequentially in one turn; no `asyncio.gather` for tools
- **Tool exception shielding** — tool bugs raise through `Agent.run` (only unknown-tool and `web_search` errors return strings)
- **RAG, vector DB, document loaders, chains, planners, LangGraph-style graphs**
- **Built-in file/shell/IDE tools** — no repo edit, terminal, or sandbox
- **MCP, A2A, sub-agents, human-in-the-loop, checkpoints, persistent memory**
- **Multi-modal** — text Chat Completions only
- **Auth, rate limits, observability** — bring your own
- **Non–Chat-Completions APIs** — no native Anthropic Messages / Gemini unless you adapt at the gateway

Backend must speak **OpenAI Chat Completions** (`/v1/chat/completions`). Otherwise override `LLM.invoke` or fix the gateway.

## Comparison

Rough positioning— not a feature scorecard:

| | **pagent** | **LangChain** | **Claude Code** |
|---|------------|---------------|-----------------|
| **What it is** | Tiny embeddable library (~hundreds of lines of core) | Large framework + ecosystem (chains, agents, integrations) | Terminal / IDE **product** for coding with Claude |
| **You write** | Python: `Agent`, `Session`, `@tool()` functions | Python (or JS); LCEL, agents, LangGraph, many abstractions | Prompts + permissions; tools mostly built-in |
| **Model API** | OpenAI Chat Completions (+ compatible servers) | Many providers and wrappers | Anthropic (Claude) via product |
| **Tools** | Your Python callables only | Huge integration catalog + custom tools | File edit, bash, search, MCP, etc. |
| **Agent loop** | One simple loop, fully visible in `agent.py` | Many patterns (ReAct, graphs, supervisors, …) | Opaque product loop tuned for coding |
| **Streaming / RAG / memory** | No / no / experimental `Memory` only | Yes (varies by module) | Product handles context & tools |
| **Best for** | Papers, evals, teaching, minimal control | Production apps needing batteries-included pieces | Daily coding in a repo |
| **Not for** | Production coding agent out of the box | “I only need 80 lines and full transparency” | Embedding as a pip dependency in your library |

**LangChain** — choose when you want integrations (vector stores, loaders, LangGraph workflows) and are fine with framework surface area.

**Claude Code** — choose when you want an agent that already edits files and runs commands in your project; it is not a substitute for `pip install pagent` inside your package.

**pagent** — choose when the agent loop should stay obvious, messages stay JSON-serializable, and you will wire tools and deployment yourself.

## Install

```bash
pip install pagent
```

Optional web search tool (`ddgs`):

```bash
pip install "pagent[search]"
```

From source:

```bash
cd pagent
uv sync --group dev --extra search   # dev + search extra for tests/web_search
pip install -e ".[search]"           # editable install with search
```

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

Optional built-in search (requires `pagent[search]`):

```python
from pagent import Agent, LLM, Session, web_search

agent = Agent(LLM("gpt-4o-mini"), Session("Use web_search when facts are uncertain."), tools=[web_search])
```

## Environment variables

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

## Local deployment

If your server exposes OpenAI-compatible `/v1/chat/completions`, it should work directly:

- `Ollama`: `http://127.0.0.1:11434/v1`
- `Vllm`: `http://127.0.0.1:8000/v1`
- `Sglang`: `http://127.0.0.1:30000/v1`

```python
from pagent import Ollama

llm = Ollama("llama3.2")
```

## Maintainer: publish to PyPI

Included workflow: `.github/workflows/publish.yml` (triggered by GitHub release publish).

Recommended: Trusted Publishing (OIDC).

- Docs: <https://docs.pypi.org/trusted-publishers/>
