# 安装

语言：四川话 | [English](/guide/install) | [普通话](/zh/guide/install) | [日本語](/ja/guide/install)

要 **Python 3.11+**，这个莫得商量哈。

## pip

```bash
pip install pagent
pip install "pagent[search]"   # 可选 web_search 工具
```

## uv

[uv](https://docs.astral.sh/uv/) 是快得飞起的 Python 包管理，[官方文档](https://docs.astral.sh/uv/)在这儿。

```bash
uv pip install pagent
uv pip install "pagent[search]"

# 在你自己的 uv 项目里头
uv add pagent
uv add "pagent[search]"
```

clone 了 **pagent** 仓库要改代码的：

::: info 不晓得 uv 是啥子？
到 [**uv 官方文档**](https://docs.astral.sh/uv/) 瞅一眼就晓得咯 — Astral（Ruff 那帮人）整的，装包、管项目都撇脱。
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

conda 环境里头多半还是用 **pip** 装 PyPI 包；要看 conda 包自己上 `conda-forge` 翻。

## 可选扩展

| Extra | 安装 | 干啥子 |
|-------|------|--------|
| `search` | `pip install "pagent[search]"` | 内置 `web_search`（`ddgs`） |
| `tokens` | `pip install "pagent[tokens]"` | 部分模型要 HF tokenizer |

API Key 跟后端看 [模型跟 Key](./providers)。

## 下一步

[架势搞起](./quick-start) — 最小 Agent 跟流式 API。
