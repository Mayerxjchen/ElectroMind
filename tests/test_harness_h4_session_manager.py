"""H4: ThreadSessionManager tests.

Verify one-Run-per-Thread, multi-Thread parallel, lazy Runner creation,
thread-switching independence, idle TTL, input routing, and snapshot.
"""

from __future__ import annotations

import asyncio

import pytest

from electromind.harness.inbound import InputDelivery, InputMessage
from electromind.harness.session_manager import ThreadSession, ThreadSessionManager
from electromind.harness.state import InputDeliveryState, RunPhase


def test_thread_session_initial_state():
    ts = ThreadSession(thread_id="thread-a")
    assert ts.thread_id == "thread-a"
    assert ts.runner is None
    assert ts.active_run_id is None
    assert ts.active_run_phase == RunPhase.DORMANT
    assert ts.status == "dormant"
    assert len(ts.queued_inputs) == 0
    assert len(ts.pending_approvals) == 0


def test_thread_session_next_seq_monotonic():
    ts = ThreadSession(thread_id="t")
    seqs = [ts.next_seq() for _ in range(10)]
    assert seqs == list(range(10))


@pytest.mark.asyncio
async def test_one_thread_one_active_run():
    mgr = ThreadSessionManager()
    msg = InputMessage.create("thread-a", "compute")
    receipt = await mgr.send_input(msg)
    assert receipt.state == InputDeliveryState.QUEUED
    assert not mgr.has_active_run("thread-a")
    # start_run atomically consumes the queued input
    result = await mgr.start_run("thread-a", object())
    assert result is not None
    run_id, consumed = result
    assert consumed.message_id == msg.message_id
    assert mgr.has_active_run("thread-a")


@pytest.mark.asyncio
async def test_second_input_enqueues():
    mgr = ThreadSessionManager()
    msg1 = InputMessage.create("thread-a", "first")
    r1 = await mgr.send_input(msg1)
    assert r1.state == InputDeliveryState.QUEUED
    result = await mgr.start_run("thread-a", object())
    assert result is not None
    run_id, _ = result
    msg2 = InputMessage.create("thread-a", "second", delivery=InputDelivery.ENQUEUE)
    r2 = await mgr.send_input(msg2)
    assert r2.state == InputDeliveryState.QUEUED


@pytest.mark.asyncio
async def test_two_threads_independent():
    mgr = ThreadSessionManager()
    msg_a = InputMessage.create("thread-a", "task A")
    msg_b = InputMessage.create("thread-b", "task B")
    _ra = await mgr.send_input(msg_a)
    _rb = await mgr.send_input(msg_b)
    res_a = await mgr.start_run("thread-a", object())
    res_b = await mgr.start_run("thread-b", object())
    assert res_a is not None
    assert res_b is not None
    run_a, _ = res_a
    run_b, _ = res_b
    assert mgr.has_active_run("thread-a")
    assert mgr.has_active_run("thread-b")


@pytest.mark.asyncio
async def test_cancel_scoped_to_correct_thread():
    mgr = ThreadSessionManager()
    await mgr.send_input(InputMessage.create("thread-a", "a"))
    await mgr.send_input(InputMessage.create("thread-b", "b"))
    res_a = await mgr.start_run("thread-a", object())
    res_b = await mgr.start_run("thread-b", object())
    assert res_a is not None
    assert res_b is not None
    run_a, _ = res_a
    run_b, _ = res_b
    ok = await mgr.cancel_run("thread-a", run_a)
    assert ok
    assert not mgr.has_active_run("thread-a")
    assert mgr.has_active_run("thread-b")
    ok2 = await mgr.cancel_run("thread-b", "wrong-run-id")
    assert not ok2


@pytest.mark.asyncio
async def test_enqueue_during_active_run():
    mgr = ThreadSessionManager()
    await mgr.send_input(InputMessage.create("t", "start"))
    result = await mgr.start_run("t", object())
    assert result is not None
    session = mgr.get_session("t")
    assert session is not None
    msg = InputMessage.create("t", "next task", delivery=InputDelivery.ENQUEUE)
    receipt = await mgr.send_input(msg)
    assert receipt.state == InputDeliveryState.QUEUED
    assert len(session.queued_inputs) == 1  # "start" was consumed


@pytest.mark.asyncio
async def test_immediate_during_active_run():
    mgr = ThreadSessionManager()
    await mgr.send_input(InputMessage.create("t", "running"))
    result = await mgr.start_run("t", object())
    assert result is not None
    session = mgr.get_session("t")
    msg = InputMessage.create("t", "steer", delivery=InputDelivery.IMMEDIATE)
    receipt = await mgr.send_input(msg)
    assert receipt.state == InputDeliveryState.IMMEDIATE_PENDING
    assert len(session.pending_immediate) == 1


