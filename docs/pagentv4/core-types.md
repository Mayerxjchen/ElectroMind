# pagentv4 Core Types

语言：[中文](/zh/pagentv4/core-types) | [English](/pagentv4/core-types)

`pagentv4` separates **configuration** (`Agent`), **conversation state**
(`Messages`), **orchestration** (`Runner`), and optional **execution**
(`Sandbox`).

## Main symbols

| Symbol | Role |
|--------|------|
| `Provider`, `DeepSeek`, `Ollama`, `Vllm`, `Sglang`, … | OpenAI-compatible streaming clients |
| `Agent(provider, system=None, tools=None, max_turns=8)` | Model + tool configuration |
| `Runner(store=None)` | Multi-turn loop, persistence, sandbox sessions |
| `run_agent(agent, user_input, …)` | One-shot sugar over `Runner().arun()` |
| `Message` | One typed message item with `role` + `content` |
| `Messages` | In-memory message list with `to_openai()` conversion |
| `ConversationStore`, `JsonlConversationStore`, `SqliteConversationStore` | Persist messages by id |
| `Thread`, `ThreadSpec` | Long-lived thread: spec + messages + workspace |
| `Sandbox` | Companion computer with files and commands |
| `TurnResult` | One model turn summary: `content`, `tool_calls`, `reasoning_content` |
| `Event` | Union of event dataclasses emitted by the run loop |

## Agent

`Agent` is a configuration container. It does **not** own conversation history
or run the tool loop by itself.

```python
from pagentv4 import Agent, DeepSeek, tool


@tool()
def get_weather(city: str) -> str:
    """Return weather for a city."""
    return f"Sunny in {city} today."


agent = Agent(
    DeepSeek("deepseek-v4-flash"),
    system="You are concise.",
    tools=[get_weather],
    max_turns=8,
)
```

Notes:

- `system=` is inserted by `Runner` if no system message is present.
- Duplicate tool names are rejected at construction time.
- `max_turns` must be `>= 1`.
- `agent.stream_messages(messages)` performs one provider call only.

## Runner

`Runner` owns the multi-turn tool loop and optional persistence.

| Method | Role |
|--------|------|
| `runner.arun(agent, user_input, messages, …)` | Full run with `return_type` projection |
| `runner.events(agent, user_input, messages, …)` | Raw event stream |
| `runner.session(provider, user_input, …)` | Create sandbox → bind tools → run → close |
| `runner.load_conversation(id, messages)` | Load from store if messages empty |
| `runner.flush_conversation(id, messages)` | Save to store |

Pass `conversation_id=` to `arun()` / `session()` when `Runner` has a store:

```python
from pagentv4 import JsonlConversationStore, Runner

runner = Runner(store=JsonlConversationStore())
async for event in runner.arun(
    agent, "hi", messages, conversation_id="demo"
):
    ...
```

Messages are flushed at each `TurnEnd`. Default JSONL root:
`<cwd>/.pagent/conversations/`.

## Thread

A **thread** binds conversation history, sandbox spec, and workspace on disk:

```text
<cwd>/.pagent/threads/<thread_id>/
  spec.json
  messages.jsonl
  workspace/
```

Use `Thread.open(thread_id, overrides={...})` to create or resume a thread.
The REPL example (`examples/v4runner/repl.py`) shows the full pattern.

## Provider

```python
from pagentv4 import Provider

provider = Provider(
    "gpt-4o-mini",
    base_url=None,
    apikey=None,
    request_kwargs=None,
)
```

Reserved keys in `Provider.complete()`:

- `model`
- `messages`
- `stream`
- `tools`

| Provider | Environment variable |
|----------|---------------------|
| `Provider` | `OPENAI_API_KEY` |
| `DeepSeek` | `DEEPSEEK_API_KEY` |
| `Ollama` | `OLLAMA_API_KEY` |
| `Vllm` | `VLLM_API_KEY` |
| `Sglang` | `SGLANG_API_KEY` |

## `arun()` return types

Valid `return_type` values:

- `"event"`: raw events
- `"text"`: `TextDelta.text` only
- `"message"`: `Message` projection over the event stream
- `"acp"`: NDJSON JSON-RPC notifications

## Differences from `pagent`

- no `Session`
- no `LLM`
- typed `Message` objects instead of raw OpenAI-shaped dicts
- `Runner` instead of `Agent.arun()` for the full loop
- optional sandbox and conversation persistence

If you want the older `Session + LLM + arun_events()` API, stay on the main
`pagent` docs.
