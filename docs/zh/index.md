---
layout: home

hero:
  image:
    src: /logo.svg
    alt: pagent
  name: pagent
  text: 轻量 async Agent 循环
  tagline: OpenAI 兼容 Chat Completions · 消息透明 · 工具自己写
  actions:
    - theme: brand
      text: 快速开始
      link: /zh/guide/quick-start
    - theme: alt
      text: 事件与 Wire
      link: /zh/events
    - theme: alt
      text: English
      link: /
    - theme: alt
      text: 日本語
      link: /ja/
    - theme: alt
      text: 四川话
      link: /sc/

features:
  - title: 小而可嵌入
    details: Session + Agent + 工具 — 不带文件编辑、终端或 MCP，循环由你掌控。
  - title: 流式事件
    details: Python 用 arun_events()；前端/插件用 arun_wire() 输出 JSON-RPC NDJSON。
  - title: OpenAI 形态 API
    details: 支持 OpenAI、DeepSeek、Ollama、vLLM、SGLang 等兼容 /v1/chat/completions 的服务。
---

## 安装

```bash
pip install pagent
pip install "pagent[search]"   # 可选 web_search
```

需要 **Python 3.11+**。

## 二十多行，就是一个 Agent

设置 `OPENAI_API_KEY`，保存为 `demo.py`，运行 `python demo.py`。模型会按需调用 `@tool`，答案在 `result.content`。

<<< ../snippets/minimal_agent.py

示例输出：`Sunny in Xiamen today.`（以模型实际返回为准）。

[快速开始 →](./guide/quick-start) · [事件流与 Wire →](./events)
