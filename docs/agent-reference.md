# pagent — agent reference

Dense API reference for **coding agents** and LLM tools. Human docs: <https://synclionpaw.github.io/pagent/>.

**Machine indexes:** [llms.txt](/llms.txt) (page list) · [llms-full.txt](/llms-full.txt) (single-file bundle) · repo [AGENTS.md](https://github.com/SyncLionPaw/pagent/blob/main/AGENTS.md)

## What it is

- **Python 3.11+** async library: `Agent` + `Session` + `@tool` functions over **OpenAI-compatible** `POST /v1/chat/completions`.
- **Not included:** file edit, shell, MCP, RAG, parallel tools, checkpoints — you implement those in your app.
- **Package:** `pip install pagent` · optional `pagent[search]`, `pagent[tokens]`.

## Core types

| Symbol | Role |
|--------|------|
| `Session(system_prompt)` | OpenAI-shaped message list; `session += {"role":"user","content":"..."}` |
| `SlidingWindowSession` | Trim by **token** budget (not message count) |
| `CompactingSession` | LLM summarization when context grows |
| `LLM`, `DeepSeek`, `Ollama`, `Vllm`, `Sglang` | Provider clients; model name in constructor |
| `Agent(llm, session, tools=[], max_turns=8)` | Runs the tool loop |
| `RunEnd` | Final model step: `.content`, `.tool_calls`, `.reasoning_content`, `.usage` |
| `@tool()` | Decorator; schema from type hints + docstring |

## Agent.run APIs

| Method | Returns | When |
|--------|---------|------|
| `await agent.run(user_input, **run_kwargs)` | `RunEnd` | Blocking; no stream |
| `agent.arun(user_input, **run_kwargs)` | `AsyncIterator[str]` | Answer text chunks only (`TextDelta`) |
| `agent.arun_events(user_input, **run_kwargs)` | `AsyncIterator[Event]` | Full timeline for Python UI |
| `agent.arun_wire(user_input, **run_kwargs)` | `AsyncIterator[str]` | NDJSON lines (JSON-RPC notifications) |

`run_kwargs` are forwarded to the provider (e.g. `reasoning_effort="medium"` for DeepSeek).

## Event types (`arun_events`)

All are frozen dataclasses; import from `pagent`.

| Event | Fields (summary) | When |
|-------|------------------|------|
| `RunBegin` | `user_input` | Run starts |
| `TurnBegin` | `turn` | One LLM call starts (0-based) |
| `TextDelta` | `text` | Assistant content chunk |
| `ReasoningDelta` | `text` | Reasoning chunk (provider-specific) |
| `StepEnd` | `content`, `tool_calls`, `reasoning_content`, `usage` | One LLM step done |
| `ToolCallBegin` | `tool_call_id`, `name`, `arguments` | Before tool execution |
| `ToolResult` | `tool_call_id`, `name`, `content` | After tool; written to session |
| `TurnEnd` | `turn`, `stopped` | Turn done; `stopped=True` if no more model calls this run |
| `RunEnd` | same as `StepEnd` | Entire run finished |

Typical sequence (tools): `RunBegin` → `TurnBegin` → `TextDelta*` → `StepEnd` → `ToolCallBegin` → `ToolResult` → `TurnEnd(stopped=False)` → next turn → … → `RunEnd`.

## Wire protocol (`arun_wire`)

One **JSON-RPC 2.0 notification** per NDJSON line (no `id`):

```json
{"jsonrpc":"2.0","method":"TextDelta","params":{"text":"hi"}}
```

`method` equals the Python event class name. Same ordering as `arun_events()`.

Python helpers: `encode_event_line`, `decode_event_line`, `event_to_rpc`, `rpc_to_event`.

Inbound control (cancel, tool approval, steer) is **not** in Wire — use your own HTTP/API.

## Minimal example

```python
import asyncio
from pagent import Agent, LLM, Session, tool

@tool()
def get_weather(city: str) -> str:
    """Return weather for the city."""
    return f"Sunny in {city}."

async def main():
    agent = Agent(
        llm=LLM("gpt-4o-mini"),
        session=Session("You are helpful."),
        tools=[get_weather],
        max_turns=8,
    )
    end = await agent.run("Weather in Xiamen?")
    print(end.content)

asyncio.run(main())
```

## Streaming example

```python
from pagent import TextDelta, ToolCallBegin, RunEnd

async for event in agent.arun_events("Hello"):
    match event:
        case TextDelta(text=t):
            print(t, end="", flush=True)
        case ToolCallBegin(name=n):
            print(f"\n[tool {n}]")
        case RunEnd(content=c):
            print(f"\n[done]")
```

## Environment variables

| Provider | Variable |
|----------|----------|
| OpenAI | `OPENAI_API_KEY` |
| DeepSeek | `DEEPSEEK_API_KEY` |
| Ollama | optional `OLLAMA_API_KEY`; default `http://127.0.0.1:11434/v1` |

## Repo map

```text
src/pagent/agent.py      Agent loop
src/pagent/session.py    Session, SlidingWindowSession, CompactingSession
src/pagent/llm.py        LLM providers, RunEnd
src/pagent/tool.py       @tool, FunctionTool
src/pagent/events.py     Event dataclasses
src/pagent/wire.py       JSON-RPC encode/decode
examples/wire_demo/      FastAPI + browser NDJSON consumer
tests/                   pytest
```

## Extended docs (English)

| Topic | Path |
|-------|------|
| Quick start | `docs/guide/quick-start.md` |
| Providers | `docs/guide/providers.md` |
| Tools & session | `docs/guide/tools-session.md` |
| Events (full) | `docs/events.md` |
| Wire (full) | `docs/wire.md` |
| Reasoning streams | `docs/reasoning.md` |
| Development | `docs/development.md` |

Raw URLs: prefix `https://raw.githubusercontent.com/SyncLionPaw/pagent/main/`.
