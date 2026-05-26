# 組み込みツール

言語: [日本語](/ja/guide/defaults) | [English](/guide/defaults) | [简体中文](/zh/guide/defaults) | [四川话](/sc/guide/defaults)

`pagent.defaults` の任意ツール: `clock`、`region`、`web_search`。

```python
from pagent import Agent, LLM, Session, DEFAULT_TOOLS, clock, region, web_search

agent = Agent(
    llm=LLM("gpt-4o-mini"),
    session=Session("助手として答えて。"),
    tools=[*DEFAULT_TOOLS],
    max_turns=8,
)
```

`DEFAULT_TOOLS` は `[clock, region]`。`web_search` は別途追加とインストールが必要。

## clock {#clock}

現在時刻（ISO 8601）。

```python
tools=[clock]
```

## region {#region}

OS のロケール / タイムゾーン（GPS なし）。

```python
tools=[region]
```

## web_search {#web-search}

DuckDuckGo で Web 検索。

```bash
pip install 'pagent[search]'
```

```python
tools=[web_search]
```

## 関連

- [ツール](./tools)
