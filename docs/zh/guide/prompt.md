# 提示词

语言： [中文](/zh/guide/prompt) | [English](/guide/prompt) | [日本語](/ja/guide/prompt) | [四川话](/sc/guide/prompt)

用 `Session` 写系统提示和对话历史，再传给 `Agent`。

## 系统提示

```python
from pagent import Session

session = Session("你是简洁助手。")
```

## 用户消息

```python
session += {"role": "user", "content": "2+2 等于几？"}
```

## 运行

```python
from pagent import Agent, LLM

agent = Agent(llm=LLM("gpt-4o-mini"), session=session, tools=[], max_turns=24)
await agent.run("2+2 等于几？")
```

每次 `run()` 会把本轮用户话和回复追加进 `session`。

## 对话很长

token 太多时用 `SlidingWindowSession` 删旧消息，或用 `CompactingSession` 再 `await session.compact()` 做摘要。

```python
from pagent import SlidingWindowSession, CompactingSession, LLM

session = SlidingWindowSession("你是助手。", max_tokens=8000)

llm = LLM("gpt-4o-mini")
session = CompactingSession("你是助手。", llm=llm, compact_at_tokens=6000)
if session.should_compact:
    await session.compact()
```

## 存盘

```python
session.save_to_file("chat.json")
```

## 相关

- [工具](./tools) · [记忆](./memory) · [快速开始](./quick-start)
