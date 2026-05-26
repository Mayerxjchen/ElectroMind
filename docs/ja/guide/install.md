# インストール

言語: [日本語](/ja/guide/install) | [English](/guide/install) | [简体中文](/zh/guide/install) | [四川话](/sc/guide/install)

**Python 3.11+** が必要です。

## pip

```bash
pip install pagent
pip install "pagent[search]"   # 任意 web_search ツール
```

## uv

[uv](https://docs.astral.sh/uv/) は高速な Python パッケージ／プロジェクトマネージャです（[公式ドキュメント](https://docs.astral.sh/uv/)）。

```bash
uv pip install pagent
uv pip install "pagent[search]"

# uv 管理プロジェクト内
uv add pagent
uv add "pagent[search]"
```

**pagent** リポジトリを clone した場合（開発用）：

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

Conda 環境では PyPI パッケージを **pip** で入れることが多いです。`conda-forge` にパッケージがあるかも確認してください。

## オプション extra

| Extra | インストール | 用途 |
|-------|-------------|------|
| `search` | `pip install "pagent[search]"` | 組み込み `web_search`（`ddgs`） |
| `tokens` | `pip install "pagent[tokens]"` | 一部モデル用 HuggingFace tokenizer |

API Key とバックエンドは [プロバイダと API Key](./providers) を参照。

## 次へ

[クイックスタート](./quick-start) — 最小 Agent とストリーミング API。
