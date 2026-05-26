# Wire protocol (JSON-RPC 2.0)

Language: [简体中文](/wire.zh-CN) | English

For **web / mobile frontends** and any transport that speaks JSON lines (HTTP chunked, SSE `data:` payloads, WebSocket text frames).

This is **not** a second event system. `arun_wire()` serializes the same stream as `arun_events()`; semantics and ordering match [events.md](./events.md).

### When to use Wire vs native Event

| Use **Wire** (`arun_wire`, NDJSON) | Use **native Event** (`arun_events`) |
|-------------------------------------|--------------------------------------|
| TypeScript / Swift / Kotlin client | Python CLI, FastAPI handler, tests |
| SSE or WebSocket to the browser | `match event:` / `isinstance` in-process |
| Persist or replay `wire.jsonl` | Rich objects (e.g. OpenAI `usage` before encode) |

| Use **`arun()`** only when you need printed answer text and nothing else (e.g. simple scripts).

Python backends that talk to a browser often: `arun_events()` in the server loop, `encode_event_line(event)` per chunk to the socket — or `arun_wire()` directly if you only forward lines.

Python events from `Agent.arun_events()` map 1:1 to **JSON-RPC 2.0 notifications** (no `id` — they are pushed, not request/response pairs).

## Message shape

```json
{
  "jsonrpc": "2.0",
  "method": "TextDelta",
  "params": { "text": "Hello" }
}
```

| Field | Value |
|-------|--------|
| `jsonrpc` | Always `"2.0"` |
| `method` | Event class name: `RunBegin`, `TextDelta`, `ToolCallBegin`, `RunEnd`, … |
| `params` | Dataclass fields as a JSON object (see [events.md](./events.md)) |

There is **no** `id` field. Inbound control (approve tool, cancel) is out of scope; use your own API for that.

## NDJSON stream

One notification per line (newline-delimited JSON):

```text
{"jsonrpc":"2.0","method":"RunBegin","params":{"user_input":"Hi"}}
{"jsonrpc":"2.0","method":"TextDelta","params":{"text":"4"}}
{"jsonrpc":"2.0","method":"RunEnd","params":{"content":"4","tool_calls":[],"reasoning_content":"","usage":null}}
```

## Python

```python
from pagent import Agent, LLM, Session, encode_event_line, decode_event_line

async for line in agent.arun_wire("2+2?"):
  # line is already NDJSON (ends with \n)
  send_to_websocket(line)

# Or encode/decode manually:
from pagent import event_to_rpc, rpc_to_event

msg = event_to_rpc(TextDelta("x"))
event = rpc_to_event(msg)
```

Exports: `event_to_rpc`, `rpc_to_event`, `encode_event`, `decode_event`, `encode_event_line`, `decode_event_line`, `JSONRPC_VERSION`.

## TypeScript consumer (sketch)

```typescript
type WireMsg = { jsonrpc: "2.0"; method: string; params: Record<string, unknown> };

function onLine(line: string) {
  const msg: WireMsg = JSON.parse(line);
  switch (msg.method) {
    case "TextDelta":
      appendAnswer(String(msg.params.text ?? ""));
      break;
    case "ReasoningDelta":
      appendThinking(String(msg.params.text ?? ""));
      break;
    case "ToolCallBegin":
      showTool(msg.params.name as string, msg.params.arguments as string);
      break;
    case "RunEnd":
      finish(msg.params.content as string);
      break;
  }
}
```

## `usage` in `StepEnd` / `RunEnd`

When present, `params.usage` is a plain object:

```json
{ "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15 }
```

## Methods reference

Same semantics as [events.md](./events.md); `method` equals the Python event class name.

| `method` | `params` keys |
|----------|----------------|
| `RunBegin` | `user_input` |
| `TurnBegin` | `turn` |
| `TurnEnd` | `turn`, `stopped` |
| `TextDelta` | `text` |
| `ReasoningDelta` | `text` |
| `StepEnd` | `content`, `tool_calls`, `reasoning_content`, `usage` |
| `ToolCallBegin` | `tool_call_id`, `name`, `arguments` |
| `ToolResult` | `tool_call_id`, `name`, `content` |
| `RunEnd` | `content`, `tool_calls`, `reasoning_content`, `usage` |

## Runnable demo

[`examples/wire_demo/`](https://github.com/SyncLionPaw/pagent/tree/main/examples/wire_demo) — FastAPI server + single-page UI. See [Wire demo](./wire-demo) on this site.

## Source

[`src/pagent/wire.py`](https://github.com/SyncLionPaw/pagent/blob/main/src/pagent/wire.py)
