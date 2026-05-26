# 工具与会话

语言： [中文](/zh/guide/tools-session) | [English](/guide/tools-session) | [日本語](/ja/guide/tools-session) | [四川话](/sc/guide/tools-session)

## Session（会话）

`Session(system_prompt)` 保存 **OpenAI 消息格式** 的历史，例如：

```python
session += {"role": "user", "content": "你好"}
```

| 类 | 作用 |
|----|------|
| `Session` | 基础缓冲 |
| `SlidingWindowSession` | 按 **token** 上限裁剪（不是条数） |
| `CompactingSession` | 上下文过大时用 LLM 压缩摘要 |

## 工具

用 `@tool()` 装饰函数，从类型注解和 docstring 生成 schema：

```python
from pagent import tool

@tool()
def calculate(expression: str) -> str:
    """计算数学表达式。"""
    ...
```

传给 `Agent(..., tools=[calculate])`。模型返回 `tool_calls` 后，pagent 执行并把结果以 `role: tool` 写回 session。

可选内置：`web_search`、`clock`、`region`（见 [defaults.py](https://github.com/SyncLionPaw/pagent/blob/main/src/pagent/defaults.py)）。

## Agent 循环

```python
Agent(llm, session, tools=[], max_turns=8)
```

每轮：模型 → 可能调工具 → 再调模型，直到无工具或达到 `max_turns`。流式用 `arun_events()` / `arun_wire()`。
