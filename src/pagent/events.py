"""Agent loop events for UI / Wire-style consumers.

See ``docs/events.md`` (English) or ``docs/events.zh-CN.md`` (中文).

Emitted by :meth:`~pagent.agent.Agent.arun_events`; serialized to JSON-RPC
NDJSON by :meth:`~pagent.agent.Agent.arun_wire` / :mod:`pagent.wire` for
non-Python consumers. See ``docs/events.md`` and ``docs/wire.md``.
"""

from dataclasses import dataclass
from typing import TypeAlias

from .llm import RunEnd

# --- lifecycle ---


@dataclass(frozen=True, slots=True)
class RunBegin:
    """User turn accepted; ``session`` already has the user message."""

    user_input: str


@dataclass(frozen=True, slots=True)
class TurnBegin:
    """Start of one model invocation inside ``max_turns``."""

    turn: int


@dataclass(frozen=True, slots=True)
class TurnEnd:
    """One model invocation finished (assistant message written to session)."""

    turn: int
    stopped: bool


# --- streaming deltas ---


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ReasoningDelta:
    text: str


# --- step boundary (assembled stream or single ``invoke``) ---


@dataclass(frozen=True, slots=True)
class StepEnd:
    """LLM step complete; same fields as :class:`~pagent.llm.RunEnd`."""

    content: str
    tool_calls: list
    reasoning_content: str
    usage: object | None = None


# --- tools ---


@dataclass(frozen=True, slots=True)
class ToolCallBegin:
    """About to run one tool from the assistant ``tool_calls`` list."""

    tool_call_id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Tool output appended to ``session``."""

    tool_call_id: str
    name: str
    content: str


Event: TypeAlias = (
    RunBegin
    | TurnBegin
    | TextDelta
    | ReasoningDelta
    | StepEnd
    | ToolCallBegin
    | ToolResult
    | TurnEnd
    | RunEnd
)
