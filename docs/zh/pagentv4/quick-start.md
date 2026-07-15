# pagentv4 快速开始

语言：[中文](/zh/pagentv4/quick-start) | [English](/pagentv4/quick-start)

`pagentv4` 是以消息为中心的 API，并增加了 `Runner` 编排层。
它用 `Message` / `Provider` 替代 `Session` / `LLM`，并可选接入 sandbox 与持久化。

前置：[安装](../guide/install)（Python 3.11+，pip / uv / conda）。

## 打开一个 thread

`Runner` 在整个生命周期内绑定到一个 **thread**：sandbox、messages 和 agent
一起创建，并在 `runner.close()` 时关闭。

```python
import asyncio
import os

from pagentv4 import DeepSeek, Runner


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请先设置 DEEPSEEK_API_KEY")

    runner = await Runner.create(
        "demo",
        DeepSeek("deepseek-v4-flash"),
        overrides={"backend": "local"},
        extra_system="你是简洁助手。",
    )
    try:
        async for text in runner.run("用一句话解释什么是尾递归。", return_type="text"):
            print(text, end="", flush=True)
        print()
    finally:
        await runner.close()


asyncio.run(main())
```

## 同一个 thread 内多轮对话

再次调用 `runner.run()` 会复用同一份 messages，并持久化到 thread 配置指定的
conversation store。默认 JSONL 后端时，路径是
`~/.pagent/threads/<thread_id>/messages.jsonl`。

```python
runner = await Runner.create("demo", provider, overrides={"backend": "local"})
try:
    async for text in runner.run("我叫 Ada。", return_type="text"):
        print(text, end="")

    async for text in runner.run("我叫什么名字？", return_type="text"):
        print(text, end="")
finally:
    await runner.close()
```

后续重新打开同一个 `thread_id` 可以继续这条 thread。

## Sandbox + tools

`Runner.create()` 会根据 thread spec 创建 sandbox，绑定内置文件和命令工具，
并合并你传入的额外工具。

```python
from pagentv4 import DeepSeek, Runner

runner = await Runner.create(
    "demo",
    DeepSeek("deepseek-v4-flash"),
    overrides={"backend": "local"},
    extra_system="需要时使用工具。",
)
try:
    async for event in runner.run("在 /home/agent 下创建 hello.txt，写一行问候语。"):
        ...
finally:
    await runner.close()
```

后端选项见 [Sandbox](./sandbox)（`local`、`docker`、`podman`、`ssh`）。

## 轻量内存循环：`VanillaRunner`

脚本里只需要临时 messages 和普通 Python tools 时，用 `VanillaRunner`。
它没有 thread、sandbox 和持久化。

```python
from pagentv4 import AgentCore, DeepSeek, VanillaRunner

agent = AgentCore(DeepSeek("deepseek-v4-flash"), system="你是简洁助手。")
runner = VanillaRunner(agent)

async for text in runner.run("用一句话解释什么是尾递归。", return_type="text"):
    print(text, end="")
```

## 流式模式

`runner.run()` 默认 `return_type="event"`。

| API | 返回 | 适用场景 |
|-----|------|----------|
| `runner.run(..., return_type="event")` | `Event` 对象 | 完整时间线、Python UI |
| `runner.run(..., return_type="text")` | `str` 片段 | 只要回答文本 |
| `runner.run(..., return_type="message")` | `Message` 对象 | 观察 assistant/tool 消息 |
| `runner.run(..., return_type="acp")` | NDJSON 行 | Socket / ACP / JSON 消费者 |

## 内置 Provider

```python
from pagentv4 import DeepSeek, Kimi, LongCat, MiMo, Ollama, Provider, Sglang, Vllm

deepseek = DeepSeek("deepseek-v4-flash")
ollama = Ollama("qwen3:8b")
vllm = Vllm("my-model")
sglang = Sglang("my-model")
```

`Provider` 及内置子类均转发到 OpenAI 兼容的 `/v1/chat/completions`。

## 下一步

- [核心类型](./core-types)
- [消息](./messages)
- [工具](./tools)
- [事件](./events)
- [Sandbox](./sandbox)
