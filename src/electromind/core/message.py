from typing import Annotated, Literal, Union
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl, model_validator


class ImageUrl(BaseModel):
    """User input: remote image (exported as OpenAI image_url part)."""

    type: Literal["image_url"]
    url: str


class AudioUrl(BaseModel):
    """User input: remote audio + transcript fallback (see user_content_to_openai)."""

    type: Literal["audio_url"]
    url: HttpUrl
    text: str


class TextChunk(BaseModel):
    type: Literal["text"]
    text: str


class ToolCall(BaseModel):
    type: Literal["function"]
    id: str
    name: str
    arguments: str

    @classmethod
    def from_openai(cls, raw: dict) -> "ToolCall":
        fn = raw["function"]
        return cls(
            type="function",
            id=raw["id"],
            name=fn["name"],
            arguments=fn["arguments"],
        )

    def to_openai(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


class ToolResult(BaseModel):
    type: Literal["tool_result"]
    tool_call_id: str
    text: str


class ThinkingChunk(BaseModel):
    type: Literal["thinking"]
    text: str


# User-side input parts (one Message row = one chunk; merged on export).
UserChunk = Annotated[
    Union[TextChunk, ImageUrl, AudioUrl],
    Field(discriminator="type"),
]

# Model-side output parts (streaming may append many rows per API turn).
AssistantChunk = Annotated[
    Union[TextChunk, ThinkingChunk, ToolCall],
    Field(discriminator="type"),
]


class Message(BaseModel):
    message_id: str | None = None
    turn_id: int | None = None
    role: Literal["system", "user", "assistant", "tool"]
    content: Union[UserChunk, AssistantChunk, ToolResult]

    @model_validator(mode="after")
    def content_matches_role(self) -> "Message":
        # Union on content is wide; this ties each role to allowed chunk types.
        c = self.content
        if self.role == "system" and not isinstance(c, TextChunk):
            raise ValueError("system message must be text")
        if self.role == "user" and not isinstance(c, (TextChunk, ImageUrl, AudioUrl)):
            raise ValueError("user message must be text, image_url, or audio_url")
        if self.role == "assistant" and not isinstance(
            c, (TextChunk, ThinkingChunk, ToolCall)
        ):
            raise ValueError("assistant message must be text, thinking, or tool call")
        if self.role == "tool" and not isinstance(c, ToolResult):
            raise ValueError("tool message must be tool_result")
        if self.role == "system" and self.turn_id is None:
            self.turn_id = 0
        return self

    @classmethod
    def assistant(
        cls,
        content: dict,
        message_id: str | None = None,
        turn_id: int | None = None,
    ) -> "Message":
        # Low-level: caller picks chunk shape (text / thinking / function).
        # Agent streaming uses {"type": "text", ...} and {"type": "thinking", ...}.
        payload = {"role": "assistant", "content": content}
        if message_id is not None:
            payload["message_id"] = message_id
        if turn_id is not None:
            payload["turn_id"] = turn_id
        return cls.model_validate(payload)

    @classmethod
    def system(
        cls,
        text: str,
        message_id: str | None = None,
        turn_id: int | None = None,
    ) -> "Message":
        payload = {"role": "system", "content": {"type": "text", "text": text}}
        if message_id is not None:
            payload["message_id"] = message_id
        if turn_id is not None:
            payload["turn_id"] = turn_id
        return cls.model_validate(payload)

    @classmethod
    def user(
        cls,
        text: str,
        message_id: str | None = None,
        turn_id: int | None = None,
    ) -> "Message":
        payload = {"role": "user", "content": {"type": "text", "text": text}}
        if message_id is not None:
            payload["message_id"] = message_id
        if turn_id is not None:
            payload["turn_id"] = turn_id
        return cls.model_validate(payload)

    @classmethod
    def user_image(
        cls,
        url: str,
        message_id: str | None = None,
        turn_id: int | None = None,
    ) -> "Message":
        payload = {
            "role": "user",
            "content": ImageUrl(type="image_url", url=url),
        }
        if message_id is not None:
            payload["message_id"] = message_id
        if turn_id is not None:
            payload["turn_id"] = turn_id
        return cls.model_validate(payload)

    @classmethod
    def tool_result(
        cls,
        tool_call_id: str,
        text: str,
        message_id: str | None = None,
        turn_id: int | None = None,
    ) -> "Message":
        payload = {
            "role": "tool",
            "content": ToolResult(
                type="tool_result", tool_call_id=tool_call_id, text=text
            ),
        }
        if message_id is not None:
            payload["message_id"] = message_id
        if turn_id is not None:
            payload["turn_id"] = turn_id
        return cls.model_validate(payload)

    def __str__(self):
        short_id = self.message_id[:8] if self.message_id else "-"
        return (
            f"Message({short_id}, turn={self.turn_id}, "
            f"{self.role}, {describe_content(self.content)})"
        )


def user_part_to_openai(chunk: UserChunk) -> dict:
    if isinstance(chunk, TextChunk):
        return {"type": "text", "text": chunk.text}
    if isinstance(chunk, ImageUrl):
        return {"type": "image_url", "image_url": {"url": chunk.url}}
    if isinstance(chunk, AudioUrl):
        return {
            "type": "audio_url",
            "audio_url": {"url": str(chunk.url)},
        }
    raise TypeError(f"not a user content part: {chunk!r}")


def user_content_to_openai(chunks: list[UserChunk]) -> str | list[dict]:
    parts: list[dict] = []
    for chunk in chunks:
        parts.append(user_part_to_openai(chunk))
        if isinstance(chunk, AudioUrl):
            # TODO: Add a dedicated media parsing/adaptation layer. Our supported
            # media types and the media types accepted by OpenAI-compatible APIs
            # do not fully align yet, so this remains a fallback mapping for now.
            parts.append({"type": "text", "text": chunk.text})
    if len(parts) == 1 and parts[0]["type"] == "text":
        return parts[0]["text"]
    return parts


def reply_text(messages: list[Message]) -> str:
    return "".join(
        m.content.text
        for m in messages
        if m.role == "assistant" and isinstance(m.content, TextChunk)
    )


def compact_text(text: str, limit: int = 120) -> str:
    one_line = text.replace("\n", "\\n")
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 3] + "..."


