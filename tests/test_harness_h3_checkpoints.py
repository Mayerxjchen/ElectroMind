"""H3: Semantic Checkpoint tests.

Verify checkpoint rules, immediate-only-at-safe-points, cancel semantics,
tool batch orphan handling, and post-RunEnd drain.
"""

from __future__ import annotations

import pytest

from electromind.harness.checkpoints import (
    CHECKPOINT_RULES,
    CheckpointKind,
    CheckpointRule,
    InboundCheckpoint,
    cancel_allowed_at,
    immediate_allowed_at,
)
from electromind.harness.inbound import InputDelivery, InputMessage, InputQueue

# ============================================================================
# Checkpoint kinds
# ============================================================================


def test_all_six_checkpoint_kinds_exist():
    kinds = set(CheckpointKind)
    assert kinds == {
        CheckpointKind.RUN_STARTED,
        CheckpointKind.BEFORE_MODEL,
        CheckpointKind.AFTER_MODEL,
        CheckpointKind.BEFORE_TOOL_BATCH,
        CheckpointKind.AFTER_TOOL_BATCH,
        CheckpointKind.BEFORE_FINALIZE,
    }


# ============================================================================
# Checkpoint rules — immediate
# ============================================================================


@pytest.mark.parametrize(
    "kind",
    [
        CheckpointKind.BEFORE_MODEL,
        CheckpointKind.AFTER_TOOL_BATCH,
        CheckpointKind.BEFORE_FINALIZE,
    ],
)
def test_immediate_allowed_at_safe_checkpoints(kind):
    """Immediate input is allowed at BEFORE_MODEL, AFTER_TOOL_BATCH,
    and BEFORE_FINALIZE (per spec). RUN_STARTED does NOT allow immediate —
    the Run must be fully initialized before steer can be applied."""
    assert immediate_allowed_at(kind), f"Immediate input must be allowed at {kind}"


@pytest.mark.parametrize(
    "kind",
    [
        CheckpointKind.AFTER_MODEL,
        CheckpointKind.BEFORE_TOOL_BATCH,
    ],
)
def test_immediate_forbidden_during_tool_batch_boundary(kind):
    """Immediate input must NOT be applied at AFTER_MODEL or
    BEFORE_TOOL_BATCH — these guard tool batch integrity."""
    assert not immediate_allowed_at(kind), (
        f"Immediate input must NOT be allowed at {kind} (tool batch boundary)"
    )


def test_immediate_forbidden_at_run_started():
    """RUN_STARTED does not allow immediate — the Run must fully initialize
    before user steer can be applied."""
    assert not immediate_allowed_at(CheckpointKind.RUN_STARTED), (
        "Immediate must NOT be allowed at RUN_STARTED"
    )


# ============================================================================
# Checkpoint rules — cancel
# ============================================================================


def test_cancel_allowed_at_every_checkpoint():
    """Cancel must be allowed at ALL checkpoints."""
    for kind in CheckpointKind:
        assert cancel_allowed_at(kind), f"Cancel must be allowed at {kind}"


# ============================================================================
# Checkpoint rule table completeness
# ============================================================================


def test_every_checkpoint_has_a_rule():
    """Every CheckpointKind must have an entry in CHECKPOINT_RULES."""
    for kind in CheckpointKind:
        assert kind in CHECKPOINT_RULES, f"Missing rule for {kind}"
        assert isinstance(CHECKPOINT_RULES[kind], CheckpointRule)


# ============================================================================
# InboundCheckpoint — immediate application
# ============================================================================


def test_immediate_applied_at_safe_checkpoint():
    ckp = InboundCheckpoint()
    msg = InputMessage.create("t", "steer text", delivery=InputDelivery.IMMEDIATE)
    ckp.submit_immediate(msg)

    drain = ckp.checkpoint(CheckpointKind.BEFORE_MODEL)
    assert drain.has_immediate
    assert drain.applied_immediate == ["steer text"]
    assert not drain.cancelled
    assert not ckp.has_pending_immediate


def test_immediate_deferred_at_unsafe_checkpoint():
    """At AFTER_MODEL, immediate input is NOT applied — it stays pending."""
    ckp = InboundCheckpoint()
    msg = InputMessage.create("t", "wait", delivery=InputDelivery.IMMEDIATE)
    ckp.submit_immediate(msg)

    drain = ckp.checkpoint(CheckpointKind.AFTER_MODEL)
    assert not drain.has_immediate  # Not applied
    assert not drain.cancelled
    assert ckp.has_pending_immediate  # Still pending

    # At next safe checkpoint, it gets applied
    drain2 = ckp.checkpoint(CheckpointKind.BEFORE_FINALIZE)
    assert drain2.has_immediate
    assert drain2.applied_immediate == ["wait"]
    assert not ckp.has_pending_immediate


def test_multiple_immediate_inputs_batched():
    """Multiple immediate inputs submitted between checkpoints are all
    applied at the next safe checkpoint."""
    ckp = InboundCheckpoint()
    ckp.submit_immediate(InputMessage.create("t", "first"))
    ckp.submit_immediate(InputMessage.create("t", "second"))
    ckp.submit_immediate(InputMessage.create("t", "third"))

    drain = ckp.checkpoint(CheckpointKind.BEFORE_MODEL)
    assert drain.applied_immediate == ["first", "second", "third"]


# ============================================================================
# InboundCheckpoint — cancel
# ============================================================================


def test_cancel_applied_at_checkpoint():
    ckp = InboundCheckpoint()
    ckp.request_cancel()

    drain = ckp.checkpoint(CheckpointKind.RUN_STARTED)
    assert drain.cancelled


