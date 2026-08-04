"""Semantic checkpoints — safe points for input injection and cancellation.

Checkpoints replace the old event-type-based polling with explicit, named
points in the agent loop.  Each checkpoint declares whether immediate input
and/or cancellation is allowed at that point.

Key invariants:
- Immediate input is NEVER applied mid-tool-batch (preserves ToolCall/Result pairing).
- Cancel can take effect at every checkpoint; unexecuted ToolCalls receive
  synthetic cancelled ToolResults.
- After RunEnd, no more steer is applied; remaining immediate inputs are
  returned to the InputQueue as deferred items.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .inbound import InputMessage, InputQueue

# ---------------------------------------------------------------------------
# CheckpointKind
# ---------------------------------------------------------------------------


class CheckpointKind(StrEnum):
    """Named checkpoints in the agent loop.

    These are declared by the loop itself (not inferred from outbound events).
    """

    RUN_STARTED = "run_started"
    BEFORE_MODEL = "before_model"
    AFTER_MODEL = "after_model"
    BEFORE_TOOL_BATCH = "before_tool_batch"
    AFTER_TOOL_BATCH = "after_tool_batch"
    BEFORE_FINALIZE = "before_finalize"


# ---------------------------------------------------------------------------
# Checkpoint rules
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CheckpointRule:
    """What is allowed at a given checkpoint."""

    allow_immediate: bool
    allow_cancel: bool


# The canonical checkpoint rules per the H3 spec
CHECKPOINT_RULES: dict[CheckpointKind, CheckpointRule] = {
    CheckpointKind.RUN_STARTED: CheckpointRule(
        allow_immediate=False, allow_cancel=True
    ),
    CheckpointKind.BEFORE_MODEL: CheckpointRule(
        allow_immediate=True, allow_cancel=True
    ),
    CheckpointKind.AFTER_MODEL: CheckpointRule(
        allow_immediate=False, allow_cancel=True
    ),
    CheckpointKind.BEFORE_TOOL_BATCH: CheckpointRule(
        allow_immediate=False, allow_cancel=True
    ),
    CheckpointKind.AFTER_TOOL_BATCH: CheckpointRule(
        allow_immediate=True, allow_cancel=True
    ),
    CheckpointKind.BEFORE_FINALIZE: CheckpointRule(
        allow_immediate=True, allow_cancel=True
    ),
}


def immediate_allowed_at(kind: CheckpointKind) -> bool:
    """Return True if immediate input may be applied at this checkpoint."""
    rule = CHECKPOINT_RULES.get(kind)
    return rule is not None and rule.allow_immediate


def cancel_allowed_at(kind: CheckpointKind) -> bool:
    """Return True if cancellation may take effect at this checkpoint."""
    rule = CHECKPOINT_RULES.get(kind)
    return rule is not None and rule.allow_cancel


# ---------------------------------------------------------------------------
# Checkpoint drain result
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CheckpointDrain:
    """Result of draining inbound events at a checkpoint.

    - ``applied_immediate``: texts that should be inserted as user messages
      into the active conversation.
    - ``cancelled``: whether the run should be cancelled.
    - ``deferred``: immediate inputs that arrived at an unsafe checkpoint
      and must be re-queued for the next checkpoint.
    - ``orphan_tool_ids``: tool_call_ids that need synthetic cancelled
      results because the run was cancelled mid-batch.
    """

    applied_immediate: list[str] = field(default_factory=list)
    cancelled: bool = False
    deferred: list[InputMessage] = field(default_factory=list)
    orphan_tool_ids: list[str] = field(default_factory=list)

    @property
    def has_immediate(self) -> bool:
        return bool(self.applied_immediate)

    @property
    def has_deferred(self) -> bool:
        return bool(self.deferred)


# ---------------------------------------------------------------------------
# InboundCheckpoint — the checkpoint-aware mailbox drainer
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class InboundCheckpoint:
    """Manages inbound events (immediate inputs + cancel requests) and
    drains them at semantic checkpoints.

    This replaces the old ``InboundMailbox`` + ``CheckpointPolicy``
    combination with explicit checkpoint semantics.

    Usage in the agent loop::

        ckp = InboundCheckpoint()
        loop:
            await ckp.checkpoint(RUN_STARTED)
            await ckp.checkpoint(BEFORE_MODEL)
            response = await model.call(...)
            await ckp.checkpoint(AFTER_MODEL)
            if response.has_tool_calls:
                await ckp.checkpoint(BEFORE_TOOL_BATCH)
                for tc in tool_calls:
                    if ckp.cancelled:
                        emit cancelled ToolResult for tc
                    else:
                        execute tc
                await ckp.checkpoint(AFTER_TOOL_BATCH)
                continue
            await ckp.checkpoint(BEFORE_FINALIZE)
            if ckp.has_pending_immediate:
                continue  # another turn
            break
    """

    # Pending immediate inputs (arrived at unsafe checkpoints)
    _pending_immediate: list[InputMessage] = field(default_factory=list)
    # Has cancel been requested?
    cancelled: bool = False
    # Tool call IDs that were pending when cancel arrived (need synthetic results)
    _pending_tool_ids: list[str] = field(default_factory=list)

    def submit_immediate(self, message: InputMessage) -> None:
        """Queue an immediate input for the next safe checkpoint."""
        self._pending_immediate.append(message)

    def request_cancel(self) -> None:
        """Request cancellation at the next checkpoint."""
        self.cancelled = True

    def begin_tool_batch(self, tool_call_ids: list[str]) -> None:
        """Record tool call IDs for orphan handling on cancel."""
        self._pending_tool_ids = list(tool_call_ids)

    def end_tool_batch(self) -> None:
        """Clear tool call tracking after successful execution."""
        self._pending_tool_ids.clear()

    def checkpoint(self, kind: CheckpointKind) -> CheckpointDrain:
        """Drain pending inbound events at the given checkpoint.

        Returns a ``CheckpointDrain`` describing what should happen next.
        The caller is responsible for applying the results (inserting user
        messages, cancelling the run, generating synthetic tool results).
        """
        result = CheckpointDrain()

        # Apply immediate inputs if allowed
        if immediate_allowed_at(kind) and self._pending_immediate:
            for msg in self._pending_immediate:
                result.applied_immediate.append(msg.text)
            self._pending_immediate.clear()

        # If immediate NOT allowed, inputs stay pending (deferred to next
        # safe checkpoint — they are NOT dropped).

        # Apply cancel if allowed
        if cancel_allowed_at(kind) and self.cancelled:
            result.cancelled = True
            # Any unexecuted tool calls become orphans
            result.orphan_tool_ids = list(self._pending_tool_ids)
            self._pending_tool_ids.clear()

        return result

    @property
    def has_pending_immediate(self) -> bool:
        """True if there are immediate inputs waiting for a safe checkpoint."""
        return bool(self._pending_immediate)

    def drain_after_run_end(self, queue: InputQueue) -> int:
        """Called after RunEnd: all unapplied immediate inputs are deferred
        and placed at the head of the input queue for the next Run.

        Returns the number of inputs deferred.
        """
        count = 0
        # Reverse so they appear in original order at queue head
        for msg in reversed(self._pending_immediate):
            queue.enqueue_head(msg)
            count += 1
        self._pending_immediate.clear()
        return count