def describe_content(content) -> str:
    if isinstance(content, TextChunk):
        return f"text, {compact_text(content.text)!r}"
    if isinstance(content, ThinkingChunk):
        return f"thinking, {compact_text(content.text)!r}"
    if isinstance(content, ImageUrl):
        return f"image_url, {content.url!r}"
    if isinstance(content, AudioUrl):
        return f"audio_url, {str(content.url)!r}, {compact_text(content.text)!r}"
    if isinstance(content, ToolCall):
        return (
            f"function, {content.id!r}, {content.name!r}, "
            f"{compact_text(content.arguments)!r}"
        )
    if isinstance(content, ToolResult):
        return f"tool_result, {content.tool_call_id!r}, {compact_text(content.text)!r}"
    return repr(content)


def can_merge_messages(current: Message, incoming: Message) -> bool:
    if current.role != "assistant" or incoming.role != "assistant":
        return False
    if current.turn_id != incoming.turn_id:
        return False

    current_content = current.content
    incoming_content = incoming.content

    if isinstance(current_content, TextChunk) and isinstance(
        incoming_content, TextChunk
    ):
        return True
    if isinstance(current_content, ThinkingChunk) and isinstance(
        incoming_content, ThinkingChunk
    ):
        return True
    return False


def next_message_id() -> str:
    return uuid4().hex


def repair_openai_tool_sequence(messages: list[dict]) -> list[dict]:
    """Drop incomplete tool-call rounds before sending Chat Completions requests.

    OpenAI-compatible APIs require every assistant message with tool_calls to be
    followed immediately by tool messages for each tool_call_id. A process can be
    interrupted after persisting the assistant tool call and before persisting the
    tool result; replaying that history would make the next request invalid.
    """
    repaired: list[dict] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.get("role") == "tool":
            index += 1
            continue

        tool_calls = message.get("tool_calls")
        if message.get("role") != "assistant" or not isinstance(tool_calls, list):
            repaired.append(message)
            index += 1
            continue

        expected_ids = [
            tool_call.get("id")
            for tool_call in tool_calls
            if isinstance(tool_call, dict) and isinstance(tool_call.get("id"), str)
        ]
        if not expected_ids:
            index += 1
            continue

        tool_messages: list[dict] = []
        seen_ids: set[str] = set()
        cursor = index + 1
        while cursor < len(messages) and messages[cursor].get("role") == "tool":
            tool_message = messages[cursor]
            tool_call_id = tool_message.get("tool_call_id")
            if isinstance(tool_call_id, str) and tool_call_id in expected_ids:
                if tool_call_id not in seen_ids:
                    tool_messages.append(tool_message)
                    seen_ids.add(tool_call_id)
            cursor += 1

        if len(seen_ids) == len(set(expected_ids)):
            repaired.append(message)
            repaired.extend(tool_messages)

        index = cursor

    return repaired


