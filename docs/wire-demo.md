# Wire demo (local browser UI)

Language: [简体中文](/zh/wire-demo) | [日本語](/ja/wire-demo) | [四川话](/sc/wire-demo) | English

Full-stack example: **FastAPI** serves a chat UI; the browser consumes **`Agent.arun_wire()`** as `application/x-ndjson`.

::: tip GitHub Pages cannot host the live demo
The docs site is static only. Run the server locally to try streaming chat.
:::

## Architecture

### Components

```mermaid
flowchart TB
  subgraph browser [Browser — static/index.html]
    UI[Chat UI + Wire drawer]
    PARSE[Line parser<br/>switch method / params]
    UI --> PARSE
  end

  subgraph server [FastAPI — server.py :8765]
    GET["GET / → index.html"]
    POST["POST /api/chat<br/>{ message }"]
    AG[Agent + Session 小帕]
    TOOL["@tool calculate"]
    WIRE[arun_wire]
    GET --> UI
    POST --> AG
    AG --> TOOL
    AG --> WIRE
  end

  subgraph external [External]
    DS[(DeepSeek API<br/>/v1/chat/completions)]
  end

  PARSE <-->|fetch stream<br/>application/x-ndjson| POST
  WIRE -->|NDJSON lines| PARSE
  AG <-->|OpenAI-compatible| DS
```

| Piece | File | Role |
|-------|------|------|
| SPA | `static/index.html` | `fetch("/api/chat")`, read NDJSON lines, render bubbles / tools / reasoning |
| API | `server.py` | `StreamingResponse` from `agent.arun_wire(message)` |
| Library | `pagent` | Agent loop, events → JSON-RPC Wire ([protocol](./wire)) |

Each chat request creates a **new** `Agent` (demo simplicity; a real app would reuse session per user).

### Request flow

```mermaid
sequenceDiagram
  autonumber
  participant User
  participant UI as index.html
  participant API as FastAPI
  participant Agent as Agent.arun_wire
  participant LLM as DeepSeek

  User->>UI: type message, Send
  UI->>API: POST /api/chat { message }
  API->>Agent: arun_wire(message)
  Agent-->>UI: RunBegin (line)
  loop turns / stream
    Agent->>LLM: chat completions
    LLM-->>Agent: deltas
    Agent-->>UI: TextDelta / ReasoningDelta …
    opt tool_calls
      Agent-->>UI: ToolCallBegin
      Note over Agent: calculate()
      Agent-->>UI: ToolResult
    end
    Agent-->>UI: StepEnd, TurnEnd …
  end
  Agent-->>UI: RunEnd (line)
  UI->>User: final bubble + drawer log

  Note over User,UI: Stop → AbortController<br/>aborts fetch (not Wire inbound)
```

### Cancel / stop

```mermaid
flowchart LR
  STOP[UI: Stop] --> ABORT[AbortController.abort]
  ABORT --> HTTP[HTTP connection closed]
  HTTP --> SR[StreamingResponse ends]
  SR --> AGENT[Agent generator stops yielding]
```

Wire has **no** cancel `method` — stopping generation closes the HTTP stream. Tool approval is also out of scope in this demo.

## Run

Examples use `uv run`. New to **uv**? See the [official docs](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/SyncLionPaw/pagent.git
cd pagent
export DEEPSEEK_API_KEY="your-key"

uv run --with fastapi --with uvicorn python examples/wire_demo/server.py
```

Open **http://127.0.0.1:8765**

## Stop

- **Server:** `Ctrl+C` in the terminal
- **While streaming:** click **停止** in the UI (aborts the HTTP request)

## What it shows

- Chat UI with tool cards and optional reasoning block
- Side drawer with raw Wire NDJSON lines
- Same protocol as [Wire protocol](./wire) — not a separate message system

Source: [examples/wire_demo/](https://github.com/SyncLionPaw/pagent/tree/main/examples/wire_demo) on GitHub.
