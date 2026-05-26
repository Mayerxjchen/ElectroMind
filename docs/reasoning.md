# reasoning_content examples

Language: [简体中文](/reasoning.zh-CN) | English

Models such as DeepSeek may return **`reasoning_content`** (chain-of-thought) alongside **`content`** (user-facing answer). pagent carries both on **`RunEnd`**; in streaming mode **`ReasoningDelta`** and **`TextDelta`** events deliver them separately.

Event reference: [events.md](./events.md)

## Example scripts

| File | Mode | Description |
|------|------|-------------|
| [reasoning_run.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/reasoning_run.py) | Non-streaming | `agent.run()` → `RunEnd` |
| [reasoning_stream.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/reasoning_stream.py) | Streaming | `agent.arun_events()` → `ReasoningDelta` + `TextDelta` |
| [reasoning_common.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/reasoning_common.py) | Shared | Questions, `make_agent()` |

Also see [simple_qa.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/simple_qa.py) (tools) and [cli.py](https://github.com/SyncLionPaw/pagent/blob/main/examples/cli.py) (interactive CLI).

## Run

```bash
export DEEPSEEK_API_KEY="your-key-here"

uv run examples/reasoning_run.py
uv run examples/reasoning_stream.py

# Chinese (chicken–rabbit cage problem)
uv run examples/reasoning_run.py --zh
uv run examples/reasoning_stream.py --zh
```

`--zh` selects a Chinese system prompt and the 鸡兔同笼 problem; the default is an English logic puzzle (mislabeled boxes).

## Non-streaming: RunEnd

```python
end = await agent.run(question, reasoning_effort="medium")

print(end.reasoning_content)
print(end.content)
```

Use **`end.content`**, not `print(end)`, to avoid dumping the full `RunEnd` repr.

## Streaming: arun_events

```python
answer_started = False
async for event in agent.arun_events(question, reasoning_effort="medium"):
    match event:
        case ReasoningDelta(text=t):
            print(t, end="", flush=True)
        case TextDelta(text=t):
            if not answer_started:
                print("\nanswer: ", end="", flush=True)
                answer_started = True
            print(t, end="", flush=True)
        case RunEnd():
            print()
```

`agent.arun()` still yields answer text only (filters `TextDelta` internally).

## Questions

- **English (default):** three mislabeled boxes puzzle.
- **Chinese (`--zh`):** 鸡兔同笼 — 35 heads, 94 legs (answer: 23 chickens, 12 rabbits).

Edit `QUESTION_EN` / `QUESTION_ZH` in `reasoning_common.py`.

## reasoning_effort

Pass through `run_kwargs`, e.g. `reasoning_effort="medium"`. Whether `reasoning_content` appears depends on the provider and model.
