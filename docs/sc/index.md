---
layout: home

hero:
  image:
    src: /logo.png
    alt: pagent
  name: pagent
  text: 丁丁儿 智能体 架架儿，你国人捏拢
  tagline: 么得花架子 · 眯起眼睛都看的清白 · 随在你整嘛
  actions:
    - theme: brand
      text: 架势搞起
      link: /sc/guide/quick-start
    - theme: alt
      text: 安装
      link: /sc/guide/install
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
  - title: 边跑边看
    details: 支持流式输出，聊天界面巴适；要接 UI 了，文档里头一步一步摆清楚。
  - title: OpenAI 那套 API
    details: OpenAI、DeepSeek、Ollama、vLLM、SGLang 等，只要兼容 /v1/chat/completions，莫得问题。
---

## 二十几行就整一个 Agent

钥匙 `OPENAI_API_KEY` 设好，存成 `demo.py`，直接 **搞起** `python demo.py`。模型要得的时候会调 `@tool`，答案在 `result.content` 里头，安逸。

<<< ../snippets/minimal_agent.py

示例输出：`Sunny in Xiamen today.`（示例哈，实际看模型咋个回喃）。

[安装 →](./guide/install) · [赶紧上手 →](./guide/quick-start)

::: tip 协作向四川话（文档里会冒）
**搞起/架势** 开干 · **过一道** 检查 · **归一** 搞定 · **经佑/看到起** 照看模块 · **落教/稳当** 办得牢靠 · **攒劲** 继续冲
:::
