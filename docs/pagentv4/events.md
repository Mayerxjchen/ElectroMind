# pagentv4 Events

语言：[中文](/zh/pagentv4/events) | [English](/pagentv4/events)

`runner.run()` emits the full multi-turn timeline, projected by `return_type`.

## Event types

| Event | Fields | Meaning |
|-------|--------|---------|
| `RunBegin` | `user_input` | A new run starts |
| `RunEnd` | `turn`, `stop_reason` | Final run outcome |
| `TurnBegin` | `turn` | One turn starts; see “What a `turn` means” below |
| `TextDelta` | `text` | Assistant text chunk |
| `ReasoningDelta` | `text` | Assistant reasoning chunk |
| `TurnResult` | `content`, `tool_calls`, `reasoning_content` | Summary of the model output for this turn; not the end marker |
| `ToolCallBegin` | `tool_call_id`, `name`, `arguments` | About to execute one tool |
| `ToolResult` | `tool_call_id`, `name`, `content`, `ok` | Tool output appended |
| `TurnEnd` | `turn`, `stopped`, `stop_reason` | Turn finished; see `StopReason` below |

## What a `turn` means

In `pagentv4`, a `turn` is one internal work cycle the agent performs while handling a single user input.

One turn includes these steps:

- emit `TurnBegin`
- call the model and produce `TextDelta`, `ReasoningDelta`, and possible tool calls
- summarize that model output as `TurnResult`
- if tools were requested, execute them in the same turn and emit `ToolCallBegin` and `ToolResult`
- emit `TurnEnd`

So:

- a `turn` is not the same as one user message
- a `turn` is not the same as one bare model call
- a `turn` is the full unit of “one model generation + tool execution for that round + continue or stop decision”

## `TurnResult` vs `TurnEnd`

These two events are easy to mix up:

- `TurnResult`: summary of the model output for the current turn, used by the runner to decide what happens next
- `TurnEnd`: the turn is actually finished, including tool execution and stop/continue resolution

In other words, a turn may still be running after `TurnResult`. Only `TurnEnd` marks the real end of the turn.

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
  RunEnd(1, stop_reason="no_tool_calls")
```

Without tools:

```text
RunBegin
  TurnBegin(0)
    TextDelta*
    TurnResult(tool_calls=[])
  TurnEnd(0, stopped=True, stop_reason="no_tool_calls")
  RunEnd(0, stop_reason="no_tool_calls")
```

## `StopReason`

| Value | `stopped` | Meaning |
|-------|---------|---------|
| `continuing` | `False` | Tools ran; another model turn will follow |
| `no_tool_calls` | `True` | Model replied without tools; run ends |
| `empty_response` | `True` | Model produced no assistant messages; run ends |
| `max_turns` | `True` | `max_turns` limit reached after tool execution; run ends |
| `cancelled` | `True` | Run cancelled by inbound control |

## Consumers

```python
from pagentv4 import DeepSeek, Runner, TextDelta, ToolCallBegin, ToolResult

runner = await Runner.create("demo", DeepSeek("deepseek-v4-flash"), overrides={"backend": "local"})
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
