# pagentv4 Events

语言：[中文](/zh/pagentv4/events) | [English](/pagentv4/events)

`runner.run()` emits the full multi-turn timeline, projected by `return_type`.

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

```python
from pagentv4 import DeepSeek, Runner, TextDelta, ToolCallBegin, ToolResult

runner = await Runner.open("demo", DeepSeek("deepseek-v4-flash"), overrides={"backend": "local"})
try:
    async for event in runner.run("Hello", return_type="event"):
        if isinstance(event, TextDelta):
            print(event.text, end="")
        elif isinstance(event, ToolCallBegin):
            print(f"\n[tool {event.name}]")
        elif isinstance(event, ToolResult):
            print(f"\n[result {event.ok}: {event.content}]")
finally:
    await runner.close()
```

## Other `return_type` projections

`runner.run()` supports:

- `"event"`: raw event objects
- `"text"`: `TextDelta.text` only
- `"message"`: `Message` objects projected from `TextDelta`, `ReasoningDelta`,
  `ToolCallBegin`, and `ToolResult`
- `"acp"`: NDJSON JSON-RPC notifications via `encode_event_line()`

The event stream is the canonical source of truth in `pagentv4`.
