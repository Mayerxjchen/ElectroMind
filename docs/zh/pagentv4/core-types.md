# pagentv4 核心类型

语言：[中文](/zh/pagentv4/core-types) | [English](/pagentv4/core-types)

`pagentv4` 把 **配置**（`AgentCore`）、**对话状态**（`Messages`）、**编排**
（`Runner`）和可选的 **执行环境**（`Sandbox`）分开。

## 主要符号

| 符号 | 作用 |
|------|------|
| `Provider`, `DeepSeek`, `Ollama`, `Vllm`, `Sglang`, … | OpenAI 兼容流式客户端 |
| `AgentCore(provider, system=None, tools=None, max_turns=24)` | 模型 + 工具配置 |
| `Runner.create(thread_id, provider, …)` | Thread 绑定的编排器：sandbox + messages + tool loop |
| `VanillaRunner(agent, messages=None)` | 轻量内存循环：无 thread、无 sandbox、无持久化 |
| `ChatAgent`, `CodeAgent`, `ThreadAgent`, `VanillaAgent` | Agent 风格别名，对应同名 Runner 能力 |
| `loop_core.run_event_loop(adapter, …)` | `Runner` 与 `VanillaRunner` 共享的事件循环内核 |
| `Message` | 一条带 `role` + `content` 的类型化消息 |
| `Messages` | 内存消息列表，可 `to_openai()` 导出 |
| `ConversationStore`, `JsonlConversationStore`, `SqliteConversationStore` | 按 id 持久化消息 |
| `Thread`, `ThreadSpec` | 长期 thread：spec + 消息 + workspace |
| `Sandbox` | 伴身电脑，提供文件与命令能力 |
| `TurnResult` | 单轮模型摘要：`content`, `tool_calls`, `reasoning_content` |
| `Event` | 运行循环发出的事件 dataclass 联合类型 |

## `turn` 的定义

在 `pagentv4` 里，`turn` 是一次 agent 内部工作轮次，不是用户对话轮次。

它包含：

- 一次模型生成
- 这一轮请求的工具执行
- 对下一步继续还是结束的判定

因此，一个 run 可以包含多个 turn。
用户只发出一次 `user_input`，agent 仍然可能经历第 0 轮、第 1 轮、第 2 轮，直到 run 结束。

`TurnResult` 和 `TurnEnd` 也不要混为一谈：

- `TurnResult` 是本轮模型输出的摘要
- `TurnEnd` 才表示这一轮真正结束

## AgentCore

`AgentCore` 是配置容器，只保存 provider、system、tools 和 max_turns。
对话历史由 `Messages` 保存，工具循环由 Runner 执行。

```python
from pagentv4 import AgentCore, DeepSeek, tool


@tool()
def get_weather(city: str) -> str:
    """查询城市天气。"""
    return f"{city} 今天晴。"


agent = AgentCore(
    DeepSeek("deepseek-v4-flash"),
    system="回答要简洁。",
    tools=[get_weather],
    max_turns=24,
)
```

说明：

- 若没有 system 消息，`Runner` 会插入 `system=` 的内容。
- 构造时重复的工具名会报错。
- `max_turns` 必须 `>= 1`。
- `agent.generate_messages(messages)` 只发起一次 provider 调用。
- `Agent` 作为 `AgentCore` 的兼容别名保留。

如果你习惯把可运行整体称作 Agent，也可以使用这些别名：

```python
from pagentv4 import ChatAgent, CodeAgent, ThreadAgent

# 分别等价于 ChatRunner、CodeRunner 和 Runner。
chat = ChatAgent(agent, thread_id="demo")
code = CodeAgent(agent, backend="local")
full = await ThreadAgent.create("demo", provider, overrides={"backend": "local"})
```

## Runner

`Runner` 通过 `Runner.create()` 创建，并在 thread 生命周期内复用。
它负责多轮工具循环、sandbox、消息状态和持久化。

分层关系如下：

- `loop_core` 只关心 run、turn、tool call、`TurnResult`、`TurnEnd` 和 `RunEnd` 这些循环语义
- `VanillaRunner` 复用 `loop_core`，提供最小内存环境
- `Runner` 也复用 `loop_core`，再叠加 thread、sandbox、持久化、inbound 和 tool hooks

这样文档里的几种核心对象看起来职责不同，实现上也共用同一套 turn/tool 主干。

| 方法 | 作用 |
|------|------|
| `Runner.create(thread_id, provider, …)` | 打开 thread → 创建 sandbox → 绑定 agent |
| `runner.run(user_input, …)` | 一次用户输入，对事件流做 `return_type` 投影 |
| `runner.close()` | 关闭 sandbox |

```python
from pagentv4 import DeepSeek, Runner

runner = await Runner.create(
    "demo",
    DeepSeek("deepseek-v4-flash"),
    overrides={"backend": "local"},
    extra_system="回答要简洁。",
    tools=[my_tool],
)
try:
    async for event in runner.run("你好"):
        ...
finally:
    await runner.close()
```

消息会在每个 `TurnEnd` 后写入 thread 配置指定的 conversation store。
默认 JSONL 后端时，路径是：
`~/.pagent/threads/<thread_id>/messages.jsonl`。

## loop_core

`loop_core` 是 runtime 内部的共享循环内核，给 `Runner` 和
`VanillaRunner` 同时使用。

它处理这些公共步骤：

- 发出 `RunBegin`
- 进入每一轮 `TurnBegin`
- 调用 `agent.generate_messages(messages)`
- 从消息切片生成 `TurnResult`
- 执行本轮工具调用
- 根据结果发出 `TurnEnd` 和 `RunEnd`

`loop_core` 不直接管理这些内容：

- thread 生命周期
- sandbox
- 消息持久化
- inbound cancel / steer / checkpoint
- tool hooks
- skills 注入

这些能力由外层 runner 通过 adapter 方法接入。

## Thread

**thread** 把对话历史、thread 配置和 workspace 绑在磁盘上：

```text
~/.pagent/threads/<thread_id>/
  thread.toml
  workspace/
```

用 `Thread.open(thread_id, overrides={...})` 创建或恢复 thread。
完整用法见 `uv run pagent` 和 `examples/app/repl.py`。

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
| `Kimi` | `MOONSHOT_API_KEY` |
| `MiMo` | `MIMO_API_KEY` |
| `LongCat` | `LONGCAT_API_KEY` |
| `Ollama` | `OLLAMA_API_KEY` |
| `Vllm` | `VLLM_API_KEY` |
| `Sglang` | `SGLANG_API_KEY` |

`ProviderProtocol` 是 `complete()` 的结构化类型；测试或自定义后端可实现它，无需继承 `Provider`。

## `run()` 返回类型

合法 `return_type`：

- `"event"`：原始事件
- `"text"`：仅 `TextDelta.text`
- `"message"`：从事件流投影出的 `Message`
- `"acp"`：NDJSON JSON-RPC 通知

## 与 `pagent` 的差异

- 无 `Session`
- 无 `LLM`
- 用类型化 `Message` 替代原始 OpenAI dict
- 完整循环由 `Runner` 承担
- 可选 sandbox 与对话持久化

若仍要用 `Session + LLM + arun_events()`，请看顶层 `pagent` 文档。
