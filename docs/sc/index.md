---
layout: home

hero:
  image:
    src: /logo.svg
    alt: pagent
  name: pagent
  text: 轻量 async Agent 循环
  tagline: OpenAI 兼容 Chat Completions · 消息摆得明明白白 · 工具自己整
  actions:
    - theme: brand
      text: 赶紧上手
      link: /sc/guide/quick-start
    - theme: alt
      text: 事件跟 Wire
      link: /sc/events
    - theme: alt
      text: English
      link: /
    - theme: alt
      text: 普通话
      link: /zh/
    - theme: alt
      text: 日本語
      link: /ja/

features:
  - title: 小巧好嵌
    details: Session + Agent + 工具 — 莫得文件编辑、终端、MCP，循环你自己捏。
  - title: 流式事件
    details: Python 用 arun_events()；前端/插件用 arun_wire() 吐 JSON-RPC NDJSON。
  - title: OpenAI 那套 API
    details: OpenAI、DeepSeek、Ollama、vLLM、SGLang 等，只要兼容 /v1/chat/completions 都行。
---

## 安装

```bash
pip install pagent
pip install "pagent[search]"   # 可选 web_search
```

要 **Python 3.11+**。完整例子看 [赶紧上手](./guide/quick-start)。
