# Developer guide

Language: [中文](./development.zh-CN.md) | English

For contributors and anyone hacking the library. End users should read the [documentation site](https://synclionpaw.github.io/pagent/) or [README.md](../README.md).

## Layout

```text
src/pagent/     library
examples/       runnable demos
tests/          pytest
docs/           documentation
```

Core: `agent.py`, `session.py`, `llm.py`, `tool.py`, `tokens.py`, `events.py`.

## Capability map

See [development.zh-CN.md](./development.zh-CN.md) for the full table (Chinese). Highlights:

- `Session`, `SlidingWindowSession`, `CompactingSession`
- `Agent.run` / `arun` / `arun_events`
- Token helpers and CLI `format_context`
- Events: [events.md](./events.md)

## Out of scope

Parallel tools, RAG, MCP, built-in file/shell tools, multimodal, checkpoints — build in your app.

## Local development

```bash
uv sync --group dev --extra search
pip install -e ".[search]"
pre-commit install
pytest -q
```

## Documentation site

Built with [VitePress](https://vitepress.dev/). Config: `docs/.vitepress/config.mts`, content: `docs/*.md`.

```bash
cd docs
npm install
npm run dev            # http://localhost:5173/pagent/
npm run build          # output in docs/.vitepress/dist/
```

Node tooling lives under `docs/` (`package.json`, `package-lock.json`) so the repo root stays Python-only.

Do **not** commit `docs/.vitepress/dist/` or `site/` — they are in `.gitignore`. Only Markdown sources under `docs/` live on `main`.

On push to `main`, [.github/workflows/docs.yml](../.github/workflows/docs.yml) runs `npm run build` in `docs/` and publishes `docs/.vitepress/dist/` to the **`gh-pages`** branch. Enable in repo **Settings → Pages → Deploy from branch → gh-pages / root**.

## Publishing

`.github/workflows/publish.yml` — PyPI via Trusted Publishing on release.

## See also

- [events.md](./events.md)
- [reasoning.md](./reasoning.md)
