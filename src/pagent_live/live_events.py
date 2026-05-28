"""Live Event types (same ``Event`` family as :mod:`pagent.events`; direction = owire / iwire)."""

from dataclasses import dataclass
from typing import TypeAlias

from pagent.events import Event as CoreEvent


@dataclass(frozen=True, slots=True)
class HumanInputRequired:
    """owire — rendezvous request (pair with :class:`HumanReply` on iwire)."""

    tool_call_id: str
    question: str


@dataclass(frozen=True, slots=True)
class HumanReply:
    """iwire — rendezvous reply."""

    tool_call_id: str
    text: str


@dataclass(frozen=True, slots=True)
class CancelRun:
    """iwire — control: abort current run."""

    pass


Event: TypeAlias = CoreEvent | HumanInputRequired | HumanReply | CancelRun
