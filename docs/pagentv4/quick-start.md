# pagentv4 Quick Start

语言：[中文](/zh/pagentv4/quick-start) | [English](/pagentv4/quick-start)

`pagentv4` is the message-centric API with a `Runner` orchestration layer.
It replaces `Session` / `LLM` with `Message` / `Provider`, and adds optional
sandbox and persistence support.

Prerequisites: [Install](../guide/install) (Python 3.11+, pip / uv / conda).

## Open a thread

`Runner` is bound to a **thread** for its entire lifetime: sandbox, messages,
and agent are created together and torn down with `runner.close()`.

```python
import asyncio
import os

from pagentv4 import DeepSeek, Runner


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("Set DEEPSEEK_API_KEY first.")

    runner = await Runner.create(
        "demo",
        DeepSeek("deepseek-v4-flash"),
        overrides={"backend": "local"},
        extra_system="You are helpful and concise.",
    )
    try:
        async for text in runner.run(
            "Explain tail recursion in one sentence.", return_type="text"
        ):
            print(text, end="", flush=True)
        print()
    finally:
        await runner.close()


asyncio.run(main())
```

## Multi-turn on the same thread

Call `runner.run()` again — messages accumulate and persist in the conversation
store configured by the thread. With the default JSONL backend, the path is
`<cwd>/.pagent/threads/<thread_id>/messages.jsonl`.

```python
runner = await Runner.create("demo", provider, overrides={"backend": "local"})
try:
    async for text in runner.run("My name is Ada.", return_type="text"):
        print(text, end="")
    async for text in runner.run("What is my name?", return_type="text"):
        print(text, end="")
finally:
    await runner.close()
```

Re-open the same `thread_id` later to resume.

## Sandbox + tools

`Runner.create()` creates the sandbox from the thread spec, binds built-in file
and command tools, and merges any extra tools you pass:

```python
runner = await Runner.create(
    "demo",
    DeepSeek("deepseek-v4-flash"),
    overrides={"backend": "local"},
    extra_system="Use tools when needed.",
)
try:
    async for event in runner.run(
        "Create hello.txt under /home/agent with one greeting line."
    ):
        ...
finally:
    await runner.close()
```

See [Sandbox](./sandbox) for backends (`local`, `docker`, `podman`, `ssh`).

## Streaming modes

`runner.run()` defaults to `return_type="event"`.

| API | Returns | Use when |
|-----|---------|----------|
| `runner.run(..., return_type="event")` | `Event` objects | Full timeline, Python UI |
| `runner.run(..., return_type="text")` | `str` chunks | Answer text only |
| `runner.run(..., return_type="message")` | `Message` objects | Observe assistant/tool messages |
| `runner.run(..., return_type="acp")` | NDJSON lines | Socket / ACP / JSON consumers |

## Built-in providers

```python
from pagentv4 import DeepSeek, Kimi, LongCat, MiMo, Ollama, Provider, Sglang, Vllm

deepseek = DeepSeek("deepseek-v4-flash")
ollama = Ollama("qwen3:8b")
vllm = Vllm("my-model")
sglang = Sglang("my-model")
```

`Provider` and the built-in subclasses forward to OpenAI-compatible
`/v1/chat/completions`.

## Next

- [Core types](./core-types)
- [Messages](./messages)
- [Tools](./tools)
- [Events](./events)
- [Sandbox](./sandbox)
