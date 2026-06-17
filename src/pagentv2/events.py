from dataclasses import dataclass
from typing import TypeAlias

from .turn_result import TurnResult


@dataclass(frozen=True, slots=True)
class RunBegin:
    user_input: str


@dataclass(frozen=True, slots=True)
class TurnBegin:
    turn: int


@dataclass(frozen=True, slots=True)
class TurnEnd:
    turn: int
    stopped: bool


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
    | TurnBegin
    | TextDelta
    | ReasoningDelta
    | TurnResult
    | ToolCallBegin
    | ToolResult
    | TurnEnd
)
