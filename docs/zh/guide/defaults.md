# 内置工具

语言： [中文](/zh/guide/defaults) | [English](/guide/defaults) | [日本語](/ja/guide/defaults) | [四川话](/sc/guide/defaults)

`pagent.defaults` 提供可选工具：`clock`、`region`、`web_search`。

```python
from pagent import Agent, LLM, Session, DEFAULT_TOOLS, clock, region, web_search

agent = Agent(
    llm=LLM("gpt-4o-mini"),
    session=Session("你是助手。"),
    tools=[*DEFAULT_TOOLS],  # clock + region
    max_turns=8,
)
```

`DEFAULT_TOOLS` 为 `[clock, region]`。`web_search` 需单独加入并安装依赖。

## clock {#clock}

返回当前时间（ISO 8601）。

```python
tools=[clock]
# 默认 utc=True；utc=False 为本地时间
```

## region {#region}

系统语言、时区等（无 GPS）。

```python
tools=[region]
```

## web_search {#web-search}

DuckDuckGo 网页搜索。

```bash
pip install 'pagent[search]'
```

```python
tools=[web_search]
```

## 相关

- [工具](./tools)（自定义 `@tool`）
