# pagentv4 Core Types

语言：[中文](/zh/pagentv4/core-types) | [English](/pagentv4/core-types)

`pagentv4` separates **configuration** (`AgentCore`), **conversation state**
(`Messages`), **orchestration** (`Runner`), and optional **execution**
(`Sandbox`).

## Main symbols

| Symbol | Role |
|--------|------|
| `Provider`, `DeepSeek`, `Ollama`, `Vllm`, `Sglang`, … | OpenAI-compatible streaming clients |
| `AgentCore(provider, system=None, tools=None, max_turns=24)` | Model + tool configuration |
| `Runner` | Thread-bound orchestrator: sandbox + messages + tool loop |
| `VanillaRunner(agent, messages=None)` | Lightweight in-memory loop with no thread, sandbox, or persistence |
| `ChatAgent`, `CodeAgent`, `ThreadAgent`, `VanillaAgent` | Agent-style aliases for the matching runner classes |
| `loop_core.run_event_loop(adapter, …)` | Shared event-loop kernel used by both runners |
| `Message` | One typed message item with `role` + `content` |
| `Messages` | In-memory message list with `to_openai()` conversion |
| `ConversationStore`, `JsonlConversationStore`, `SqliteConversationStore` | Persist messages by id |
| `Thread`, `ThreadSpec` | Long-lived thread: spec + messages + workspace |
| `Sandbox` | Companion computer with files and commands |
| `TurnResult` | One model turn summary: `content`, `tool_calls`, `reasoning_content` |
| `Event` | Union of event dataclasses emitted by the run loop |

## What a `turn` means

In `pagentv4`, a `turn` is one internal work cycle of the agent, not one user-facing conversation round.

It includes:

- one model generation
- the tool execution requested by that round
- the decision to continue or stop

Because of that, one run may contain multiple turns.
The user sends one `user_input`, while the agent may still go through turn 0, turn 1, turn 2, and so on until the run finishes.

Do not treat `TurnResult` and `TurnEnd` as the same thing:

- `TurnResult` is the summary of the model output for the current turn
- `TurnEnd` is the event that actually marks the end of that turn

## AgentCore

`AgentCore` is a configuration container. It does not own conversation history
or run the tool loop by itself.

```python
from pagentv4 import AgentCore, DeepSeek, tool


@tool()
def get_weather(city: str) -> str:
    """Return weather for a city."""
    return f"Sunny in {city} today."


agent = AgentCore(
    DeepSeek("deepseek-v4-flash"),
    system="You are concise.",
    tools=[get_weather],
    max_turns=24,
)
```

Notes:

- `system=` is inserted by `Runner` if no system message is present.
- Duplicate tool names are rejected at construction time.
- `max_turns` must be `>= 1`.
- `agent.generate_messages(messages)` performs one provider call only.
- `Agent` remains as a compatibility alias for `AgentCore`.

Some users prefer naming the whole runnable object an agent. `pagentv4` supports
that style with aliases:

```python
from pagentv4 import CodeAgent, ChatAgent, ThreadAgent

# Same classes as CodeRunner, ChatRunner, and Runner.
code = CodeAgent(agent, backend="local")
chat = ChatAgent(agent, thread_id="demo")
full = await ThreadAgent.create("demo", provider, overrides={"backend": "local"})
```

## Runner

`Runner` is created only via `Runner.create()` and lives as long as its thread.
It owns the multi-turn tool loop, sandbox, messages, and persistence.

The layering looks like this:

- `loop_core` handles the shared run, turn, tool call, `TurnResult`, `TurnEnd`, and `RunEnd` semantics
- `LoopAdapter` carries the shared loop skeleton (`execute_tool`, `stream_agent_events`, `emit`, `run`)
- `VanillaRunner(LoopAdapter)` reuses that loop with a minimal in-memory environment
- `BaseRunner(LoopAdapter)` adds thread, conversation store, sandbox, and skills, and flushes after each turn
- `Runner(BaseRunner)` adds the inbound control plane (steer/cancel/permit) and tool hooks

This keeps the different runtime layers aligned on turn/tool behavior while still exposing different runtime capabilities.

| Method | Role |
|--------|------|
| `Runner.create(thread_id, provider, …)` | Open thread → sandbox → agent |
| `runner.run(user_input, …)` | One user turn with `return_type` projection |
| `runner.close()` | Close sandbox |

```python
from pagentv4 import DeepSeek, Runner

runner = await Runner.create(
    "demo",
    DeepSeek("deepseek-v4-flash"),
    overrides={"backend": "local"},
    extra_system="You are helpful.",
    tools=[my_tool],  # optional extras merged with sandbox tools
)
try:
    async for event in runner.run("hi"):
        ...
finally:
    await runner.close()
```

Messages are flushed at each `TurnEnd` into the conversation store configured by
the thread. With the default JSONL backend, the path is
`~/.pagent/threads/<thread_id>/messages.jsonl`.

## loop_core

`loop_core` is the shared runtime kernel used by both `Runner` and
`VanillaRunner`.

It handles the common steps in a run:

- emit `RunBegin`
- enter each `TurnBegin`
- call `agent.generate_messages(messages)`
- build `TurnResult` from the message slice
- execute tool calls for the turn
- emit `TurnEnd` and `RunEnd`

`loop_core` leaves these concerns to the outer runner adapter:

- thread lifecycle
- sandbox
- message persistence
- inbound cancel / steer / checkpoint
- tool hooks
- skills injection

## Thread

A **thread** binds conversation history, thread config, and workspace on disk:

```text
~/.pagent/threads/<thread_id>/
  thread.toml
  workspace/
```

Use `Thread.open(thread_id, overrides={...})` to create or resume a thread.
The terminal app (`uv run pagent`) and `examples/app/repl.py` show the full pattern.

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

Reserved keys in `Provider.complete()`:

- `model`
- `messages`
- `stream`
- `tools`

| Provider | Environment variable |
|----------|---------------------|
| `Provider` | `OPENAI_API_KEY` |
| `DeepSeek` | `DEEPSEEK_API_KEY` |
| `Kimi` | `MOONSHOT_API_KEY` |
| `MiMo` | `MIMO_API_KEY` |
| `LongCat` | `LONGCAT_API_KEY` |
| `Ollama` | `OLLAMA_API_KEY` |
| `Vllm` | `VLLM_API_KEY` |
| `Sglang` | `SGLANG_API_KEY` |

`ProviderProtocol` is the structural type for `complete()` (tests and custom
backends may implement it without subclassing `Provider`).

## `run()` return types

Valid `return_type` values:

- `"event"`: raw events
- `"text"`: `TextDelta.text` only
- `"message"`: `Message` projection over the event stream
- `"acp"`: NDJSON JSON-RPC notifications

## Differences from `pagent`

- no `Session`
- no `LLM`
- typed `Message` objects instead of raw OpenAI-shaped dicts
- `Runner` instead of `Agent.arun()` for the full loop
- optional sandbox and conversation persistence

If you want the older `Session + LLM + arun_events()` API, stay on the main
`pagent` docs.
