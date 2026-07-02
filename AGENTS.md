# pagent — instructions for coding agents

You are working with **pagent**, a small async Python library (Agent + Session + tools over OpenAI-compatible Chat Completions). Use the resources below before guessing APIs.

## Read first

1. **[docs/agent-reference.md](docs/agent-reference.md)** — dense cheat sheet (types, `run` / `arun_events` / `arun_wire`, events, Wire shape).
2. **[llms.txt](llms.txt)** — index of doc pages with `raw.githubusercontent.com` URLs (fetch as markdown).
3. **[llms-full.txt](llms-full.txt)** — single-file English bundle (all main guides concatenated).

Human-readable site: <https://synclionpaw.github.io/pagent/>

## How to look up docs

| Goal | Where |
|------|--------|
| API surface, event names, Wire JSON shape | `docs/agent-reference.md` |
| Streaming / UI integration | `docs/events.md`, `docs/wire.md` |
| Minimal working code | `docs/guide/quick-start.md`, `examples/` |
| Reasoning models (DeepSeek) | `docs/reasoning.md` |
| Browser demo | `examples/wire_demo/`, `docs/wire-demo.md` |

Prefer **English** paths under `docs/` for machine consumption. Locales: `docs/zh/`, `docs/ja/`, `docs/sc/`.

## Source layout

```text
src/pagent/              v1 API — Agent.run / arun_events / Session + LLM
src/pagentv4/core/       Agent, Message, Provider, Tool, Event
src/pagentv4/runtime/    Runner, ConversationStore, Thread
src/pagentv4/sandbox/    Backend, Sandbox, file/command tools
src/pagentv4/skills/     SKILL.md discovery and loading
src/app/                 application layer (REPL, CLI) on top of pagentv4
```

Prefer **pagentv4** for new work (`Runner`, sandbox, persistence). See
`docs/pagentv4/` and `examples/v4runner/`.

**Terminal agent:** `uv run pagent` — same REPL as `examples/v4runner/repl.py`.

## Conventions

- `agent.run()` returns **`RunEnd`**; use `.content` for the answer (not `str(run_end)`).
- Wire lines are **NDJSON** JSON-RPC **notifications** (`method` = event class name, no `id`).
- Inbound cancel/steer/tool-approval is **not** part of Wire; implement in your HTTP layer.
- Do not add file/shell/MCP to the core library unless the user explicitly asks for product scope changes.

## Regenerate `llms-full.txt`

```bash
cd docs && npm run build:llms
```

Commit `llms-full.txt` at repo root when English docs change materially.
