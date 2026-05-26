# Wire demo（ローカルブラウザ UI）

言語: 日本語 | [English](/wire-demo) | [简体中文](/zh/wire-demo) | [四川话](/sc/wire-demo)

FastAPI がチャット UI を提供し、ブラウザが **`Agent.arun_wire()`** の `application/x-ndjson` ストリームを消費します。

::: tip GitHub Pages ではデモは動きません
公開サイトは静的ドキュメントのみ。体験するにはローカルでサーバーを起動してください。
:::

## 起動

```bash
git clone https://github.com/SyncLionPaw/pagent.git
cd pagent
export DEEPSEEK_API_KEY="your-key"

uv run --with fastapi --with uvicorn python examples/wire_demo/server.py
```

ブラウザで **http://127.0.0.1:8765**

## 停止

- **サーバー:** ターミナルで `Ctrl+C`
- **生成中:** UI の **停止**（HTTP リクエストを中断）

## 内容

- チャット UI、ツールカード、思考ブロック（任意）
- サイドドロワーで生の Wire NDJSON
- [Wire プロトコル](./wire) と同じメッセージ体系

ソース: [examples/wire_demo/](https://github.com/SyncLionPaw/pagent/tree/main/examples/wire_demo)
