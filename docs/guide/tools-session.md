# Tools & session

Language: [中文](/zh/guide/tools-session) | [日本語](/ja/guide/tools-session) | [四川话](/sc/guide/tools-session) | English

## Session

`Session(system_prompt)` holds the message list in **OpenAI chat format**. Append with:

```python
session += {"role": "user", "content": "Hello"}
```

Variants:

| Class | Purpose |
|-------|---------|
| `Session` | Basic buffer |
| `SlidingWindowSession` | Trim by **token** budget (not message count) |
| `CompactingSession` | LLM summary compression when context is large |

## Tools

Decorate a Python function with `@tool()` — schema is inferred from type hints and docstring:

```python
from pagent import tool

@tool()
def calculate(expression: str) -> str:
    """Evaluate a math expression."""
    ...
```

Pass callables to `Agent(..., tools=[calculate])`. The model receives OpenAI-style `tools` definitions; pagent executes matching calls and appends `role: tool` messages.

Built-in optional tools: `web_search`, `clock`, `region` (see [defaults](https://github.com/SyncLionPaw/pagent/blob/main/src/pagent/defaults.py)).

## Agent loop

```python
Agent(llm, session, tools=[], max_turns=8)
```

Each turn: model → optional tool calls → model again until no tools or `max_turns`. Streaming: `arun_events()` / `arun_wire()`.
