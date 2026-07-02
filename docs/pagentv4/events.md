# pagentv4 Events

语言：[中文](/zh/pagentv4/events) | [English](/pagentv4/events)

`Runner.events()` emits the full multi-turn timeline. `Runner.arun()`
projects that same stream into one of four return types.

## Event types

| Event | Fields | Meaning |
|-------|--------|---------|
| `RunBegin` | `user_input` | A new run starts |
| `TurnBegin` | `turn` | One provider call starts |
| `TextDelta` | `text` | Assistant text chunk |
| `ReasoningDelta` | `text` | Assistant reasoning chunk |
| `TurnResult` | `content`, `tool_calls`, `reasoning_content` | One model turn finished |
| `ToolCallBegin` | `tool_call_id`, `name`, `arguments` | About to execute one tool |
| `ToolResult` | `tool_call_id`, `name`, `content`, `ok` | Tool output appended |
| `TurnEnd` | `turn`, `stopped`, `stop_reason` | Turn finished; see `StopReason` below |

## Typical sequence

With tools:

```text
RunBegin
  TurnBegin(0)
    TextDelta*
    ReasoningDelta*
    TurnResult(tool_calls=[...])
    ToolCallBegin(...)
    ToolResult(...)
  TurnEnd(0, stopped=False, stop_reason="continuing")
  TurnBegin(1)
    TextDelta*
    TurnResult(tool_calls=[])
  TurnEnd(1, stopped=True, stop_reason="no_tool_calls")
```

Without tools:

```text
RunBegin
  TurnBegin(0)
    TextDelta*
    TurnResult(tool_calls=[])
  TurnEnd(0, stopped=True, stop_reason="no_tool_calls")
```

## `StopReason`

| Value | `stopped` | Meaning |
|-------|---------|---------|
| `continuing` | `False` | Tools ran; another model turn will follow |
| `no_tool_calls` | `True` | Model replied without tools; run ends |
| `empty_response` | `True` | Model produced no assistant messages; run ends |
| `max_turns` | `True` | `max_turns` limit reached after tool execution; run ends |

## Consumers

### Raw event stream

```python
from pagentv4 import Messages, Runner, TextDelta, ToolCallBegin, ToolResult

messages = Messages()
async for event in Runner().events(agent, "Hello", messages):
    if isinstance(event, TextDelta):
        print(event.text, end="")
    elif isinstance(event, ToolCallBegin):
        print(f"\n[tool {event.name}]")
    elif isinstance(event, ToolResult):
        print(f"\n[result {event.ok}: {event.content}]")
```

### `arun(return_type="event")`

```python
async for event in Runner().arun(agent, "Hello", messages, return_type="event"):
    ...
```

## Other `return_type` projections

`Runner.arun()` supports:

- `"event"`: raw event objects
- `"text"`: `TextDelta.text` only
- `"message"`: `Message` objects projected from `TextDelta`, `ReasoningDelta`,
  `ToolCallBegin`, and `ToolResult`
- `"acp"`: NDJSON JSON-RPC notifications via `encode_event_line()`

The event stream is the canonical source of truth in `pagentv4`.
