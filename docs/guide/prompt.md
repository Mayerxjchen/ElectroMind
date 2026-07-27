# Prompt

Language: [简体中文](/zh/guide/prompt) | [日本語](/ja/guide/prompt) | [四川话](/sc/guide/prompt) | English

Use `Session` for the system prompt and chat history, then pass it to `Agent`.

## System prompt

```python
from pagent import Session

session = Session("You are a concise assistant.")
```

## User message

```python
session += {"role": "user", "content": "What's 2+2?"}
```

## Run

```python
from pagent import Agent, LLM

agent = Agent(llm=LLM("gpt-4o-mini"), session=session, tools=[], max_turns=24)
await agent.run("What's 2+2?")
```

Each `run()` appends the user turn and the reply to `session`.

## Long chats

Too many tokens? Use `SlidingWindowSession` to drop old turns, or `CompactingSession` and `await session.compact()` to summarize.

```python
from pagent import SlidingWindowSession, CompactingSession, LLM

session = SlidingWindowSession("You are helpful.", max_tokens=8000)

llm = LLM("gpt-4o-mini")
session = CompactingSession("You are helpful.", llm=llm, compact_at_tokens=6000)
if session.should_compact:
    await session.compact()
```

## Save

```python
session.save_to_file("chat.json")
```

## See also

- [Tools](./tools) · [Memory](./memory) · [Quick start](./quick-start)
