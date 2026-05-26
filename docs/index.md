---
layout: home

hero:
  image:
    src: /logo.png
    alt: pagent
  name: pagent
  text: Your minimal agent framework
  tagline: Small · transparent · you extend it
  actions:
    - theme: brand
      text: Quick start
      link: /guide/quick-start
    - theme: alt
      text: Install
      link: /guide/install
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
  - title: Stream as it runs
    details: Incremental output for chat UIs — wire up your own frontend when you are ready; the docs walk you through it.
  - title: OpenAI-shaped API
    details: Works with OpenAI, DeepSeek, Ollama, vLLM, SGLang — any /v1/chat/completions compatible server.
---

## A full agent in ~25 lines

Set `OPENAI_API_KEY`, save as `demo.py`, run `python demo.py`. The model can call your `@tool` and you read the answer from `result.content`.

<<< ./snippets/minimal_agent.py

Example output: `Sunny in Xiamen today.` (actual text depends on the model).

[Install →](./guide/install) · [Quick start →](./guide/quick-start)
