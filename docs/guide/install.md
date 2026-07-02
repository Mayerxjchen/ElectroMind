# Install

Language: [简体中文](/zh/guide/install) | [日本語](/ja/guide/install) | [四川话](/sc/guide/install) | English

Requires **Python 3.11+**.

## pip

```bash
pip install pagent
pip install "pagent[search]"   # optional web_search tool
```

## uv

[uv](https://docs.astral.sh/uv/) is a fast Python package and project manager ([official docs](https://docs.astral.sh/uv/)).

```bash
uv pip install pagent
uv pip install "pagent[search]"

# or in a uv-managed project
uv add pagent
uv add "pagent[search]"
```

### uvx (terminal REPL, no install)

Run the interactive CLI without adding the package to a project:

```bash
export DEEPSEEK_API_KEY="your-key"
uvx pagent
uvx pagent --thread-id demo
```

From a git checkout or local wheel:

```bash
uvx --from . pagent
uvx --from git+https://github.com/SyncLionPaw/pagent pagent
```

In a cloned **pagent** repo (contributors):

```bash
uv sync --group dev --extra search
uv run python -c "import pagent; print(pagent.__version__)"
```

## conda

```bash
conda activate your-env
pip install pagent
pip install "pagent[search]"
```

Conda envs usually install PyPI packages with **pip** inside the activated environment. Check `conda-forge` if you prefer a conda package when available.

## Optional extras

| Extra | Install | Purpose |
|-------|---------|---------|
| `search` | `pip install "pagent[search]"` | Built-in `web_search` tool (`ddgs`) |
| `tokens` | `pip install "pagent[tokens]"` | HuggingFace tokenizers for some models |

See [Providers & API keys](./providers) for API keys and backends.

## Next

[Quick start](./quick-start) — minimal agent and streaming APIs.
