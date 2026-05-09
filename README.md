# pagent

Small **async** agent core built on OpenAI-compatible **Chat Completions** APIs:

- `Session`: system / user / assistant / tool messages
- `LLM`: stateless wrapper around `AsyncOpenAI` (+ optional backends: DeepSeek, vLLM, ChatAnywhere)
- `@tool()` / `FunctionTool`: expose Python callables as function-calling schemas
- `Agent`: multi-turn loop until the model stops calling tools or `max_turns` is exceeded

## Install

```bash
pip install pagent
```

Or from a checkout:

```bash
cd pagent
uv sync
pip install -e .
```

## Quick usage

```python
import asyncio
from pagent import Agent, DeepSeek, Session, tool


@tool()
def get_weather(city: str) -> str:
    """Return a fake weather string.

    Args:
        city: City name.
    """
    return f"sunny in {city}"


async def main() -> None:
    agent = Agent(
        llm=DeepSeek(),
        session=Session("You are a helpful assistant."),
        tools=[get_weather],
    )
    out = await agent.run("What's the weather in Xiamen?")
    print(out.content)


asyncio.run(main())
```

Set the appropriate API key (`DEEPSEEK_API_KEY` for `DeepSeek`, or `OPENAI_API_KEY` for the base `LLM` class).
