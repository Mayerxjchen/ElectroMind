# pagent

Minimal **async** Python library for an **Agent + tools** loop over **OpenAI-compatible Chat Completions**.

语言：本页 English · 用户指南见导航 **用户指南**（中文）

## Install

Python 3.11+.

```bash
pip install pagent
pip install "pagent[search]"   # optional web_search tool
```

## Quick start

```python
import asyncio
from pagent import Agent, LLM, Session, tool


@tool()
def get_weather(city: str) -> str:
    """Return weather for the city."""
    return f"Sunny in {city}."


async def main():
    agent = Agent(
        LLM("gpt-4o-mini"),
        Session("You are helpful. Use tools when needed."),
        tools=[get_weather],
    )
    result = await agent.run("Weather in Xiamen?")
    print(result.content)


asyncio.run(main())
```

## Streaming APIs

| API | Returns |
|-----|---------|
| `agent.run()` | Final `RunEnd` |
| `agent.arun()` | Answer text chunks |
| `agent.arun_events()` | Python `Event` objects |
| `agent.arun_wire()` | NDJSON (JSON-RPC 2.0) for frontends |

See [Events](events.md) and [Wire protocol](wire.md).

## Examples (repo)

```bash
uv run examples/cli.py
uv run examples/simple_qa.py
uv run --with fastapi --with uvicorn python examples/wire_demo/server.py
```

## Links

- [PyPI](https://pypi.org/project/pagent/)
- [Source](https://github.com/SyncLionPaw/pagent)
- README on GitHub: [English](https://github.com/SyncLionPaw/pagent/blob/main/README.md) · [中文](https://github.com/SyncLionPaw/pagent/blob/main/README.zh-CN.md)
