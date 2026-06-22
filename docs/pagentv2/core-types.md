# pagentv2 Core Types

`pagentv2` is built around explicit message objects and a small provider layer.

## Main symbols

| Symbol | Role |
|--------|------|
| `Provider`, `DeepSeek`, `Ollama`, `Vllm`, `Sglang` | OpenAI-compatible streaming clients |
| `Agent(provider, messages=None, system=None, tools=None, max_turns=8)` | Runs the tool loop |
| `Message` | One typed message item with `role` + `content` |
| `Messages` | In-memory message list with `to_openai()` conversion |
| `TextChunk`, `ThinkingChunk`, `ImageUrl`, `AudioUrl` | Content variants |
| `ToolCall` | Assistant tool call chunk |
| `ToolResult` | Tool output message content |
| `TurnResult` | One model turn summary: `content`, `tool_calls`, `reasoning_content` |
| `Event` | Union of the event dataclasses emitted by the run loop |

## Agent constructor

```python
from pagentv2 import Agent, Provider

agent = Agent(
    Provider("gpt-4o-mini"),
    system="You are concise.",
    tools=[],
    max_turns=8,
)
```

Notes:

- `messages` is optional. If omitted, the agent starts with an empty `Messages()`.
- `system=` is inserted as a system `Message` if one is not already present.
- Duplicate tool names are rejected.
- `max_turns` must be `>= 1`.

## Runtime surfaces

| Method | Returns | Notes |
|--------|---------|-------|
| `agent.stream_messages(**run_kwargs)` | `AsyncIterator[Message]` | One provider call only |
| `agent.events(user_input, **run_kwargs)` | `AsyncIterator[Event]` | Full multi-turn loop |
| `agent.arun(user_input, return_type=...)` | projected stream | `event`, `text`, `message`, or `acp` |
| `agent.reset()` | `None` | Keeps system messages, drops later messages |

## `arun()` return types

```python
from pagentv2 import ArunReturnType
```

Valid values:

- `"event"`: raw events
- `"text"`: `TextDelta.text` only
- `"message"`: `Message` projection over the event stream
- `"acp"`: NDJSON JSON-RPC notifications

## Differences from `pagent`

`pagentv2` intentionally shifts the center of gravity:

- no `Session`
- no `LLM`
- typed `Message` objects instead of raw OpenAI-shaped dicts
- `Provider.complete()` owns the low-level request
- `TurnResult` replaces the old `RunEnd` / `StepEnd` shape for the per-turn summary

If you want the older `Session + LLM + arun_events()` API, stay on the main
`pagent` docs. If you want the newer typed message model, use the `pagentv2`
pages.
