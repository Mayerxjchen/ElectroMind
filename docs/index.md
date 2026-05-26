---
layout: home

hero:
  name: pagent
  text: Minimal async Agent loop
  tagline: OpenAI-compatible Chat Completions · transparent messages · your own tools
  actions:
    - theme: brand
      text: Quick start
      link: /guide/quick-start
    - theme: alt
      text: Events & Wire
      link: /events
    - theme: alt
      text: 中文文档
      link: /zh/
    - theme: alt
      text: 日本語
      link: /ja/
    - theme: alt
      text: 四川话
      link: /sc/

features:
  - title: Small & embeddable
    details: Session + Agent + tools — no file editor, no shell, no MCP. You own the loop.
  - title: Streaming events
    details: arun_events() for Python UIs; arun_wire() emits JSON-RPC NDJSON for web and IDE plugins.
  - title: OpenAI-shaped API
    details: Works with OpenAI, DeepSeek, Ollama, vLLM, SGLang — any /v1/chat/completions compatible server.
---

## Install

```bash
pip install pagent
pip install "pagent[search]"   # optional web_search
```

Python **3.11+**. See [Quick start](./guide/quick-start) for a full example.
