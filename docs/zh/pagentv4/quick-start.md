# pagentv4 快速开始

语言：[中文](/zh/pagentv4/quick-start) | [English](/pagentv4/quick-start)

`pagentv4` 是以消息为中心的 API，并增加了 `Runner` 编排层。
它用 `Message` / `Provider` 替代 `Session` / `LLM`，并可选接入 sandbox 与持久化。

前置：[安装](../guide/install)（Python 3.11+，pip / uv / conda）。

## 一行搞定：`run_agent()`

脚本或快速试模型时，用 `run_agent()`。它会在内部临时创建 `Messages`，跑完即弃。

```python
import asyncio
import os

from pagentv4 import Agent, DeepSeek, run_agent


async def main():
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise SystemExit("请先设置 DEEPSEEK_API_KEY")

    agent = Agent(
        DeepSeek("deepseek-v4-flash"),
        system="你是简洁助手。",
    )

    async for text in run_agent(
        agent, "用一句话解释什么是尾递归。", return_type="text"
    ):
        print(text, end="", flush=True)
    print()


asyncio.run(main())
```

## 多轮对话：`Runner`

需要跨调用保留 `Messages` 时：

```python
from pagentv4 import Agent, DeepSeek, Messages, Runner

agent = Agent(DeepSeek("deepseek-v4-flash"), system="你是简洁助手。")
runner = Runner()
messages = Messages()

async for text in runner.arun(
    agent, "我叫 Ada。", messages, return_type="text"
):
    print(text, end="")

async for text in runner.arun(
    agent, "我叫什么名字？", messages, return_type="text"
):
    print(text, end="")
```

## Sandbox 会话

Agent 需要读写文件或跑命令时，用 `Runner.session()`。它会创建 sandbox、
绑定 8 个内置工具、跑 agent，然后关闭 sandbox。

```python
from pagentv4 import DeepSeek, Runner

async for event in Runner().session(
    DeepSeek("deepseek-v4-flash"),
    "在 /home/agent 下创建 hello.txt，写一行问候语。",
    system="需要时用工具。",
    workspace_id="default",  # → <cwd>/.pagent/workspaces/default/
):
    ...
```

后端选项见 [Sandbox](./sandbox)（`local`、`docker`、`podman`、`ssh`）。

## 流式模式

`Runner.arun()` 默认 `return_type="event"`。

| API | 返回 | 适用场景 |
|-----|------|----------|
| `runner.arun(..., return_type="event")` | `Event` 对象 | 完整时间线、Python UI |
| `runner.arun(..., return_type="text")` | `str` 片段 | 只要回答文本 |
| `runner.arun(..., return_type="message")` | `Message` 对象 | 观察 assistant/tool 消息 |
| `runner.arun(..., return_type="acp")` | NDJSON 行 | Socket / ACP / JSON 消费者 |

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
