# Quick start

Language: [中文](/zh/guide/quick-start) | [日本語](/ja/guide/quick-start) | [四川话](/sc/guide/quick-start) | English

Prerequisites: [Install](./install) (Python 3.11+, pip / uv / conda).

## Minimal agent

```python
import asyncio
import os

from pagent import Agent, LLM, Session, tool


@tool()
def get_weather(city: str) -> str:
    """Return weather for the city."""
    return f"Sunny in {city} today."


async def main():
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY first.")

    agent = Agent(
        llm=LLM("gpt-4o-mini"),
        session=Session("You are helpful. Use tools when needed."),
        tools=[get_weather],
        max_turns=8,
    )

    result = await agent.run("What's the weather in Xiamen?")
    print(result.content)


asyncio.run(main())
```

`run()` returns **`RunEnd`** — use `.content` for the answer.

## Streaming APIs

| API | Returns | Use when |
|-----|---------|----------|
| `agent.run()` | `RunEnd` | No streaming |
| `agent.arun()` | `str` chunks | Typing effect, text only |
| `agent.arun_events()` | `Event` objects | Python UI, tests |
| `agent.arun_wire()` | NDJSON lines | Browser, VS Code plugin, any JSON consumer |

Next: [Providers & API keys](./providers) · [Events](/events) · [Wire protocol](/wire)

## Examples (clone repo)

```bash
git clone https://github.com/SyncLionPaw/pagent.git
cd pagent
export DEEPSEEK_API_KEY="your-key"   # for DeepSeek examples

uv run examples/cli.py
uv run examples/simple_qa.py
uv run examples/reasoning_stream.py --zh
uv run --with fastapi --with uvicorn python examples/wire_demo/server.py
```

| Script | Description |
|--------|-------------|
| [cli.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/cli.py) | Interactive CLI (`arun`, text only) |
| [cli_events.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/cli_events.py) | CLI with tools/reasoning via `arun_events` |
| [simple_qa.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/simple_qa.py) | Tools demo |
| [reasoning_stream.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/reasoning_stream.py) | Reasoning + answer stream |
| [wire_demo](https://github.com/SyncLionPaw/pagent/tree/main/examples/wire_demo) | FastAPI + browser UI |
