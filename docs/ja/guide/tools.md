# ツール

言語: [日本語](/ja/guide/tools) | [English](/guide/tools) | [简体中文](/zh/guide/tools) | [四川话](/sc/guide/tools)

Python 関数に `@tool()` を付け、`tools=[...]` に渡します。

## 定義

docstring が説明、型ヒントが引数スキーマになります。

```python
from pagent import tool

@tool()
def get_weather(city: str) -> str:
    """都市の天気を返す。"""
    return f"{city} は今日晴れです。"
```

## Agent で使う

```python
from pagent import Agent, LLM, Session

agent = Agent(
    llm=LLM("gpt-4o-mini"),
    session=Session("天気は get_weather を使う。"),
    tools=[get_weather],
    max_turns=8,
)
await agent.run("厦门の天気は？")
```

複数: `tools=[a, b]`。名前変更: `@tool(name="weather", description="...")`。

組み込みは [組み込みツール](./defaults) を参照。

## 関連

- [プロンプト](./prompt) · [メモリ](./memory) · [組み込みツール](./defaults) · [イベント](/ja/events)