class Messages(BaseModel):
    data: list[Message] = Field(default_factory=list)

    def __iadd__(self, other: Message):
        # Streamed assistant text/thinking appends merge into the last row.
        if not self.data:
            if other.message_id is None:
                other.message_id = next_message_id()
            self.data.append(other)
            return self

        current = self.data[-1]
        if not can_merge_messages(current, other):
            if other.message_id is None:
                other.message_id = next_message_id()
            self.data.append(other)
            return self

        current_content = current.content
        incoming_content = other.content
        if isinstance(current_content, TextChunk) and isinstance(
            incoming_content, TextChunk
        ):
            current_content.text += incoming_content.text
            return self
        if isinstance(current_content, ThinkingChunk) and isinstance(
            incoming_content, ThinkingChunk
        ):
            current_content.text += incoming_content.text
        return self

    def max_turn_id(self) -> int:
        turn_ids = [
            message.turn_id for message in self.data if message.turn_id is not None
        ]
        if not turn_ids:
            return 0
        return max(turn_ids)

    def complete_orphan_tool_results(
        self, *, text: str = "已中断：任务结束，未返回结果"
    ) -> int:
        """为已持久化但缺少 tool 行的 assistant tool_call 补上占位结果。"""
        fulfilled = {
            message.content.tool_call_id
            for message in self.data
            if message.role == "tool" and isinstance(message.content, ToolResult)
        }
        added = 0
        for message in self.data:
            if message.role != "assistant":
                continue
            chunk = message.content
            if not isinstance(chunk, ToolCall):
                continue
            if chunk.id in fulfilled:
                continue
            result = Message.tool_result(chunk.id, text)
            if message.turn_id is not None:
                result.turn_id = message.turn_id
            self += result
            fulfilled.add(chunk.id)
            added += 1
        return added

    def __iter__(self):
        return iter(self.data)

    def __len__(self):
        return len(self.data)

    def __str__(self):
        if not self.data:
            return "Messages[]"

        lines = ["Messages["]
        for index, message in enumerate(self.data):
            lines.append(f"  {index}: {message}")
        lines.append("]")
        return "\n".join(lines)

    def save_to_jsonl(self, path):
        # P1.2: 原子写——崩溃 / 断电不留下半写的 messages.jsonl。
        from ..atomicfile import atomic_write_text

        atomic_write_text(
            path,
            "".join(f"{message.model_dump_json()}\n" for message in self.data),
            encoding="utf-8",
            backup=True,
        )

    @classmethod
    def load_from_jsonl(cls, path):
        # P1.3: 主文件损坏 → 尝试 .bak；单条损坏 fail-soft 跳过。
        from ..atomicfile import load_jsonl_recover

        parsed = load_jsonl_recover(
            path,
            parse_line=lambda raw: Message.model_validate_json(raw),
        )
        messages = cls()
        for message in parsed:
            messages += message
        return messages

    def to_openai(self) -> list[dict]:
        # Collapse many Message rows back into OpenAI chat message dicts.
        # 与 __iadd__ 的 append 合并分工不同：__iadd__ 只把同 turn 同类型的
        # 流式 delta（text/text、thinking/thinking）累积成一行（存储紧凑），
        # 这里则把任意 chunk 组合折叠成一条 OpenAI message（结构转换）。
        out: list[dict] = []
        i = 0
        data = self.data

        while i < len(data):
            msg = data[i]

            if msg.role == "system" and isinstance(msg.content, TextChunk):
                out.append({"role": "system", "content": msg.content.text})
                i += 1
                continue

            if msg.role == "user":
                chunks: list[UserChunk] = []
                while i < len(data) and data[i].role == "user":
                    chunk = data[i].content
                    if not isinstance(chunk, (TextChunk, ImageUrl, AudioUrl)):
                        raise ValueError(f"unsupported user chunk: {chunk!r}")
                    chunks.append(chunk)
                    i += 1
                out.append({"role": "user", "content": user_content_to_openai(chunks)})
                continue

            if msg.role == "tool" and isinstance(msg.content, ToolResult):
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.content.tool_call_id,
                        "content": msg.content.text,
                    }
                )
                i += 1
                continue

            if msg.role == "assistant":
                text_parts: list[str] = []
                reasoning_parts: list[str] = []
                tool_calls: list[dict] = []

                while i < len(data) and data[i].role == "assistant":
                    chunk = data[i].content
                    if isinstance(chunk, TextChunk):
                        text_parts.append(chunk.text)
                    elif isinstance(chunk, ThinkingChunk):
                        reasoning_parts.append(chunk.text)
                    elif isinstance(chunk, ToolCall):
                        tool_calls.append(
                            {
                                "id": chunk.id,
                                "type": "function",
                                "function": {
                                    "name": chunk.name,
                                    "arguments": chunk.arguments,
                                },
                            }
                        )
                    else:
                        raise ValueError(f"unsupported assistant chunk: {chunk!r}")
                    i += 1

                api_msg: dict = {"role": "assistant"}
                if text_parts:
                    api_msg["content"] = "".join(text_parts)
                elif tool_calls:
                    api_msg["content"] = None
                else:
                    # DeepSeek rejects content=null without tool_calls (reasoning-only turn).
                    api_msg["content"] = ""
                if tool_calls:
                    api_msg["tool_calls"] = tool_calls
                if reasoning_parts:
                    api_msg["reasoning_content"] = "".join(reasoning_parts)
                out.append(api_msg)
                continue

            raise ValueError(f"unsupported message: {msg!r}")

        return repair_openai_tool_sequence(out)
