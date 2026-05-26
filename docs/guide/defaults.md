# Built-in tools

Language: [简体中文](/zh/guide/defaults) | [日本語](/ja/guide/defaults) | [四川话](/sc/guide/defaults) | English

Optional tools in `pagent.defaults`: `clock`, `region`, `web_search`.

```python
from pagent import Agent, LLM, Session, DEFAULT_TOOLS, clock, region, web_search

agent = Agent(
    llm=LLM("gpt-4o-mini"),
    session=Session("You are helpful."),
    tools=[*DEFAULT_TOOLS],  # clock + region
    max_turns=8,
)
```

`DEFAULT_TOOLS` is `[clock, region]`. Add `web_search` yourself (needs extra install).

## clock {#clock}

Current time as ISO 8601.

```python
tools=[clock]
# utc=True (default) or utc=False for local time
```

## region {#region}

OS locale and timezone hint (no GPS).

```python
tools=[region]
```

## web_search {#web-search}

Web search via DuckDuckGo.

```bash
pip install 'pagent[search]'
```

```python
tools=[web_search]
```

## See also

- [Tools](./tools) (write your own `@tool`)
