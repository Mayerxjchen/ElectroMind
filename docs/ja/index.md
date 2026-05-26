---
layout: home

hero:
  image:
    src: /logo.png
    alt: pagent
  name: pagent
  text: あなたの軽量 Agent フレームワーク
  tagline: 小さく · 透ける · あなたが足す
  actions:
    - theme: brand
      text: クイックスタート
      link: /ja/guide/quick-start
    - theme: alt
      text: インストール
      link: /ja/guide/install
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
  - title: 流しながら表示
    details: ストリーミング出力に対応。UI を足すときはドキュメントで順を追って説明します。
  - title: OpenAI 形式 API
    details: OpenAI、DeepSeek、Ollama、vLLM、SGLang など /v1/chat/completions 互換サーバーに対応。
---

## 25 行足らずで Agent が動く

プロバイダのタブを選び、API Key を設定、`demo.py` で `python demo.py`。モデルが `@tool` を呼び、答えは `result.content`。

::: code-group

<<< ../snippets/minimal_agent_openai.py{python}[OpenAI]

<<< ../snippets/minimal_agent_deepseek.py{python}[DeepSeek]

<<< ../snippets/minimal_agent_claude.py{python}[Claude]

<<< ../snippets/minimal_agent_kimi.py{python}[Kimi]

:::

出力例：`Sunny in Xiamen today.`（実際の出力はモデル次第）。[プロバイダと API Key](./guide/providers)

[インストール →](./guide/install) · [クイックスタート →](./guide/quick-start)
