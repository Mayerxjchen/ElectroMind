from dataclasses import dataclass, field

from .message import Message, TextChunk, ThinkingChunk, ToolCall


@dataclass(frozen=True, slots=True)
class TurnResult:
    """One model invocation: assembled content, reasoning, and tool calls."""

    content: str = ""
    tool_calls: list = field(default_factory=list)
    reasoning_content: str = ""

    @classmethod
    def from_slice(cls, messages: list[Message], start: int = 0) -> "TurnResult":
        content = "".join(
            m.content.text
            for m in messages[start:]
            if m.role == "assistant" and isinstance(m.content, TextChunk)
        )
        reasoning_content = "".join(
            m.content.text
            for m in messages[start:]
            if m.role == "assistant" and isinstance(m.content, ThinkingChunk)
        )
        tool_calls = [
            m.content.to_openai()
            for m in messages[start:]
            if m.role == "assistant" and isinstance(m.content, ToolCall)
        ]
        return cls(
            content=content,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
        )

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)
