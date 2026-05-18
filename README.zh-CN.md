# pagent（中文）

[![CI](https://github.com/SyncLionPaw/pagent/actions/workflows/ruff.yml/badge.svg)](https://github.com/SyncLionPaw/pagent/actions/workflows/ruff.yml)

语言切换： [中文](./README.zh-CN.md) | [English](./README.en.md)

**pagent** 是一个很小的 **async** Python 库：在 **OpenAI 兼容的 Chat Completions**（`messages` + function tools）上跑一个 `Agent` 循环。适合论文实验、评测脚本、教学演示——你能看清完整消息列表、自己写工具；不是开箱即用的「编程 Agent」产品，也不是 LangChain 那种大框架。

## 已实现什么

| 模块 | 能力 |
|------|------|
| **对话** | `Session` 保存 API 形状的消息 dict；`session += {...}`；`reset()`；`save_to_file()` |
| **调模型** | `LLM.invoke(messages, tools=...)` 无状态；历史由 `Session` 组装 |
| **Provider** | `LLM`、`DeepSeek`、`Ollama`、`Vllm`、`Sglang`（OpenAI SDK + `base_url`） |
| **工具** | `@tool()` / `FunctionTool`，docstring 转 JSON schema；`to_openai_tools()` |
| **Agent 循环** | 用户消息 → 模型 → 若有 tool calls 则执行并写回 session → 重复，直到无工具或达到 `max_turns` |
| **统计** | `AgentStats`：token 用量与轮次 |
| **内置工具** | `clock`、`region`（地区/时区线索，非 GPS）；可选 `web_search`（extra：`search`） |
| **提示词辅助** | `JUDGER_SYSTEM`：评判类任务的示例 system prompt |
| **实验性** | `pagent.memory.Memory`：纯文本行列表（未从顶层 `pagent` 导出） |

典型数据流：

```text
user → [Session] → LLM → assistant（含 tool_calls?）→ 执行工具 → tool 消息 → LLM → … → 最终文本
```

## 刻意不实现什么

以下**不在库内**，请在业务里自己加，或换别的工具：

- **流式输出** — `LLM.invoke` 固定 `stream=False`；`Agent.run` 无 token 流接口
- **并行 / 异步工具** — 同一轮多个 tool call 顺序执行，无 `asyncio.gather`
- **工具异常兜底** — 工具函数抛错会打断 `Agent.run`（仅「未知工具」和 `web_search` 部分错误会写成字符串）
- **RAG、向量库、文档加载、Chain、Planner、LangGraph 式状态图**
- **内置读文件 / Shell / IDE 工具** — 不改仓库、不跑终端、无沙箱
- **MCP、多 Agent 协作、人工确认、检查点、持久记忆**
- **多模态** — 仅文本 Chat Completions
- **鉴权、限流、可观测性** — 自备
- **非 Chat Completions 协议** — 无原生 Anthropic Messages / Gemini（除非网关转成 OpenAI 形状）

后端需兼容 **OpenAI Chat Completions**（`/v1/chat/completions`），否则请改网关或重写 `LLM.invoke`。

## 和 LangChain、Claude Code 对比

定位对比，不是功能打分表：

| | **pagent** | **LangChain** | **Claude Code** |
|---|------------|---------------|-----------------|
| **是什么** | 可嵌入的微型库（核心约几百行） | 大型框架 + 生态（Chain、Agent、各类集成） | 用 Claude 写代码的终端 / IDE **产品** |
| **你写什么** | Python：`Agent`、`Session`、`@tool()` | Python/JS；LCEL、LangGraph 等大量抽象 | 主要是提示与权限；工具多为内置 |
| **模型接口** | OpenAI Chat Completions（及兼容服务） | 多 Provider、多封装 | 产品内接 Anthropic（Claude） |
| **工具** | 仅你自己的 Python 函数 | 海量集成 + 自定义 | 改文件、bash、搜索、MCP 等 |
| **Agent 循环** | `agent.py` 里一条简单循环，可读可改 | ReAct、图、监督者等多种模式 | 产品内闭环，面向写代码优化 |
| **流式 / RAG / 记忆** | 无 / 无 / 仅实验性 `Memory` | 有（视模块而定） | 产品内处理上下文与工具 |
| **更适合** | 论文、评测、教学、要完全掌控循环 | 需要「电池Included」集成的应用 | 日常在仓库里编程 |
| **不适合** | 拿来就当生产级编程 Agent | 「我只要几十行且全透明」 | 当作 pip 库嵌进你的 Python 包 |

**LangChain** — 需要向量库、文档加载、LangGraph 工作流等集成，能接受框架体积时用。

**Claude Code** — 需要能直接改项目、跑命令的编码 Agent；不能替代在库里 `pip install pagent` 嵌入。

**pagent** — 需要循环简单透明、消息可 JSON 序列化、工具与部署自己接时用。

## 安装

```bash
pip install pagent
```

可选网页搜索（`ddgs`）：

```bash
pip install "pagent[search]"
```

源码开发：

```bash
cd pagent
uv sync --group dev --extra search   # 开发依赖 + search，便于测 web_search
pip install -e ".[search]"
```

## 快速开始

```python
import asyncio
import os

from pagent import Agent, LLM, Session, tool


@tool()
def get_weather(city: str) -> str:
    """Return a fake weather summary for the city."""
    return f"It's sunny in {city} today."


async def main() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("Please set OPENAI_API_KEY first.")

    agent = Agent(
        llm=LLM("gpt-4o-mini"),
        session=Session("You are a concise assistant. Use tools when needed."),
        tools=[get_weather],
        max_turns=8,
    )

    result = await agent.run("What's the weather in Xiamen?")
    print(result.content)
    print(agent.stats)


asyncio.run(main())
```

## 终端流式小助手

仓库提供了一个最小 CLI 示例：`examples/cli.py`。

```bash
python examples/cli.py
```

支持命令：

- `/help` 查看命令
- `/reset` 清空会话历史
- `/stats` 查看当前 token/turn 统计
- `/exit` 退出

需要先设置 `DEEPSEEK_API_KEY`。

内置搜索（需 `pagent[search]`）：

```python
from pagent import Agent, LLM, Session, web_search

agent = Agent(LLM("gpt-4o-mini"), Session("事实不确定时用 web_search。"), tools=[web_search])
```

## 环境变量

- `LLM(...)` 默认读取 `OPENAI_API_KEY`
- `DeepSeek(...)` 默认读取 `DEEPSEEK_API_KEY`
- 本地 provider 可选：`OLLAMA_API_KEY` / `VLLM_API_KEY` / `SGLANG_API_KEY`（未设置时使用占位 key）

## DeepSeek

- 文档： [DeepSeek API Docs](https://api-docs.deepseek.com/zh-cn/)
- `base_url`: `https://api.deepseek.com`
- 默认模型： `deepseek-v4-flash`

```python
from pagent import DeepSeek

llm = DeepSeek()  # or DeepSeek("deepseek-v4-pro")
```

高级参数可通过 `request_kwargs` 透传给 `chat.completions.create`。

## 本地部署

只要服务提供 OpenAI-compatible `/v1/chat/completions`，即可直接使用：

- `Ollama`: `http://127.0.0.1:11434/v1`
- `Vllm`: `http://127.0.0.1:8000/v1`
- `Sglang`: `http://127.0.0.1:30000/v1`

```python
from pagent import Ollama

llm = Ollama("llama3.2")
```

## 维护者：发布到 PyPI

仓库内置：`.github/workflows/publish.yml`（release 发布触发）。

建议使用 Trusted Publishing（OIDC）：

- Docs: <https://docs.pypi.org/trusted-publishers/>
