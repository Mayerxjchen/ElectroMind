---
layout: home

hero:
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

## インストール

```bash
pip install pagent
pip install "pagent[search]"   # 任意 web_search
```

**Python 3.11+**。[クイックスタート](./guide/quick-start) を参照。