def test_cancel_produces_orphan_tool_ids():
    """When cancel hits mid-tool-batch, unexecuted tools become orphans."""
    ckp = InboundCheckpoint()
    ckp.begin_tool_batch(["tc-1", "tc-2", "tc-3"])
    # Execute tc-1, then cancel arrives
    ckp.request_cancel()

    drain = ckp.checkpoint(CheckpointKind.BEFORE_TOOL_BATCH)
    assert drain.cancelled
    assert drain.orphan_tool_ids == ["tc-1", "tc-2", "tc-3"]


def test_cancel_without_pending_tools_has_no_orphans():
    ckp = InboundCheckpoint()
    ckp.request_cancel()
    drain = ckp.checkpoint(CheckpointKind.RUN_STARTED)
    assert drain.cancelled
    assert drain.orphan_tool_ids == []


def test_end_tool_batch_clears_orphan_tracking():
    ckp = InboundCheckpoint()
    ckp.begin_tool_batch(["tc-1"])
    ckp.end_tool_batch()
    # Now cancel — no orphans because batch completed
    ckp.request_cancel()
    drain = ckp.checkpoint(CheckpointKind.AFTER_TOOL_BATCH)
    assert drain.orphan_tool_ids == []


# ============================================================================
# Cancel + immediate interaction
# ============================================================================


def test_cancel_and_immediate_at_same_checkpoint():
    """If both cancel and immediate are pending, both are drained."""
    ckp = InboundCheckpoint()
    ckp.submit_immediate(InputMessage.create("t", "final steer"))
    ckp.request_cancel()

    drain = ckp.checkpoint(CheckpointKind.BEFORE_MODEL)
    assert drain.has_immediate
    assert drain.applied_immediate == ["final steer"]
    assert drain.cancelled


# ============================================================================
# Tool batch integrity: no immediate mid-batch
# ============================================================================


def test_tool_batch_integrity_no_immediate_between_tool_calls():
    """Simulate: model returns 3 tool calls. User sends immediate after
    first tool result. The immediate must NOT be applied mid-batch —
    only after all 3 tools complete."""
    ckp = InboundCheckpoint()

    # BEFORE_TOOL_BATCH checkpoint
    ckp.begin_tool_batch(["tc-a", "tc-b", "tc-c"])
    drain1 = ckp.checkpoint(CheckpointKind.BEFORE_TOOL_BATCH)
    assert not drain1.cancelled

    # Execute tc-a (success)
    # User sends immediate after tc-a result
    ckp.submit_immediate(InputMessage.create("t", "stop after this"))

    # BEFORE_TOOL_BATCH is checked before each tool? No — the batch is
    # bracketed by BEFORE_TOOL_BATCH/AFTER_TOOL_BATCH. Mid-batch there
    # is no checkpoint, so the immediate stays pending.
    # After tc-b and tc-c complete:
    ckp.end_tool_batch()
    drain2 = ckp.checkpoint(CheckpointKind.AFTER_TOOL_BATCH)
    assert drain2.has_immediate
    assert drain2.applied_immediate == ["stop after this"]
    assert not drain2.cancelled


# ============================================================================
# Post-RunEnd drain
# ============================================================================


def test_drain_after_run_end_defers_to_queue_head():
    """Unapplied immediate inputs after RunEnd are deferred to the queue
    head for the next Run."""
    ckp = InboundCheckpoint()
    ckp.submit_immediate(InputMessage.create("t", "msg-1"))
    ckp.submit_immediate(InputMessage.create("t", "msg-2"))

    q = InputQueue()
    q.enqueue(InputMessage.create("t", "queued-already"))

    count = ckp.drain_after_run_end(q)
    assert count == 2
    assert not ckp.has_pending_immediate

    # Deferred inputs appear at queue head, in original order
    assert q.dequeue().text == "msg-1"
    assert q.dequeue().text == "msg-2"
    assert q.dequeue().text == "queued-already"
    assert q.dequeue() is None


def test_drain_after_run_end_empty_queue():
    ckp = InboundCheckpoint()
    q = InputQueue()
    count = ckp.drain_after_run_end(q)
    assert count == 0


# ============================================================================
# Complete Run lifecycle simulation
# ============================================================================


def test_full_run_lifecycle_with_immediate_and_cancel():
    """Simulate a complete Run with checkpoints, an immediate input, and
    a cancel."""
    ckp = InboundCheckpoint()
    q = InputQueue()

    # RUN_STARTED
    drain = ckp.checkpoint(CheckpointKind.RUN_STARTED)
    assert not drain.cancelled

    # User sends immediate mid-run
    ckp.submit_immediate(InputMessage.create("t", "check this"))

    # BEFORE_MODEL — immediate applied
    drain = ckp.checkpoint(CheckpointKind.BEFORE_MODEL)
    assert drain.applied_immediate == ["check this"]

    # Model returns tool calls
    ckp.begin_tool_batch(["tc-1", "tc-2"])
    drain = ckp.checkpoint(CheckpointKind.BEFORE_TOOL_BATCH)
    assert not drain.cancelled

    # User requests cancel after tc-1
    ckp.request_cancel()

    # BEFORE_TOOL_BATCH (for remaining tools): cancel + orphans
    drain = ckp.checkpoint(CheckpointKind.BEFORE_TOOL_BATCH)
    assert drain.cancelled
    assert drain.orphan_tool_ids == ["tc-1", "tc-2"]

    # BEFORE_FINALIZE with unapplied immediate
    ckp.submit_immediate(InputMessage.create("t", "too late"))
    ckp.drain_after_run_end(q)

    assert q.dequeue().text == "too late"
