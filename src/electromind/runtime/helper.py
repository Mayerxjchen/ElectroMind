from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from ..adapters.acp import encode_event_line
from ..core.events import ReasoningDelta, TextDelta, ToolCallBegin, ToolResult
from ..core.message import Message, Messages, TextChunk, ThinkingChunk, ToolCall

ArunReturnType = Literal["event", "text", "acp", "message"]

EventHandler = Callable[[Any], Awaitable[None] | None]


def append_message(messages: Messages, message: Message, turn_id: int | None) -> None:
    if message.turn_id is None and message.role != "system":
        message.turn_id = turn_id
    messages += message


def ensure_system(messages: Messages, system: str | None) -> None:
    if system is None:
        return
    if any(message.role == "system" for message in messages):
        return
    append_message(messages, Message.system(system), turn_id=0)


def message_to_event(message: Message):
    chunk = message.content
    if isinstance(chunk, TextChunk):
        return TextDelta(chunk.text)
    if isinstance(chunk, ThinkingChunk):
        return ReasoningDelta(chunk.text)
    return None


def project_event(event, return_type: ArunReturnType):
    if return_type == "event":
        return event
    if return_type == "text":
        if not isinstance(event, TextDelta):
            return None
        return event.text
    if return_type == "acp":
        return encode_event_line(event)
    if return_type == "message":
        if isinstance(event, TextDelta):
            return Message.assistant({"type": "text", "text": event.text})
        if isinstance(event, ReasoningDelta):
            return Message.assistant({"type": "thinking", "text": event.text})
        if isinstance(event, ToolCallBegin):
            return Message(
                role="assistant",
                content=ToolCall(
                    type="function",
                    id=event.tool_call_id,
                    name=event.name,
                    arguments=event.arguments,
                ),
            )
        if isinstance(event, ToolResult):
            return Message.tool_result(event.tool_call_id, event.content)
        return None
    raise ValueError(f"unknown return_type: {return_type!r}")
