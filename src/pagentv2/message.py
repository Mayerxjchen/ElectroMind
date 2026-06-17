from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, HttpUrl, model_validator


class ImageUrl(BaseModel):
    type: Literal["image_url"]
    url: str


class AudioUrl(BaseModel):
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


UserChunk = Annotated[
    Union[TextChunk, ImageUrl, AudioUrl],
    Field(discriminator="type"),
]

AssistantChunk = Annotated[
    Union[TextChunk, ThinkingChunk, ToolCall],
    Field(discriminator="type"),
]


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Union[UserChunk, AssistantChunk, ToolResult]

    @model_validator(mode="after")
    def content_matches_role(self) -> "Message":
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
        return self

    @classmethod
    def assistant(cls, content: dict) -> "Message":
        return cls.model_validate({"role": "assistant", "content": content})

    @classmethod
    def system(cls, text: str) -> "Message":
        return cls.model_validate(
            {"role": "system", "content": {"type": "text", "text": text}}
        )

    @classmethod
    def user(cls, text: str) -> "Message":
        return cls.model_validate(
            {"role": "user", "content": {"type": "text", "text": text}}
        )

    @classmethod
    def user_image(cls, url: str) -> "Message":
        return cls(role="user", content=ImageUrl(type="image_url", url=url))

    @classmethod
    def tool_result(cls, tool_call_id: str, text: str) -> "Message":
        return cls(
            role="tool",
            content=ToolResult(
                type="tool_result", tool_call_id=tool_call_id, text=text
            ),
        )


def user_part_to_openai(chunk: UserChunk) -> dict:
    if isinstance(chunk, TextChunk):
        return {"type": "text", "text": chunk.text}
    if isinstance(chunk, ImageUrl):
        return {"type": "image_url", "image_url": {"url": chunk.url}}
    if isinstance(chunk, AudioUrl):
        return {
            "type": "input_audio",
            "input_audio": {"data": str(chunk.url), "format": "wav"},
        }
    raise TypeError(f"not a user content part: {chunk!r}")


def user_content_to_openai(chunks: list[UserChunk]) -> str | list[dict]:
    parts = [user_part_to_openai(c) for c in chunks]
    if len(parts) == 1 and parts[0]["type"] == "text":
        return parts[0]["text"]
    return parts


def reply_text(messages: list[Message]) -> str:
    return "".join(
        m.content.text
        for m in messages
        if m.role == "assistant" and isinstance(m.content, TextChunk)
    )


class Messages(BaseModel):
    data: list[Message] = Field(default_factory=list)

    def __iadd__(self, other: Message):
        self.data.append(other)
        return self

    def __iter__(self):
        return iter(self.data)

    def __len__(self):
        return len(self.data)

    def to_openai(self) -> list[dict]:
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
                else:
                    api_msg["content"] = None
                if tool_calls:
                    api_msg["tool_calls"] = tool_calls
                if reasoning_parts:
                    api_msg["reasoning_content"] = "".join(reasoning_parts)
                out.append(api_msg)
                continue

            raise ValueError(f"unsupported message: {msg!r}")

        return out
