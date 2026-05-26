---
layout: home

hero:
  image:
    src: /logo.svg
    alt: pagent
  name: pagent
  text: 軽量 async Agent ループ
  tagline: OpenAI 互換 Chat Completions · 透明なメッセージ · 自作ツール
  actions:
    - theme: brand
      text: クイックスタート
      link: /ja/guide/quick-start
    - theme: alt
      text: イベントと Wire
      link: /ja/events
    - theme: alt
      text: English
      link: /
    - theme: alt
      text: 中文文档
      link: /zh/
    - theme: alt
      text: 四川话
      link: /sc/

features:
  - title: 小さく埋め込み可能
    details: Session + Agent + ツール — ファイル編集やシェル、MCP は含みません。ループはあなたが握ります。
  - title: ストリーミングイベント
    details: Python は arun_events()、フロントは arun_wire() の JSON-RPC NDJSON。
  - title: OpenAI 形式 API
    details: OpenAI、DeepSeek、Ollama、vLLM、SGLang など /v1/chat/completions 互換サーバーに対応。
---

<div class="minimal-demo">

## 25 行足らずで Agent が動く

`OPENAI_API_KEY` を設定し、`demo.py` として保存して `python demo.py`。モデルが `@tool` を呼び、答えは `result.content` に入ります。

<<< ../snippets/minimal_agent.py

<p class="output"><code>Sunny in Xiamen today.</code>（例 — 実際の出力はモデル次第）</p>

[クイックスタート →](./guide/quick-start) · [イベントと Wire →](./events)

</div>

## インストール

```bash
pip install pagent
pip install "pagent[search]"   # 任意 web_search
```

**Python 3.11+**。
