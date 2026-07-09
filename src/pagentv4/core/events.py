from dataclasses import dataclass
from typing import Literal, TypeAlias

from .turn_result import TurnResult

StopReason = Literal[
    "continuing", "no_tool_calls", "empty_response", "max_turns", "cancelled"
]


@dataclass(frozen=True, slots=True)
class RunBegin:
    user_input: str


@dataclass(frozen=True, slots=True)
class RunEnd:
    turn: int
    stop_reason: StopReason


@dataclass(frozen=True, slots=True)
class TurnBegin:
    turn: int


@dataclass(frozen=True, slots=True)
class TurnEnd:
    """One model turn finished (assistant messages written to ``messages``)."""

    turn: int
    stopped: bool
    stop_reason: StopReason


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ReasoningDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ToolCallBegin:
    tool_call_id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool_call_id: str
    name: str
    content: str
    ok: bool = True


Event: TypeAlias = (
    RunBegin
    | RunEnd
    | TurnBegin
    | TextDelta
    | ReasoningDelta
    | TurnResult
    | ToolCallBegin
    | ToolResult
    | TurnEnd
)
