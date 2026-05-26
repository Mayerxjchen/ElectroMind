# 開発者ガイド

言語: 日本語 | [English](/development) | [简体中文](/zh/development) | [四川话](/sc/development)

コントリビューターとライブラリ内部を触る方向け。利用者は [ドキュメントトップ](/ja/) または [クイックスタート](./guide/quick-start) から。

## レイアウト

```text
src/pagent/     ライブラリ
examples/       実行可能サンプル
tests/          pytest
docs/           ドキュメント
```

中核: `agent.py`, `session.py`, `llm.py`, `tool.py`, `tokens.py`, `events.py`

## 機能マップ

| モジュール | 説明 |
|-----------|------|
| `Session` | OpenAI 形式メッセージ; `SlidingWindowSession` はトークンでトリム; `CompactingSession` は LLM 圧縮 |
| `LLM` | `invoke` / `invoke_stream`; 戻り値 `RunEnd` |
| `Agent` | `run` / `arun` / `arun_events` / `arun_wire` |
| `tokens` | `count_tokens`, `count_tokens_detail`, `format_context` |
| `events` / `wire` | UI タイムライン — [イベント](./events), [Wire](./wire) |

## スコープ外

並列ツール、RAG、MCP、組み込みファイル/シェル、マルチモーダル、チェックポイント — アプリ側で実装。

## ローカル開発

```bash
uv sync --group dev --extra search
pip install -e ".[search]"
pre-commit install
pytest -q
```

## ドキュメントサイト

[VitePress](https://vitepress.dev/)。設定: `docs/.vitepress/config.mts`

```bash
cd docs && npm install && npm run dev
```

`main` への push で [docs.yml](https://github.com/SyncLionPaw/pagent/blob/main/.github/workflows/docs.yml) が `gh-pages` にデプロイ。

## 関連

- [イベント](./events)
- [推論](./reasoning)