@pytest.mark.asyncio
async def test_auto_during_active_run_treated_as_immediate():
    mgr = ThreadSessionManager()
    await mgr.send_input(InputMessage.create("t", "running"))
    result = await mgr.start_run("t", object())
    assert result is not None
    msg = InputMessage.create("t", "auto-steer", delivery=InputDelivery.AUTO)
    receipt = await mgr.send_input(msg)
    assert receipt.state == InputDeliveryState.IMMEDIATE_PENDING


@pytest.mark.asyncio
async def test_empty_input_rejected():
    mgr = ThreadSessionManager()
    msg = InputMessage.create("t", "")
    receipt = await mgr.send_input(msg)
    assert receipt.state == InputDeliveryState.REJECTED


@pytest.mark.asyncio
async def test_complete_run_defers_pending_immediate():
    mgr = ThreadSessionManager()
    await mgr.send_input(InputMessage.create("t", "running"))
    result = await mgr.start_run("t", object())
    assert result is not None
    run_id, _ = result
    session = mgr.get_session("t")
    session.pending_immediate.append(
        InputMessage.create("t", "late steer", delivery=InputDelivery.IMMEDIATE)
    )
    ok = await mgr.complete_run("t", run_id)
    assert ok
    assert session.active_run_phase == RunPhase.COMPLETED
    assert len(session.queued_inputs) == 1
    assert session.queued_inputs.peek().text == "late steer"


@pytest.mark.asyncio
async def test_cancel_run_defers_pending_immediate():
    mgr = ThreadSessionManager()
    await mgr.send_input(InputMessage.create("t", "running"))
    result = await mgr.start_run("t", object())
    assert result is not None
    run_id, _ = result
    session = mgr.get_session("t")
    session.pending_immediate.append(
        InputMessage.create("t", "interrupted", delivery=InputDelivery.IMMEDIATE)
    )
    ok = await mgr.cancel_run("t", run_id)
    assert ok
    assert session.active_run_phase == RunPhase.CANCELLED
    assert len(session.queued_inputs) == 1


@pytest.mark.asyncio
async def test_complete_wrong_run_id_fails():
    mgr = ThreadSessionManager()
    await mgr.send_input(InputMessage.create("t", "run"))
    result = await mgr.start_run("t", object())
    assert result is not None
    run_id, _ = result
    ok = await mgr.complete_run("t", "wrong-id")
    assert not ok


@pytest.mark.asyncio
async def test_snapshot_nonexistent_thread():
    mgr = ThreadSessionManager()
    snap = await mgr.get_snapshot("no-such-thread")
    assert snap["thread_id"] == "no-such-thread"
    assert not snap["exists"]


@pytest.mark.asyncio
async def test_snapshot_active_run():
    mgr = ThreadSessionManager()
    await mgr.send_input(InputMessage.create("t", "task"))
    result = await mgr.start_run("t", object())
    assert result is not None
    snap = await mgr.get_snapshot("t")
    assert snap["exists"]
    assert snap["active_run_id"] is not None
    assert snap["active_run_phase"] == str(RunPhase.RUNNING)
    assert snap["status"] == "running"


@pytest.mark.asyncio
async def test_close_idle_runner_active_run_protected():
    mgr = ThreadSessionManager()
    mgr._idle_ttl_seconds = 0
    await mgr.send_input(InputMessage.create("t", "running"))
    result = await mgr.start_run("t", object())
    assert result is not None
    session = mgr.get_session("t")
    session.runner = object()
    ok = await mgr.close_idle_runner("t")
    assert not ok
    assert session.runner is not None


@pytest.mark.asyncio
async def test_close_idle_runner_idle_past_ttl():
    mgr = ThreadSessionManager()
    mgr._idle_ttl_seconds = -1
    await mgr.send_input(InputMessage.create("t", "done"))
    result = await mgr.start_run("t", object())
    assert result is not None
    run_id, _ = result
    await mgr.complete_run("t", run_id)
    session = mgr.get_session("t")
    session.runner = object()
    session.last_activity = 0
    ok = await mgr.close_idle_runner("t")
    assert ok
    assert session.runner is None


@pytest.mark.asyncio
async def test_approval_scoped_to_run():
    mgr = ThreadSessionManager()
    await mgr.send_input(InputMessage.create("t", "run-1"))
    result = await mgr.start_run("t", object())
    assert result is not None
    run1_id, _ = result
    session = mgr.get_session("t")

    class FakeApproval:
        approval_id = "apr-001"

    await mgr.add_approval("t", FakeApproval())
    apr = await mgr.resolve_approval("t", run1_id, "apr-001", True)
    assert apr is not None
    await mgr.complete_run("t", run1_id)
    assert session.active_run_phase == RunPhase.COMPLETED
    # Enqueue a new input for run-2, then start it via the single atomic
    # entry (start_run consumes + transitions in one operation).
    await mgr.send_input(InputMessage.create("t", "run-2-input"))
    res2 = await mgr.start_run("t", object())
    assert res2 is not None
    run2_id, _ = res2
    assert run2_id != run1_id
    apr2 = await mgr.resolve_approval("t", run1_id, "apr-001", True)
    assert apr2 is None


