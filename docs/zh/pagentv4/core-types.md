# pagentv4 核心类型

语言：[中文](/zh/pagentv4/core-types) | [English](/pagentv4/core-types)

`pagentv4` 把 **配置**（`Agent`）、**对话状态**（`Messages`）、**编排**
（`Runner`）和可选的 **执行环境**（`Sandbox`）分开。

## 主要符号

| 符号 | 作用 |
|------|------|
| `Provider`, `DeepSeek`, `Ollama`, `Vllm`, `Sglang`, … | OpenAI 兼容流式客户端 |
| `Agent(provider, system=None, tools=None, max_turns=8)` | 模型 + 工具配置 |
| `Runner(store=None)` | 多轮循环、持久化、sandbox 会话 |
| `run_agent(agent, user_input, …)` | 一次性糖，内部走 `Runner().arun()` |
| `Message` | 一条带 `role` + `content` 的类型化消息 |
| `Messages` | 内存消息列表，可 `to_openai()` 导出 |
| `ConversationStore`, `JsonlConversationStore`, `SqliteConversationStore` | 按 id 持久化消息 |
| `Thread`, `ThreadSpec` | 长期 thread：spec + 消息 + workspace |
| `Sandbox` | 伴身电脑，提供文件与命令能力 |
| `TurnResult` | 单轮模型摘要：`content`, `tool_calls`, `reasoning_content` |
| `Event` | 运行循环发出的事件 dataclass 联合类型 |

## Agent

`Agent` 是配置容器，**不**持有对话历史，也**不**自己跑工具循环。

```python
from pagentv4 import Agent, DeepSeek, tool


@tool()
def get_weather(city: str) -> str:
    """查询城市天气。"""
    return f"{city} 今天晴。"


agent = Agent(
    DeepSeek("deepseek-v4-flash"),
    system="回答要简洁。",
    tools=[get_weather],
    max_turns=8,
)
```

说明：

- 若没有 system 消息，`Runner` 会插入 `system=` 的内容。
- 构造时重复的工具名会报错。
- `max_turns` 必须 `>= 1`。
- `agent.stream_messages(messages)` 只发起一次 provider 调用。

## Runner

`Runner` 负责多轮工具循环和可选持久化。

| 方法 | 作用 |
|------|------|
| `runner.arun(agent, user_input, messages, …)` | 完整 run，带 `return_type` 投影 |
| `runner.events(agent, user_input, messages, …)` | 原始事件流 |
| `runner.session(provider, user_input, …)` | 造 sandbox → 绑工具 → 跑 → 关 |
| `runner.load_conversation(id, messages)` | messages 为空时从 store 加载 |
| `runner.flush_conversation(id, messages)` | 写入 store |

`Runner` 带 store 时，给 `arun()` / `session()` 传 `conversation_id=`：

```python
from pagentv4 import JsonlConversationStore, Runner

runner = Runner(store=JsonlConversationStore())
async for event in runner.arun(
    agent, "你好", messages, conversation_id="demo"
):
    ...
```

每个 `TurnEnd` 会 flush 一次。默认 JSONL 根目录：
`<cwd>/.pagent/conversations/`。

## Thread

**thread** 把对话历史、sandbox 配置和 workspace 绑在磁盘上：

```text
<cwd>/.pagent/threads/<thread_id>/
  spec.json
  messages.jsonl
  workspace/
```

用 `Thread.open(thread_id, overrides={...})` 创建或恢复 thread。
完整用法见 `examples/v4runner/repl.py`。

## Provider

```python
from pagentv4 import Provider

provider = Provider(
    "gpt-4o-mini",
    base_url=None,
    apikey=None,
    request_kwargs=None,
)
```

`Provider.complete()` 保留这些请求字段：

- `model`
- `messages`
- `stream`
- `tools`

| Provider | 环境变量 |
|----------|----------|
| `Provider` | `OPENAI_API_KEY` |
| `DeepSeek` | `DEEPSEEK_API_KEY` |
| `Ollama` | `OLLAMA_API_KEY` |
| `Vllm` | `VLLM_API_KEY` |
| `Sglang` | `SGLANG_API_KEY` |

## `arun()` 返回类型

合法 `return_type`：

- `"event"`：原始事件
- `"text"`：仅 `TextDelta.text`
- `"message"`：从事件流投影出的 `Message`
- `"acp"`：NDJSON JSON-RPC 通知

## 与 `pagent` 的差异

- 无 `Session`
- 无 `LLM`
- 用类型化 `Message` 替代原始 OpenAI dict
- 完整循环由 `Runner` 承担，而非 `Agent.arun()`
- 可选 sandbox 与对话持久化

若仍要用 `Session + LLM + arun_events()`，请看顶层 `pagent` 文档。
