# 工具跟会话

语言：四川话 | [English](/guide/tools-session) | [普通话](/zh/guide/tools-session) | [日本語](/ja/guide/tools-session)

## Session（会话）

`Session(system_prompt)` 存 **OpenAI 消息格式** 的历史，摆在那儿给模型看，比如：

```python
session += {"role": "user", "content": "你好嘛"}
```

| 类 | 干啥子 |
|----|--------|
| `Session` | 基础缓冲，撇脱 |
| `SlidingWindowSession` | 按 **token** 上限裁（不是按条数哈） |
| `CompactingSession` | 上下文胀了用 LLM 压摘要，莫爆膛 |

## 工具

`@tool()` 装饰函数，从类型注解跟 docstring 生成 schema，省得你手写：

```python
from pagent import tool

@tool()
def calculate(expression: str) -> str:
    """算数学表达式。"""
    ...
```

传给 `Agent(..., tools=[calculate])`。模型返回 `tool_calls` 后，pagent 帮你执行完，结果以 `role: tool` 写回 session，一条龙。

可选内置：`web_search`、`clock`、`region`（见 [defaults.py](https://github.com/SyncLionPaw/pagent/blob/main/src/pagent/defaults.py)）。

## Agent 循环

```python
Agent(llm, session, tools=[], max_turns=8)
```

每轮：喊模型 → 可能要调工具 → 再喊模型，直到莫得工具或者到 `max_turns`，活路做杀割。

`Session` 你来 **经佑**，工具列表 **捡倒** 好别重名；流式用 `arun_events()` / `arun_wire()`，前端那边 **看到起** Wire 行就安逸。
