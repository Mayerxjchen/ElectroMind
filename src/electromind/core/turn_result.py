from __future__ import annotations

from dataclasses import dataclass, field

from .message import Message, TextChunk, ThinkingChunk, ToolCall


def normalize_tool_call(value) -> ToolCall:
    if isinstance(value, ToolCall):
        return value
    if isinstance(value, dict) and "function" in value:
        return ToolCall.from_openai(value)
    return ToolCall.model_validate(value)


@dataclass(frozen=True, slots=True)
class TurnResult:
    """One model invocation: assembled content, reasoning, and tool calls."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning_content: str = ""
    usage: dict | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tool_calls",
            [normalize_tool_call(tool_call) for tool_call in self.tool_calls],
        )

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
        tool_calls: list[ToolCall] = [
            m.content
            for m in messages[start:]
            if m.role == "assistant" and isinstance(m.content, ToolCall)
        ]
        return cls(
            content=content,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
        )

    def with_usage(self, usage: dict | None) -> TurnResult:
        return TurnResult(
            content=self.content,
            tool_calls=self.tool_calls,
            reasoning_content=self.reasoning_content,
            usage=usage,
        )

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)
