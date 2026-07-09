# Wire browser example

Minimal **server + single-page UI** showing [JSON-RPC wire](../../docs/wire.md)
from pagentv4 events (`VanillaRunner.run(..., return_type="acp")` → NDJSON).

## Run

From repo root:

```bash
export DEEPSEEK_API_KEY="your-key"
uv run --with fastapi --with uvicorn python examples/wire_browser/server.py
```

Open **http://127.0.0.1:8765**

## Stop

**Stop the server** — in the terminal where it is running, press **`Ctrl+C`**.

If port `8765` is still in use:

```bash
lsof -ti :8765 | xargs kill
```

**Stop a streaming reply** — in the browser UI, click **停止** (square button) while the assistant is generating. This aborts the HTTP request; the server stops sending when the connection closes.

Optional env:

| Variable | Default |
|----------|---------|
| `PAGENT_WIRE_HOST` | `127.0.0.1` |
| `PAGENT_WIRE_PORT` | `8765` |

## Layout

| File | Role |
|------|------|
| `server.py` | FastAPI: `GET /` → UI, `POST /api/chat` → `application/x-ndjson` stream |
| `static/index.html` | SPA: `fetch` + line parser, `switch (method)` on wire events |

## API

**POST** `/api/chat`

```json
{ "message": "What is 123 * 456?" }
```

Response: chunked **NDJSON**, one JSON-RPC notification per line, e.g.

```text
{"jsonrpc":"2.0","method":"TextDelta","params":{"text":"59088"}}
{"jsonrpc":"2.0","method":"RunEnd","params":{"content":"59088",...}}
```

See [docs/wire.md](../../docs/wire.md) for all `method` names.
