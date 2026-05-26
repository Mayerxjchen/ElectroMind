---
layout: home

hero:
  image:
    src: /logo.svg
    alt: pagent
  name: pagent
  text: 轻量 async Agent 循环
  tagline: OpenAI 兼容 · 消息摆得明明白白 · 工具自己整 · 用起来巴适
  actions:
    - theme: brand
      text: 架势搞起
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
    details: Session + Agent + 工具 — 莫得文件编辑、终端、MCP 那些花架子，循环你自己捏，撇脱。
  - title: 流式事件
    details: Python 用 arun_events() 瞅过程；前端/插件用 arun_wire() 吐 JSON-RPC NDJSON，要得。
  - title: OpenAI 那套 API
    details: OpenAI、DeepSeek、Ollama、vLLM、SGLang 等，只要兼容 /v1/chat/completions，莫得问题。
---

<div class="minimal-demo">

## 二十几行就整一个 Agent

钥匙 `OPENAI_API_KEY` 设好，存成 `demo.py`，直接 **搞起** `python demo.py`。模型要得的时候会调 `@tool`，答案在 `result.content` 里头，安逸。

<<< ../snippets/minimal_agent.py

<p class="output"><code>Sunny in Xiamen today.</code>（示例哈，实际看模型咋个回喃）</p>

[赶紧上手 →](./guide/quick-start) · [事件跟 Wire →](./events)

</div>

## 安装

```bash
pip install pagent
pip install "pagent[search]"   # 可选 web_search
```

要 **Python 3.11+**，这个莫得商量哈。下面按文档 **架势** 走，记到起嘛。

::: tip 协作向四川话（文档里会冒）
**搞起/架势** 开干 · **过一道** 检查 · **归一** 搞定 · **经佑/看到起** 照看模块 · **落教/稳当** 办得牢靠 · **攒劲** 继续冲
:::
