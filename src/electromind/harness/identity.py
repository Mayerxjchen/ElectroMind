"""Harness identity types — strongly-typed IDs, RunSnapshot, and WorkspaceKey.

Every ID is a ``NewType`` over ``str`` with a constructor that validates
non-emptiness and a canonical prefix.  This gives us type-safety at zero
runtime cost while keeping JSON serialisation trivial.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import NewType

from .state import (
    ExecutionTargetSnapshot,
    PermissionPolicySnapshot,
    SessionMode,
)

# ---------------------------------------------------------------------------
# ID types (NewType over str — zero-overhead, JSON-transparent)
# ---------------------------------------------------------------------------

ThreadId = NewType("ThreadId", str)
RunId = NewType("RunId", str)
MessageId = NewType("MessageId", str)
ItemId = NewType("ItemId", str)
EventId = NewType("EventId", str)
ApprovalId = NewType("ApprovalId", str)
RequestId = NewType("RequestId", str)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _check_nonempty(value: str, label: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{label} must not be empty")


def _check_prefix(value: str, prefix: str, label: str) -> None:
    if not value.startswith(prefix):
        raise ValueError(f"{label} must start with {prefix!r}, got {value!r}")


def validate_thread_id(value: str) -> ThreadId:
    """Validate and return a ``ThreadId``."""
    _check_nonempty(value, "thread_id")
    return ThreadId(value)


def validate_run_id(value: str) -> RunId:
    """Validate and return a ``RunId`` (prefix ``run-``)."""
    _check_nonempty(value, "run_id")
    _check_prefix(value, "run-", "run_id")
    return RunId(value)


def validate_message_id(value: str) -> MessageId:
    """Validate and return a ``MessageId`` (prefix ``msg-``)."""
    _check_nonempty(value, "message_id")
    _check_prefix(value, "msg-", "message_id")
    return MessageId(value)


def validate_item_id(value: str) -> ItemId:
    """Validate and return an ``ItemId`` (prefix ``item-``)."""
    _check_nonempty(value, "item_id")
    _check_prefix(value, "item-", "item_id")
    return ItemId(value)


def validate_event_id(value: str) -> EventId:
    """Validate and return an ``EventId`` (prefix ``evt-``)."""
    _check_nonempty(value, "event_id")
    _check_prefix(value, "evt-", "event_id")
    return EventId(value)


def validate_approval_id(value: str) -> ApprovalId:
    """Validate and return an ``ApprovalId`` (prefix ``apr-``)."""
    _check_nonempty(value, "approval_id")
    _check_prefix(value, "apr-", "approval_id")
    return ApprovalId(value)


def validate_request_id(value: str) -> RequestId:
    """Validate and return a ``RequestId`` (prefix ``req-``)."""
    _check_nonempty(value, "request_id")
    _check_prefix(value, "req-", "request_id")
    return RequestId(value)


# ---------------------------------------------------------------------------
# Factory functions (generate canonical IDs with UUIDv4)
# ---------------------------------------------------------------------------


def _make_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def new_run_id() -> RunId:
    return RunId(_make_id("run-"))


def new_message_id() -> MessageId:
    return MessageId(_make_id("msg-"))


def new_item_id() -> ItemId:
    return ItemId(_make_id("item-"))


def new_event_id() -> EventId:
    return EventId(_make_id("evt-"))


def new_approval_id() -> ApprovalId:
    return ApprovalId(_make_id("apr-"))


def new_request_id() -> RequestId:
    return RequestId(_make_id("req-"))


# ---------------------------------------------------------------------------
# RunSnapshot — immutable capture of everything that defines a Run
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    """Frozen snapshot of a Run's configuration at creation time.

    Once a Run starts, none of these fields may change.  Setting changes
    only affect subsequent Runs.
    """

    run_id: str
    thread_id: str
    input_message_id: str

    session_mode: SessionMode
    model: str
    max_iterations: int

    execution_target: ExecutionTargetSnapshot
    permission_policy: PermissionPolicySnapshot
    project_path: str

    system_prompt_digest: str
    skill_set_digest: str
    tool_set_digest: str

    created_at: str  # ISO 8601


# ---------------------------------------------------------------------------
# WorkspaceKey — identifies a writable namespace for lease acquisition
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorkspaceKey:
    """Uniquely identifies an execution target + workspace combination.

    Two Runs that share the same ``WorkspaceKey`` contend for the write
    lease.  Read-only Runs (ask / plan) do not acquire the lease.

    Examples::

        local:/Users/alice/project
        container:abc123:/workspace
        ssh:myhost:/remote/home/alice/work
    """

    execution_target_id: str
    canonical_workdir: str

    def __str__(self) -> str:
        return f"{self.execution_target_id}:{self.canonical_workdir}"
