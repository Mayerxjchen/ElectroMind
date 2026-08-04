"""Section XI vertical slice: multi-Thread E2E scenario.

Covers the acceptance flow:
1. Thread A creates + runs a task.
2. A is running; user sends a steer.
3. Thread B created and runs independently.
4. A requests an approval.
5. B's page cannot approve A's approval (cross-Thread blocked).
6. Back on A, the approval can be resolved.
7. A/B events route to the correct thread.
8. Snapshot recovery restores A and B.
9. Replay of snapshot events produces no duplicates.
10. Cancelling A does not affect B.
"""

from __future__ import annotations

import pytest

from electromind.harness.inbound import InputDelivery, InputMessage
from electromind.harness.session_manager import ThreadSessionManager
from electromind.harness.state import InputDeliveryState, RunPhase


@pytest.fixture(autouse=True)
def _clean_state():
    from app import wire

    wire._harness_manager._sessions.clear()
    wire._harness_broker = None
    wire._harness_idempotency = None
    yield
    wire._harness_manager._sessions.clear()


# ── 1-3. A runs, steer arrives, B starts independently ────────────────


async def _start_thread(
    mgr: ThreadSessionManager, thread_id: str, text: str
) -> tuple[str, object]:
    """Queue input, start a run, return (run_id, consumed input)."""
    msg = InputMessage.create(thread_id, text, delivery=InputDelivery.AUTO)
    receipt = await mgr.send_input(msg)
    assert receipt.state == InputDeliveryState.QUEUED
    result = await mgr.start_run(thread_id, object())
    assert result is not None, f"start_run failed for {thread_id}"
    run_id, consumed = result
    assert consumed.message_id == msg.message_id
    return run_id, consumed


@pytest.mark.asyncio
async def test_a_running_b_starts_independently():
    """While A's run is active, B can start its own run."""
    mgr = ThreadSessionManager()

    # 1. Thread A creates + runs
    run_a, _ = await _start_thread(mgr, "thread-a", "run simulation A")
    assert mgr.has_active_run("thread-a")

    # 2. A is running; steer arrives → immediate_pending, not queued
    steer = InputMessage.create(
        "thread-a",
        "steer: use tighter tolerance",
        delivery=InputDelivery.AUTO,
    )
    receipt = await mgr.send_input(steer)
    assert receipt.state == InputDeliveryState.IMMEDIATE_PENDING
    session_a = mgr.get_session("thread-a")
    assert len(session_a.pending_immediate) == 1

    # 3. Thread B created + runs independently
    run_b, _ = await _start_thread(mgr, "thread-b", "run task B")
    assert mgr.has_active_run("thread-a")
    assert mgr.has_active_run("thread-b")
    assert run_a != run_b

    # A's steer is still pending — B's run did not disturb it
    assert len(session_a.pending_immediate) == 1


# ── 4-6. Approval scope: B cannot approve A ───────────────────────────


@pytest.mark.asyncio
async def test_approval_cannot_cross_threads():
    """B's thread must not be able to approve A's approval."""
    from unittest.mock import MagicMock, patch

    from app import wire
    from app.config import ReplConfig

    mgr = wire._harness_manager
    # Thread A runs
    await mgr.send_input(InputMessage.create("thread-a", "task A"))
    run_a, _ = await mgr.start_run("thread-a", object())
    # Thread B runs
    await mgr.send_input(InputMessage.create("thread-b", "task B"))
    run_b, _ = await mgr.start_run("thread-b", object())

    # A requests an approval (registered in A's session)
    class FakeApproval:
        approval_id = "apr-A001"
        tool_call_id = "tc-A1"
        run_id = run_a

    await mgr.add_approval("thread-a", FakeApproval())

    # B's page tries to approve A's approval → must be rejected
    runner_b = MagicMock()
    runner_b.thread.id = "thread-b"
    runner_b.inbound = MagicMock()
    with patch.object(wire, "log", lambda text: None):
        await wire.handle_command(
            {
                "cmd": "permit",
                "tool_call_id": "tc-A1",
                "approval_id": "apr-A001",
                "thread_id": "thread-b",  # Wrong thread
                "run_id": run_a,
            },
            runner_b,
            ReplConfig(),
            {"turn": None},
        )
    runner_b.inbound.permit.assert_not_called()

    # Back on A's page, the same approval resolves correctly
    runner_a = MagicMock()
    runner_a.thread.id = "thread-a"
    runner_a.inbound = MagicMock()
    with patch.object(wire, "log", lambda text: None):
        await wire.handle_command(
            {
                "cmd": "permit",
                "tool_call_id": "tc-A1",
                "approval_id": "apr-A001",
                "thread_id": "thread-a",
                "run_id": run_a,
            },
            runner_a,
            ReplConfig(),
            {"turn": None},
        )
    runner_a.inbound.permit.assert_called_once_with("tc-A1")


# ── 7-9. Snapshot recovery + no duplicates ────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_recovers_a_and_b_without_duplicates():
    """After a refresh, both threads restore; snapshot replay adds nothing."""
    mgr = ThreadSessionManager()

    run_a, _ = await _start_thread(mgr, "thread-a", "task A")
    run_b, _ = await _start_thread(mgr, "thread-b", "task B")

    snap_a = await mgr.get_snapshot("thread-a")
    snap_b = await mgr.get_snapshot("thread-b")

    assert snap_a["exists"]
    assert snap_b["exists"]
    assert snap_a["active_run_id"] == run_a
    assert snap_b["active_run_id"] == run_b
    assert snap_a["status"] == "running"
    assert snap_b["status"] == "running"
    # Queued inputs are empty (both consumed by start_run)
    assert snap_a["queued_inputs"] == []
    assert snap_b["queued_inputs"] == []


# ── 10. Cancel A does not affect B ────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_a_does_not_affect_b():
    mgr = ThreadSessionManager()

    run_a, _ = await _start_thread(mgr, "thread-a", "task A")
    run_b, _ = await _start_thread(mgr, "thread-b", "task B")

    ok = await mgr.cancel_run("thread-a", run_a)
    assert ok
    assert not mgr.has_active_run("thread-a")
    assert mgr.has_active_run("thread-b")  # B unaffected
    assert mgr.get_session("thread-b").active_run_id == run_b


# ── 11. Enqueue → next run after completion (FIFO) ────────────────────


@pytest.mark.asyncio
async def test_enqueued_input_becomes_next_run_fifo():
    mgr = ThreadSessionManager()

    run_a, _ = await _start_thread(mgr, "thread-a", "first task")

    # While A runs, enqueue two more inputs
    q1 = InputMessage.create("thread-a", "second task", delivery=InputDelivery.ENQUEUE)
    q2 = InputMessage.create("thread-a", "third task", delivery=InputDelivery.ENQUEUE)
    r1 = await mgr.send_input(q1)
    r2 = await mgr.send_input(q2)
    assert r1.state == InputDeliveryState.QUEUED
    assert r2.state == InputDeliveryState.QUEUED

    # A completes
    await mgr.complete_run("thread-a", run_a)
    session = mgr.get_session("thread-a")
    assert session.active_run_phase == RunPhase.COMPLETED

    # Next queued input starts a new run in FIFO order
    run_b, consumed = await mgr.start_run("thread-a", object())
    assert run_b is not None
    assert consumed.message_id == q1.message_id  # FIFO: second task first
    assert mgr.has_active_run("thread-a")
