# Developer guide

Language: [简体中文](/zh/development) | [日本語](/ja/development) | [四川话](/sc/development) | English

For contributors and anyone hacking the library. End users should start at the [documentation home](/) or [Quick start](./guide/quick-start).

## Layout

```text
src/pagent/     v1 library
src/pagentv4/   v4 library (core, runtime, sandbox, skills)
src/app/        application layer (REPL, CLI) on top of pagentv4
examples/       runnable demos grouped by category (see examples/pagentv4/)
tests/          pytest
docs/           documentation
```

Core: `agent.py`, `session.py`, `llm.py`, `tool.py`, `tokens.py`, `events.py`.

## Capability map

| Module | Notes |
|--------|--------|
| `Session` | OpenAI-shaped messages; `SlidingWindowSession` trims by tokens; `CompactingSession` LLM-compresses history |
| `LLM` | `invoke` / `invoke_stream`; returns `RunEnd` |
| `Agent` | `run` / `arun` / `arun_events` / `arun_wire` |
| `tokens` | `count_tokens`, `count_tokens_detail`, `format_context` |
| `events` / `wire` | UI timeline — [events.md](./events.md), [wire.md](./wire.md) |

中文完整表：[开发指南](/zh/development)

## Out of scope

Parallel tools, RAG, MCP, built-in file/shell tools, multimodal, checkpoints — build in your app.

**Planned:** [Hooks support plan](./plans/hooks.md) (lifecycle hooks for tool approval, cancel, context injection; distinct from Event/Wire).

## Local development

Uses [uv](https://docs.astral.sh/uv/) for env management. New to uv? See the [official docs](https://docs.astral.sh/uv/).

```bash
uv sync --group dev --extra search
pip install -e ".[search]"
pre-commit install
pytest -q
```

## Documentation site

Built with [VitePress](https://vitepress.dev/). Config: `docs/.vitepress/config.mts`, content: `docs/*.md`. Mermaid diagrams use [vitepress-plugin-mermaid](https://github.com/emersonbottero/vitepress-plugin-mermaid) (fenced ` ```mermaid ` blocks).

**For coding agents / LLMs:** [agent-reference](./agent-reference), repo [AGENTS.md](https://github.com/SyncLionPaw/pagent/blob/main/AGENTS.md), [llms.txt](https://github.com/SyncLionPaw/pagent/blob/main/llms.txt), [llms-full.txt](https://github.com/SyncLionPaw/pagent/blob/main/llms-full.txt) (`npm run build:llms` in `docs/` regenerates the bundle).

```bash
cd docs
npm install
npm run dev            # http://localhost:5173/pagent/
npm run build          # output in docs/.vitepress/dist/
```

Node tooling lives under `docs/` (`package.json`, `package-lock.json`) so the repo root stays Python-only.

Do **not** commit `docs/.vitepress/dist/` or `site/` — they are in `.gitignore`. Only Markdown sources under `docs/` live on `main`.

On push to `main`, [docs.yml](https://github.com/SyncLionPaw/pagent/blob/main/.github/workflows/docs.yml) runs `npm run build` in `docs/` and publishes `docs/.vitepress/dist/` to the **`gh-pages`** branch. Enable in repo **Settings → Pages → Deploy from branch → gh-pages / root**.

## Publishing

Release notes live in **[`CHANGELOG.md`](../CHANGELOG.md)** at the repo root (one file, newest version first). Before tagging, write under `## Unreleased`, then rename that section to `## x.y.z — date`.

```bash
./scripts/release-notes.sh 0.7.8 | gh release create v0.7.8 --title v0.7.8 --notes-file -
```

`.github/workflows/publish.yml` — on **published** GitHub Release: uploads VS Code `.vsix`, builds Desktop macOS zip, publishes wheel to PyPI (Trusted Publishing).

## See also

- [events.md](./events.md)
- [reasoning.md](./reasoning.md)
