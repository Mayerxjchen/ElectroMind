# pagentv2 Quick Start

`pagentv2` is the newer message-centric API in this repo. It keeps the same
small runtime shape, but replaces `Session` / `LLM` with `Message` / `Provider`.

Prerequisites: [Install](../guide/install) (Python 3.11+, pip / uv / conda).

## Minimal agent

```python
import asyncio
import os

from pagentv2 import Agent, Provider, tool


@tool()
def get_weather(city: str) -> str:
    """Return weather for a city."""
    return f"Sunny in {city} today."


async def main():
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY first.")

    agent = Agent(
        Provider("gpt-4o-mini"),
        system="You are helpful. Use tools when needed.",
        tools=[get_weather],
        max_turns=8,
    )

    answer_parts: list[str] = []
    async for text in agent.arun("Weather in Xiamen?", return_type="text"):
        answer_parts.append(text)

    print("".join(answer_parts))


asyncio.run(main())
```

## Streaming modes

Unlike `pagent.Agent.arun()`, `pagentv2.Agent.arun()` defaults to
`return_type="event"`.

| API | Returns | Use when |
|-----|---------|----------|
| `agent.arun(..., return_type="event")` | `Event` objects | Full timeline, Python UI |
| `agent.arun(..., return_type="text")` | `str` chunks | Answer text only |
| `agent.arun(..., return_type="message")` | `Message` objects | Observe assistant/tool messages |
| `agent.arun(..., return_type="acp")` | NDJSON lines | Socket / ACP / JSON consumers |

## Built-in providers

```python
from pagentv2 import DeepSeek, Ollama, Vllm, Sglang

deepseek = DeepSeek("deepseek-v4-flash")
ollama = Ollama("qwen3:8b")
vllm = Vllm("my-model")
sglang = Sglang("my-model")
```

`Provider` and the built-in subclasses forward to
OpenAI-compatible `/v1/chat/completions`.

## Next

- [Core types](./core-types)
- [Messages](./messages)
- [Tools](./tools)
- [Events](./events)
- [Provider](./provider)
