# 工具

语言：四川话 | [English](/guide/tools) | [普通话](/zh/guide/tools) | [日本語](/ja/guide/tools)

写个 Python 函数，加 `@tool()`，放进 `tools=[...]`。

## 定义工具

docstring 给模型看，类型注解整参数 schema。

```python
from pagent import tool

@tool()
def get_weather(city: str) -> str:
    """查指定城市天气。"""
    return f"{city} 今天晴。"
```

## 交给 Agent

```python
from pagent import Agent, LLM, Session

agent = Agent(
    llm=LLM("gpt-4o-mini"),
    session=Session("天气用 get_weather。"),
    tools=[get_weather],
    max_turns=8,
)
await agent.run("厦门天气咋个样？")
```

多个：`tools=[a, b]`。改名：`@tool(name="weather", description="...")`。

内置看 [内置工具](./defaults)。

## 相关

- [提示词](./prompt) · [记忆](./memory) · [内置工具](./defaults) · [事件流](/sc/events)
