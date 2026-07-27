# Tools

Language: [简体中文](/zh/guide/tools) | [日本語](/ja/guide/tools) | [四川话](/sc/guide/tools) | English

Write a Python function, add `@tool()`, pass it in `tools=[...]`.

## Define a tool

Docstring = what the model sees. Type hints = argument schema.

```python
from pagent import tool

@tool()
def get_weather(city: str) -> str:
    """Return weather for a city."""
    return f"Sunny in {city} today."
```

## Use with Agent

```python
from pagent import Agent, LLM, Session

agent = Agent(
    llm=LLM("gpt-4o-mini"),
    session=Session("Use get_weather for weather."),
    tools=[get_weather],
    max_turns=24,
)
await agent.run("Weather in Xiamen?")
```

Multiple tools: `tools=[a, b]`. Custom name: `@tool(name="weather", description="...")`.

Built-in: [defaults](./defaults) (`clock`, `region`, `readfile`, `web_search`, `bash`).

## See also

- [Prompt](./prompt) · [Memory](./memory) · [Defaults](./defaults) · [Events](/events)