@pytest.mark.asyncio
async def test_approval_wrong_run_id_rejected():
    mgr = ThreadSessionManager()
    await mgr.send_input(InputMessage.create("t", "current-run"))
    result = await mgr.start_run("t", object())
    assert result is not None
    apr = await mgr.resolve_approval("t", "wrong-run-id", "apr-001", True)
    assert apr is None


@pytest.mark.asyncio
async def test_thread_a_does_not_block_thread_b():
    mgr = ThreadSessionManager()
    await mgr.send_input(InputMessage.create("a", "task-a"))
    await mgr.send_input(InputMessage.create("b", "task-b"))

    async def op_a():
        session = mgr.get_session("a")
        async with session.lifecycle_lock:
            await asyncio.sleep(0.01)
        return "a-done"

    async def op_b():
        session = mgr.get_session("b")
        async with session.lifecycle_lock:
            pass
        return "b-done"

    results = await asyncio.gather(op_a(), op_b())
    assert results == ["a-done", "b-done"]


@pytest.mark.asyncio
async def test_same_thread_serialized():
    mgr = ThreadSessionManager()
    await mgr.send_input(InputMessage.create("t", "task"))
    order: list[str] = []

    async def op1():
        session = mgr.get_session("t")
        async with session.lifecycle_lock:
            order.append("op1-start")
            await asyncio.sleep(0.02)
            order.append("op1-end")

    async def op2():
        session = mgr.get_session("t")
        async with session.lifecycle_lock:
            order.append("op2-start")
            order.append("op2-end")

    await asyncio.gather(op1(), op2())
    assert order == ["op1-start", "op1-end", "op2-start", "op2-end"]


@pytest.mark.asyncio
async def test_start_run_rejected_when_active():
    mgr = ThreadSessionManager()
    await mgr.send_input(InputMessage.create("t", "first"))
    result = await mgr.start_run("t", object())
    assert result is not None
    run1, _ = result
    result2 = await mgr.start_run("t", object())
    assert result2 is None


@pytest.mark.asyncio
async def test_start_next_queued_after_completion():
    """After completion, the queued input starts a fresh Run via the single
    atomic entry (no separate preparation stage)."""
    mgr = ThreadSessionManager()
    await mgr.send_input(InputMessage.create("t", "first"))
    result = await mgr.start_run("t", object())
    assert result is not None
    run1, _ = result
    await mgr.complete_run("t", run1)
    assert not mgr.has_active_run("t")
    await mgr.send_input(
        InputMessage.create("t", "second", delivery=InputDelivery.ENQUEUE)
    )
    result2 = await mgr.start_run("t", object())
    assert result2 is not None
    run2, consumed = result2
    assert run2 != run1
    assert consumed.message_id.startswith("msg-")
    assert mgr.has_active_run("t")
    assert mgr.get_session("t").active_run_phase == RunPhase.RUNNING


# ============================================================================
# Illegal transitions are rejected (centralized transition map)
# ============================================================================


@pytest.mark.asyncio
async def test_complete_run_from_cancelled_rejected():
    """Terminal states have no outgoing transitions."""
    mgr = ThreadSessionManager()
    await mgr.send_input(InputMessage.create("t", "run"))
    result = await mgr.start_run("t", object())
    assert result is not None
    run_id, _ = result
    ok = await mgr.cancel_run("t", run_id)
    assert ok
    # COMPLETED is not reachable from CANCELLED
    ok2 = await mgr.complete_run("t", run_id)
    assert not ok2
    session = mgr.get_session("t")
    assert session.active_run_phase == RunPhase.CANCELLED


@pytest.mark.asyncio
async def test_fail_run_from_completed_rejected():
    mgr = ThreadSessionManager()
    await mgr.send_input(InputMessage.create("t", "run"))
    result = await mgr.start_run("t", object())
    assert result is not None
    run_id, _ = result
    ok = await mgr.complete_run("t", run_id)
    assert ok
    ok2 = await mgr.fail_run("t", run_id)
    assert not ok2
    session = mgr.get_session("t")
    assert session.active_run_phase == RunPhase.COMPLETED


@pytest.mark.asyncio
async def test_complete_run_walks_through_finalizing():
    """RUNNING → COMPLETED must go through the legal FINALIZING hop."""
    mgr = ThreadSessionManager()
    await mgr.send_input(InputMessage.create("t", "run"))
    result = await mgr.start_run("t", object())
    assert result is not None
    run_id, _ = result
    ok = await mgr.complete_run("t", run_id)
    assert ok
    session = mgr.get_session("t")
    assert session.active_run_phase == RunPhase.COMPLETED
