# 提示词

语言：四川话 | [English](/guide/prompt) | [普通话](/zh/guide/prompt) | [日本語](/ja/guide/prompt)

用 `Session` 写系统提示跟对话历史，再传给 `Agent`。

## 系统提示

```python
from pagent import Session

session = Session("你是简洁助手。")
```

## 用户消息

```python
session += {"role": "user", "content": "2+2 等于几？"}
```

## 跑起来

```python
from pagent import Agent, LLM

agent = Agent(llm=LLM("gpt-4o-mini"), session=session, tools=[], max_turns=8)
await agent.run("2+2 等于几？")
```

每次 `run()` 会把这轮用户话跟回复摞进 `session`。

## 对话拖长了

token 太多用 `SlidingWindowSession` 删旧的，或 `CompactingSession` 再 `await session.compact()` 压摘要。

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

- [工具](./tools) · [记忆](./memory) · [架势搞起](./quick-start)
