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

uv run pagent
uv run python -m examples.pagentv4.thread_based.conversation_only
uv run python -m examples.pagentv4.thread_based.code_runner
uv run --with fastapi --with uvicorn python examples/wire_browser/server.py
```

| Example | Description |
|---------|-------------|
| [`examples/README.md`](https://github.com/SyncLionPaw/pagent/blob/main/examples/README.md) | Classified examples index |
| [`examples/pagentv4/thread_based`](https://github.com/SyncLionPaw/pagent/tree/main/examples/pagentv4/thread_based) | ChatRunner / CodeRunner examples |
| [`examples/pagentv4/runner`](https://github.com/SyncLionPaw/pagent/tree/main/examples/pagentv4/runner) | Runner.create examples |
| [`wire_browser`](https://github.com/SyncLionPaw/pagent/tree/main/examples/wire_browser) | FastAPI + browser UI |
