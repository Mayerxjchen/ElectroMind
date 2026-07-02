# pagentv4 事件

语言：[中文](/zh/pagentv4/events) | [English](/pagentv4/events)

`Runner.events()` 发出完整多轮时间线。`Runner.arun()` 把同一流投影成四种返回类型之一。

## 事件类型

| 事件 | 字段 | 含义 |
|------|------|------|
| `RunBegin` | `user_input` | 新 run 开始 |
| `TurnBegin` | `turn` | 一次 provider 调用开始 |
| `TextDelta` | `text` | assistant 文本片段 |
| `ReasoningDelta` | `text` | assistant 推理片段 |
| `TurnResult` | `content`, `tool_calls`, `reasoning_content` | 单轮模型结束 |
| `ToolCallBegin` | `tool_call_id`, `name`, `arguments` | 即将执行工具 |
| `ToolResult` | `tool_call_id`, `name`, `content`, `ok` | 工具输出已追加 |
| `TurnEnd` | `turn`, `stopped`, `stop_reason` | 本轮结束；见下方 `StopReason` |

## 典型序列

有工具时：

```text
RunBegin
  TurnBegin(0)
    TextDelta*
    ReasoningDelta*
    TurnResult(tool_calls=[...])
    ToolCallBegin(...)
    ToolResult(...)
  TurnEnd(0, stopped=False, stop_reason="continuing")
  TurnBegin(1)
    TextDelta*
    TurnResult(tool_calls=[])
  TurnEnd(1, stopped=True, stop_reason="no_tool_calls")
```

无工具时：

```text
RunBegin
  TurnBegin(0)
    TextDelta*
    TurnResult(tool_calls=[])
  TurnEnd(0, stopped=True, stop_reason="no_tool_calls")
```

## `StopReason`

| 值 | `stopped` | 含义 |
|----|-----------|------|
| `continuing` | `False` | 工具已跑，还有下一轮模型调用 |
| `no_tool_calls` | `True` | 模型未调工具，run 结束 |
| `empty_response` | `True` | 模型无 assistant 消息，run 结束 |
| `max_turns` | `True` | 工具执行后达到 `max_turns` 上限，run 结束 |

## 消费方式

### 原始事件流

```python
from pagentv4 import Messages, Runner, TextDelta, ToolCallBegin, ToolResult

messages = Messages()
async for event in Runner().events(agent, "你好", messages):
    if isinstance(event, TextDelta):
        print(event.text, end="")
    elif isinstance(event, ToolCallBegin):
        print(f"\n[tool {event.name}]")
    elif isinstance(event, ToolResult):
        print(f"\n[result {event.ok}: {event.content}]")
```

### `arun(return_type="event")`

```python
async for event in Runner().arun(agent, "你好", messages, return_type="event"):
    ...
```

## 其他 `return_type` 投影

`Runner.arun()` 支持：

- `"event"`：原始事件对象
- `"text"`：仅 `TextDelta.text`
- `"message"`：从 `TextDelta`、`ReasoningDelta`、`ToolCallBegin`、`ToolResult` 投影的 `Message`
- `"acp"`：经 `encode_event_line()` 的 NDJSON JSON-RPC 通知

事件流是 `pagentv4` 中的唯一真相来源。
