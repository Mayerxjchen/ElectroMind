# 内置工具

语言：四川话 | [English](/guide/defaults) | [普通话](/zh/guide/defaults) | [日本語](/ja/guide/defaults)

`pagent.defaults` 可选工具：`clock`、`region`、`web_search`。

```python
from pagent import Agent, LLM, Session, DEFAULT_TOOLS, clock, region, web_search

agent = Agent(
    llm=LLM("gpt-4o-mini"),
    session=Session("你是助手。"),
    tools=[*DEFAULT_TOOLS],
    max_turns=8,
)
```

`DEFAULT_TOOLS` 是 `[clock, region]`。`web_search` 要自己加还要装依赖。

## clock {#clock}

当前时间（ISO 8601）。

```python
tools=[clock]
```

## region {#region}

系统语言、时区（莫得 GPS）。

```python
tools=[region]
```

## web_search {#web-search}

DuckDuckGo 搜网页。

```bash
pip install 'pagent[search]'
```

```python
tools=[web_search]
```

## 相关

- [工具](./tools)
