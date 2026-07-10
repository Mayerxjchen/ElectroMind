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
src/pagentv4/ithread/    IThread Protocol + ThreadSpec
src/pagentv4/conversation/ ConversationStore, JSONL/SQLite backends
src/pagentv4/runtime/    Runner, VanillaRunner, loop_core, inbound, hooks
src/pagentv4/sandbox/    Backend, Sandbox, file/command tools
src/pagentv4/skills/     SKILL.md discovery and loading
src/pagentv4/adapters/   ACP and other protocol adapters
src/pagentv4/tools/      reusable tool functions
src/app/                 application layer (REPL, CLI) on top of pagentv4
```

Prefer **pagentv4** for new work (`Runner`, sandbox, persistence). See
`docs/pagentv4/` and `examples/pagentv4/`.

**Terminal agent:** `uv run pagent` — same REPL as `examples/app/repl.py`.

## CI before commit / push

**Always run** `./scripts/ci-check.sh` before `git commit` or `git push` to `main`.
It mirrors the GitHub Actions that run on every push:

| Local step | Workflow |
|------------|----------|
| `uv sync --group dev --extra search --frozen` | ruff.yml, coverage.yml |
| `uv run ruff check .` | ruff.yml |
| `uv run ruff format --check .` | ruff.yml |
| `uv run pytest tests/ --cov=src …` | ruff.yml + coverage.yml |
| `cd docs && npm ci && npm run build` | docs.yml |

Do not push until this script exits 0. If docs build regenerates `llms-full.txt`,
include those changes when English docs changed.

Optional git hook (one-time per clone):

```bash
git config core.hooksPath .githooks
chmod +x scripts/ci-check.sh .githooks/pre-push
```

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
