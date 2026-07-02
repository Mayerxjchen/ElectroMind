# pagentv4 Quick Start

语言：[中文](/zh/pagentv4/quick-start) | [English](/pagentv4/quick-start)

`pagentv4` is the message-centric API with a `Runner` orchestration layer.
It replaces `Session` / `LLM` with `Message` / `Provider`, and adds optional
sandbox and persistence support.

Prerequisites: [Install](../guide/install) (Python 3.11+, pip / uv / conda).

## One-liner: `run_agent()`

For scripts and quick experiments, use `run_agent()`. It creates a temporary
`Messages` internally and discards it when the run finishes.

```python
import asyncio
import os

from pagentv4 import Agent, DeepSeek, run_agent


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("Set DEEPSEEK_API_KEY first.")

    agent = Agent(
        DeepSeek("deepseek-v4-flash"),
        system="You are helpful and concise.",
    )

    async for text in run_agent(
        agent, "Explain tail recursion in one sentence.", return_type="text"
    ):
        print(text, end="", flush=True)
    print()


asyncio.run(main())
```

## Multi-turn with `Runner`

When you need to keep `Messages` across calls:

```python
from pagentv4 import Agent, DeepSeek, Messages, Runner

agent = Agent(DeepSeek("deepseek-v4-flash"), system="You are helpful.")
runner = Runner()
messages = Messages()

async for text in runner.arun(
    agent, "My name is Ada.", messages, return_type="text"
):
    print(text, end="")

async for text in runner.arun(
    agent, "What is my name?", messages, return_type="text"
):
    print(text, end="")
```

## Sandbox session

When the agent needs files or shell commands, use `Runner.session()`. It
creates a sandbox, binds eight built-in tools, runs the agent, then closes
the sandbox.

```python
from pagentv4 import DeepSeek, Runner

async for event in Runner().session(
    DeepSeek("deepseek-v4-flash"),
    "Create hello.txt under /home/agent with one greeting line.",
    system="Use tools when needed.",
    workspace_id="default",  # → <cwd>/.pagent/workspaces/default/
):
    ...
```

See [Sandbox](./sandbox) for backends (`local`, `docker`, `podman`, `ssh`).

## Streaming modes

`Runner.arun()` defaults to `return_type="event"`.

| API | Returns | Use when |
|-----|---------|----------|
| `runner.arun(..., return_type="event")` | `Event` objects | Full timeline, Python UI |
| `runner.arun(..., return_type="text")` | `str` chunks | Answer text only |
| `runner.arun(..., return_type="message")` | `Message` objects | Observe assistant/tool messages |
| `runner.arun(..., return_type="acp")` | NDJSON lines | Socket / ACP / JSON consumers |

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
