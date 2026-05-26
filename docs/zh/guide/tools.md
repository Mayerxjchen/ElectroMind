# 工具

语言： [中文](/zh/guide/tools) | [English](/guide/tools) | [日本語](/ja/guide/tools) | [四川话](/sc/guide/tools)

写一个 Python 函数，加上 `@tool()`，放进 `tools=[...]`。

## 定义工具

docstring 给模型看说明，类型注解生成参数 schema。

```python
from pagent import tool

@tool()
def get_weather(city: str) -> str:
    """查询指定城市的天气。"""
    return f"{city} 今天晴。"
```

## 交给 Agent

```python
from pagent import Agent, LLM, Session

agent = Agent(
    llm=LLM("gpt-4o-mini"),
    session=Session("天气问题用 get_weather。"),
    tools=[get_weather],
    max_turns=8,
)
await agent.run("厦门天气怎么样？")
```

多个工具：`tools=[a, b]`。改名字：`@tool(name="weather", description="...")`。

内置工具见 [内置工具](./defaults)。

## 相关

- [提示词](./prompt) · [记忆](./memory) · [内置工具](./defaults) · [事件流](/zh/events)
