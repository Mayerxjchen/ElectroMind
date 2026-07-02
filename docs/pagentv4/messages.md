# pagentv4 Messages

语言：[中文](/zh/pagentv4/messages) | [English](/pagentv4/messages)

`pagentv4` stores conversation state as typed `Message` objects rather than raw
OpenAI-shaped dicts.

## Roles and content types

| Role | Allowed content |
|------|-----------------|
| `system` | `TextChunk` |
| `user` | `TextChunk`, `ImageUrl`, `AudioUrl` |
| `assistant` | `TextChunk`, `ThinkingChunk`, `ToolCall` |
| `tool` | `ToolResult` |

The role/content pairing is validated in `Message`.

## Constructors

```python
from pagentv4 import Message

system = Message.system("You are helpful.")
user = Message.user("Describe this image.")
image = Message.user_image("https://example.com/cat.png")
tool = Message.tool_result("call_1", "ok")
```

Assistant messages are often created from streamed events:

```python
Message.assistant({"type": "text", "text": "hello"})
Message.assistant({"type": "thinking", "text": "let me think"})
```

## `Messages`

`Messages` is a thin wrapper around `list[Message]`:

```python
from pagentv4 import Message, Messages

msgs = Messages()
msgs += Message.system("You are concise.")
msgs += Message.user("Hello")
```

Useful methods:

- `len(msgs)`
- iteration over `Message`
- `msgs.to_openai()` to export provider payloads
- `msgs.save_to_jsonl(path)` / `Messages.load_from_jsonl(path)`

## Conversion to provider payloads

`Messages.to_openai()` performs a few important merges:

- consecutive `user` chunks become one OpenAI user message
- consecutive `assistant` chunks become one assistant message
- assistant `ThinkingChunk` values are joined into `reasoning_content`
- assistant `ToolCall` values are exported into `tool_calls`

## Multimedia

### Image

```python
from pagentv4 import ImageUrl, Message

msg = Message(role="user", content=ImageUrl(type="image_url", url="https://..."))
```

Exports to:

```python
{"type": "image_url", "image_url": {"url": "..."}}
```

### Audio

```python
from pagentv4 import AudioUrl, Message

msg = Message(
    role="user",
    content=AudioUrl(
        type="audio_url",
        url="https://example.com/voice.wav",
        text="transcribed text",
    ),
)
```

Current export is a fallback mapping:

- one media part for the remote audio URL
- one text part for the transcript

Media types supported by `pagentv4` and media types accepted by
OpenAI-compatible APIs do not fully align yet.
