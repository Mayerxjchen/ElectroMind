# pagentv4 消息

语言：[中文](/zh/pagentv4/messages) | [English](/pagentv4/messages)

`pagentv4` 用类型化 `Message` 对象保存对话状态，而不是原始 OpenAI dict。

## 角色与内容类型

| 角色 | 允许的内容 |
|------|------------|
| `system` | `TextChunk` |
| `user` | `TextChunk`, `ImageUrl`, `AudioUrl` |
| `assistant` | `TextChunk`, `ThinkingChunk`, `ToolCall` |
| `tool` | `ToolResult` |

`Message` 会校验 role/content 配对。

## 构造方法

```python
from pagentv4 import Message

system = Message.system("你是简洁助手。")
user = Message.user("描述这张图片。")
image = Message.user_image("https://example.com/cat.png")
tool = Message.tool_result("call_1", "ok")
```

Assistant 消息常由流式事件创建：

```python
Message.assistant({"type": "text", "text": "hello"})
Message.assistant({"type": "thinking", "text": "让我想想"})
```

## `Messages`

`Messages` 是对 `list[Message]` 的轻量包装：

```python
from pagentv4 import Message, Messages

msgs = Messages()
msgs += Message.system("回答要简洁。")
msgs += Message.user("你好")
```

常用方法：

- `len(msgs)`
- 迭代 `Message`
- `msgs.to_openai()` 导出 provider 载荷
- `msgs.save_to_jsonl(path)` / `Messages.load_from_jsonl(path)`

## 转为 provider 载荷

`Messages.to_openai()` 会做几项重要合并：

- 连续 `user` chunk 合并成一条 OpenAI user 消息
- 连续 `assistant` chunk 合并成一条 assistant 消息
- assistant 的 `ThinkingChunk` 拼成 `reasoning_content`
- assistant 的 `ToolCall` 导出为 `tool_calls`

## 多媒体

### 图片

```python
from pagentv4 import ImageUrl, Message

msg = Message(role="user", content=ImageUrl(type="image_url", url="https://..."))
```

导出为：

```python
{"type": "image_url", "image_url": {"url": "..."}}
```

### 音频

```python
from pagentv4 import AudioUrl, Message

msg = Message(
    role="user",
    content=AudioUrl(
        type="audio_url",
        url="https://example.com/voice.wav",
        text="转写文本",
    ),
)
```

当前导出为兜底映射：

- 远程音频 URL 一个 media part
- 转写文本一个 text part

`pagentv4` 支持的媒体类型与 OpenAI 兼容 API 接受的类型尚未完全对齐。
