# Wire demo（ローカルブラウザ UI）

言語: 日本語 | [English](/wire-demo) | [简体中文](/zh/wire-demo) | [四川话](/sc/wire-demo)

FastAPI がチャット UI を提供し、ブラウザが **`Agent.arun_wire()`** の `application/x-ndjson` ストリームを消費します。

::: tip GitHub Pages ではデモは動きません
公開サイトは静的ドキュメントのみ。体験するにはローカルでサーバーを起動してください。
:::

## アーキテクチャ

### コンポーネント

```mermaid
flowchart TB
  subgraph browser [ブラウザ — static/index.html]
    UI[チャット UI + Wire ドロワー]
    PARSE[行パーサ<br/>switch method / params]
    UI --> PARSE
  end

  subgraph server [FastAPI — server.py :8765]
    GET["GET / → index.html"]
    POST["POST /api/chat<br/>{ message }"]
    AG[Agent + Session 小帕]
    TOOL["@tool calculate"]
    WIRE[arun_wire]
    GET --> UI
    POST --> AG
    AG --> TOOL
    AG --> WIRE
  end

  subgraph external [外部]
    DS[(DeepSeek API<br/>/v1/chat/completions)]
  end

  PARSE <-->|fetch ストリーム<br/>application/x-ndjson| POST
  WIRE -->|NDJSON 行| PARSE
  AG <-->|OpenAI 互換| DS
```

| 部分 | ファイル | 役割 |
|------|----------|------|
| SPA | `static/index.html` | `fetch("/api/chat")`、NDJSON 行を描画 |
| API | `server.py` | `agent.arun_wire(message)` の `StreamingResponse` |
| ライブラリ | `pagent` | Agent ループ、Wire シリアライズ（[プロトコル](./wire)） |

リクエストごとに **新しい** `Agent`（デモ用の簡略化。本番はユーザーごとに session を再利用）。

### リクエストの流れ

```mermaid
sequenceDiagram
  autonumber
  participant User as ユーザー
  participant UI as index.html
  participant API as FastAPI
  participant Agent as Agent.arun_wire
  participant LLM as DeepSeek

  User->>UI: 送信
  UI->>API: POST /api/chat { message }
  API->>Agent: arun_wire(message)
  Agent-->>UI: RunBegin
  loop ターン / ストリーム
    Agent->>LLM: chat completions
    LLM-->>Agent: delta
    Agent-->>UI: TextDelta / ReasoningDelta …
    opt tool_calls
      Agent-->>UI: ToolCallBegin
      Note over Agent: calculate()
      Agent-->>UI: ToolResult
    end
    Agent-->>UI: StepEnd, TurnEnd …
  end
  Agent-->>UI: RunEnd
  UI->>User: バブル + ドロワー

  Note over User,UI: 停止 → AbortController<br/>（Wire インバウンドではない）
```

### 停止

```mermaid
flowchart LR
  STOP[UI: 停止] --> ABORT[AbortController.abort]
  ABORT --> HTTP[HTTP 切断]
  HTTP --> SR[StreamingResponse 終了]
  SR --> AGENT[Agent 生成停止]
```

Wire にキャンセル `method` は **なし** — HTTP ストリームを閉じて停止。

## 起動

例は `uv run` を使用。**uv** が初めての方は [公式ドキュメント](https://docs.astral.sh/uv/) を参照。

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
