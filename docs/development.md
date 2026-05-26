# Developer guide

Language: [中文](./development.zh-CN.md) | English

For contributors and anyone hacking the library. End users should read [README.md](../README.md) only.

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

## Publishing

`.github/workflows/publish.yml` — PyPI via Trusted Publishing on release.

## See also

- [events.md](./events.md)
- [reasoning.md](./reasoning.md)
