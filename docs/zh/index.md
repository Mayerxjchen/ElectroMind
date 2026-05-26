---
layout: home

hero:
  image:
    src: /logo.png
    alt: pagent
  name: pagent
  text: 你的轻量 Agent 框架
  tagline: 小库 · 全透明 · 你说了算
  actions:
    - theme: brand
      text: 快速开始
      link: /zh/guide/quick-start
    - theme: alt
      text: 安装
      link: /zh/guide/install
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
  - title: 边跑边看
    details: 支持流式输出，适合聊天界面；需要再接 UI 时，文档里一步步写清楚。
  - title: OpenAI 形态 API
    details: 支持 OpenAI、DeepSeek、Ollama、vLLM、SGLang 等兼容 /v1/chat/completions 的服务。
---

## 二十多行，就是一个 Agent

设置 `OPENAI_API_KEY`，保存为 `demo.py`，运行 `python demo.py`。模型会按需调用 `@tool`，答案在 `result.content`。

<<< ../snippets/minimal_agent.py

示例输出：`Sunny in Xiamen today.`（以模型实际返回为准）。

[安装 →](./guide/install) · [快速开始 →](./guide/quick-start)
