# pagentv2 Provider

`pagentv2` replaces `LLM` with a smaller `Provider` abstraction.

## Basic usage

```python
from pagentv2 import Provider

provider = Provider("gpt-4o-mini")
```

Built-in subclasses:

```python
from pagentv2 import DeepSeek, Ollama, Vllm, Sglang

deepseek = DeepSeek("deepseek-v4-flash")
ollama = Ollama("qwen3:8b")
vllm = Vllm("my-model")
sglang = Sglang("my-model")
```

## Constructor

```python
Provider(
    model_id: str,
    base_url: str | None = None,
    apikey: str | None = None,
    request_kwargs: Mapping[str, Any] | None = None,
)
```

Behavior:

- `base_url` defaults to the subclass base URL
- `apikey` falls back to the subclass environment variable
- `request_kwargs` becomes per-provider default request options

## Reserved keys

`Provider.complete()` owns these request fields:

- `model`
- `messages`
- `stream`
- `tools`

They cannot be passed in either `request_kwargs` or per-call `run_kwargs`.
Doing so raises `TypeError`.

## Streaming call

```python
stream = await provider.complete(
    messages,
    tools=tool_schemas,
    reasoning_effort="medium",
)

async for chunk in stream:
    ...
```

`complete()` always performs a streaming chat-completions request. `Agent`
builds higher-level behavior on top of that stream.

## Environment variables

| Provider | Variable |
|----------|----------|
| `Provider` | `OPENAI_API_KEY` |
| `DeepSeek` | `DEEPSEEK_API_KEY` |
| `Ollama` | `OLLAMA_API_KEY` |
| `Vllm` | `VLLM_API_KEY` |
| `Sglang` | `SGLANG_API_KEY` |

## Notes

- `Provider` is intentionally stateless apart from its client config.
- It does not own conversation history. `Agent.messages` does.
- `run_kwargs` are where you pass model-specific options like temperature or
  reasoning knobs, as long as they are not reserved keys.
