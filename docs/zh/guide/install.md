# 安装

语言： [中文](/zh/guide/install) | [English](/guide/install) | [日本語](/ja/guide/install) | [四川话](/sc/guide/install)

需要 **Python 3.11+**。

## pip

```bash
pip install pagent
pip install "pagent[search]"   # 可选 web_search 工具
```

## uv

[uv](https://docs.astral.sh/uv/) 是快速的 Python 包与项目管理工具，见 [官方文档](https://docs.astral.sh/uv/)。

```bash
uv pip install pagent
uv pip install "pagent[search]"

# 或在 uv 管理的项目里
uv add pagent
uv add "pagent[search]"
```

在 clone 的 **pagent** 仓库里（参与开发）：

::: info 不了解 uv 是什么？
请看 [**uv 官方文档**](https://docs.astral.sh/uv/) — 极速 Python 包与项目管理工具（[Astral](https://astral.sh/) / Ruff 团队出品）。
:::

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

Conda 环境内通常仍用 **pip** 安装 PyPI 包；也可在 `conda-forge` 查找是否有 conda 包。

## 可选扩展

| Extra | 安装 | 用途 |
|-------|------|------|
| `search` | `pip install "pagent[search]"` | 内置 `web_search`（`ddgs`） |
| `tokens` | `pip install "pagent[tokens]"` | 部分模型的 HuggingFace tokenizer |

API Key 与后端见 [模型与 API Key](./providers)。

## 下一步

[快速开始](./quick-start) — 最小 Agent 与流式 API。
