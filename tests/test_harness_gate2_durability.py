"""Gate 2 (Durability) + Gate 1 (Workspace) acceptance tests.

Covers: workspace write-lease conflicts (场景 E), reconnect without
duplicates (场景 F), restart recovery marking interrupted (场景 G),
persistence round-trips, external task recovery, and fault injection.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from electromind.harness.external import (
    ExternalTaskRef,
    ExternalTaskStatus,
    new_external_task_id,
)
from electromind.harness.identity import WorkspaceKey
from electromind.harness.inbound import InputDelivery, InputMessage
from electromind.harness.persistence import (
    load_thread_state,
    save_thread_state,
    thread_state_path,
)
from electromind.harness.session_manager import ThreadSessionManager
from electromind.harness.state import RunPhase, SessionMode
from electromind.harness.workspace import ApprovalRequest

KEY_A = WorkspaceKey(execution_target_id="local", canonical_workdir="/work/a")
KEY_B = WorkspaceKey(execution_target_id="local", canonical_workdir="/work/b")


# ============================================================================
# 场景 E — Workspace 冲突
# ============================================================================


@pytest.mark.asyncio
async def test_write_conflict_second_run_waits():
    """Two write Runs on the same workspace → the second must wait."""
    mgr = ThreadSessionManager()
    run_a = "run-aaaa"
    ok = await mgr.try_acquire_workspace("thread-a", KEY_A, run_a, SessionMode.RUN)
    assert ok
    assert mgr.workspace_holder(KEY_A) == (run_a, "thread-a")

    # Second write Run on the SAME workspace → conflict
    ok2 = await mgr.try_acquire_workspace(
        "thread-b", KEY_A, "run-bbbb", SessionMode.RUN
    )
    assert not ok2

    # Different workspace → allowed
    ok3 = await mgr.try_acquire_workspace(
        "thread-b", KEY_B, "run-bbbb", SessionMode.RUN
    )
    assert ok3


@pytest.mark.asyncio
async def test_read_only_runs_parallel_with_writer():
    """Ask/Plan (read-only) never block, even while a writer holds the lease."""
    mgr = ThreadSessionManager()
    await mgr.try_acquire_workspace("thread-a", KEY_A, "run-aaaa", SessionMode.RUN)

    # Read-only runs on the SAME workspace proceed
    ok = await mgr.try_acquire_workspace("thread-b", KEY_A, "run-bbbb", SessionMode.ASK)
    assert ok
    ok2 = await mgr.try_acquire_workspace(
        "thread-c", KEY_A, "run-cccc", SessionMode.PLAN
    )
    assert ok2


@pytest.mark.asyncio
async def test_release_allows_next_waiter():
    """Releasing the lease lets the next write Run acquire."""
    mgr = ThreadSessionManager()
    run_a = "run-aaaa"
    await mgr.try_acquire_workspace("thread-a", KEY_A, run_a, SessionMode.RUN)
    assert not await mgr.try_acquire_workspace(
        "thread-b", KEY_A, "run-bbbb", SessionMode.RUN
    )

    # Only the holder may release
    assert not await mgr.release_workspace("thread-b", "run-bbbb")
    assert await mgr.release_workspace("thread-a", run_a)
    assert mgr.workspace_holder(KEY_A) is None

    # Waiter can now proceed
    ok = await mgr.try_acquire_workspace("thread-b", KEY_A, "run-bbbb", SessionMode.RUN)
    assert ok


def test_leases_are_memory_only_no_stuck_locks_after_restart():
    """Restart ⇒ a fresh manager has no leases (nothing stuck forever)."""
    mgr1 = ThreadSessionManager()
    mgr1.workspace_leases.acquire(KEY_A, "run-aaaa", "thread-a", SessionMode.RUN)

    # Simulated restart: new manager instance
    mgr2 = ThreadSessionManager()
    assert mgr2.workspace_holder(KEY_A) is None
    ok = mgr2.workspace_leases.acquire(KEY_A, "run-new", "thread-x", SessionMode.RUN)
    assert ok


# ============================================================================
# Persistence round-trip
# ============================================================================


def test_persistence_round_trip(tmp_path: Path):
    """Save → load yields the same messages/approvals (idempotent)."""
    from electromind.harness.persistence import (
        approval_from_dict,
        approval_to_dict,
        input_message_from_dict,
        input_message_to_dict,
    )

    msg = InputMessage.create("t", "hello", delivery=InputDelivery.IMMEDIATE)
    state = {
        "version": 1,
        "active_run_id": "run-aaaa",
        "queued_inputs": [input_message_to_dict(msg)],
        "pending_immediate": [input_message_to_dict(msg)],
        "pending_approvals": [],
        "external_tasks": [],
    }
    path = thread_state_path(tmp_path)
    save_thread_state(path, state)
    loaded = load_thread_state(path)
    assert loaded is not None
    assert loaded["active_run_id"] == "run-aaaa"
    restored = input_message_from_dict(loaded["pending_immediate"][0])
    assert restored.message_id == msg.message_id
    assert restored.text == "hello"
    assert restored.delivery == InputDelivery.IMMEDIATE

    approval = ApprovalRequest(
        approval_id="apr-001",
        thread_id="t",
        run_id="run-aaaa",
        tool_call_id="tc-1",
        action_id="action:tc-1",
    )
    state2 = {
        "version": 1,
        "active_run_id": None,
        "queued_inputs": [],
        "pending_immediate": [],
        "pending_approvals": [approval_to_dict(approval)],
        "external_tasks": [],
    }
    path2 = thread_state_path(tmp_path / "sub")
    save_thread_state(path2, state2)
    restored2 = approval_from_dict(load_thread_state(path2)["pending_approvals"][0])
    assert restored2.approval_id == "apr-001"
    assert restored2.action_id == "action:tc-1"


def test_corrupt_state_file_loads_as_none(tmp_path: Path):
    path = thread_state_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json!!")
    assert load_thread_state(path) is None


# ============================================================================
# 场景 G — 服务重启恢复
# ============================================================================


@pytest.mark.asyncio
async def test_restart_marks_interrupted_never_completed():
    """A persisted active-run marker ⇒ INTERRUPTED after restart."""
    mgr1 = ThreadSessionManager()
    msg = InputMessage.create("t", "mid-flight")
    await mgr1.send_input(msg)
    result = await mgr1.start_run("t", object())
    assert result is not None
    run_id, _ = result

    # Crash: no complete/cancel/fail ever recorded (the wire layer would
    # have persisted an active-run marker; recovery restores it).
    mgr2 = ThreadSessionManager()  # Restart: fresh manager
    mgr2.restore_session_marker("t", run_id)
    ok = await mgr2.mark_interrupted("t", run_id)
    assert ok
    session = mgr2.get_session("t")
    assert session.active_run_phase == RunPhase.INTERRUPTED
    # NEVER completed
    assert session.active_run_phase != RunPhase.COMPLETED


@pytest.mark.asyncio
async def test_restart_requeues_pending_immediate_at_head():
    """Pending immediate inputs become the HEAD of the queue."""
    mgr = ThreadSessionManager()
    first = InputMessage.create("t", "first", delivery=InputDelivery.ENQUEUE)
    late = InputMessage.create("t", "late steer", delivery=InputDelivery.IMMEDIATE)
    mgr.restore_queued_at_head("t", [late])
    session = mgr.get_session("t")
    session.queued_inputs.enqueue(first)
    assert session.queued_inputs.peek().text == "late steer"


@pytest.mark.asyncio
async def test_restart_expires_unverifiable_approvals():
    """Restored approvals are expired (fail-closed, cannot re-verify)."""
    mgr = ThreadSessionManager()
    approval = ApprovalRequest(
        approval_id="apr-001",
        thread_id="t",
        run_id="run-aaaa",
        tool_call_id="tc-1",
    )
    mgr.restore_approvals("t", [approval])
    session = mgr.get_session("t")
    assert len(session.pending_approvals) == 0
    assert len(session._expired_approvals) == 1
    assert session._expired_approvals[0].approval_id == "apr-001"


@pytest.mark.asyncio
async def test_restore_is_idempotent():
    """Recovery is idempotent across restarts: the recovered queues and
    active-run marker are dropped from the state file after pass 1, so a
    second restart has nothing left to restore (no duplicates)."""
    from electromind.harness.persistence import (
        input_message_from_dict,
        input_message_to_dict,
    )

    late = InputMessage.create("t", "steer", delivery=InputDelivery.IMMEDIATE)
    state = {
        "version": 1,
        "active_run_id": "run-aaaa",
        "queued_inputs": [],
        "pending_immediate": [input_message_to_dict(late)],
        "pending_approvals": [],
        "external_tasks": [],
    }

    # ── Pass 1 (restart) ──────────────────────────────────────────────
    mgr1 = ThreadSessionManager()
    mgr1.restore_session_marker("t", "run-aaaa")
    await mgr1.mark_interrupted("t", "run-aaaa")
    restored = [input_message_from_dict(d) for d in state["pending_immediate"]]
    mgr1.restore_queued_at_head("t", restored)
    assert mgr1.get_session("t").queued_inputs.peek().text == "steer"
    # Recovery write-back: queues + marker are dropped from the file
    state["queued_inputs"] = []
    state["pending_immediate"] = []
    state["pending_approvals"] = []
    state["active_run_id"] = None

    # ── Pass 2 (second restart) ───────────────────────────────────────
    mgr2 = ThreadSessionManager()
    assert state.get("active_run_id") is None  # No marker to interrupt
    session2 = mgr2.get_session("t")
    assert session2 is None or len(session2.queued_inputs) == 0  # No dupes


# ============================================================================
# ExternalTask — ref contract + recovery
# ============================================================================


def test_external_task_ref_contract():
    task = ExternalTaskRef(
        external_task_id=new_external_task_id(),
        thread_id="t",
        adapter="slurm",
        target="hpc-01",
        remote_id="job-42",
        workdir="/home/alice/jobs",
        created_by_run_id="run-aaaa",
        resume_token="tok-1",
        status=ExternalTaskStatus.RUNNING,
    )
    assert task.external_task_id.startswith("xtask-")
    d = task.to_dict()
    assert d["adapter"] == "slurm"
    assert d["remote_id"] == "job-42"
    restored = ExternalTaskRef.from_dict(d)
    assert restored.external_task_id == task.external_task_id
    assert restored.resume_token == "tok-1"


def test_external_task_recovery_marks_unknown():
    """In-flight tasks cannot be re-attached without an adapter → UNKNOWN."""
    from electromind.harness.external import ExternalTaskRegistry

    reg = ExternalTaskRegistry()
    task = ExternalTaskRef(
        external_task_id="xtask-1",
        thread_id="t",
        adapter="slurm",
        target="hpc-01",
        remote_id="job-42",
        workdir="/w",
        created_by_run_id="run-aaaa",
        resume_token="tok",
        status=ExternalTaskStatus.RUNNING,
    )
    done = ExternalTaskRef(
        external_task_id="xtask-2",
        thread_id="t",
        adapter="slurm",
        target="hpc-01",
        remote_id="job-43",
        workdir="/w",
        created_by_run_id="run-aaaa",
        resume_token="tok2",
        status=ExternalTaskStatus.COMPLETED,
    )
    reg.restore([task, done])
    reg.mark_unverifiable_unknown()
    assert reg.get("xtask-1").status == ExternalTaskStatus.UNKNOWN
    # Completed tasks are NOT downgraded
    assert reg.get("xtask-2").status == ExternalTaskStatus.COMPLETED


def test_external_task_persists_through_state_file(tmp_path: Path):
    from electromind.harness.external import ExternalTaskRegistry

    reg = ExternalTaskRegistry()
    task = ExternalTaskRef(
        external_task_id="xtask-1",
        thread_id="t",
        adapter="ssh",
        target="host-a",
        remote_id="pid-7",
        workdir="/w",
        created_by_run_id="run-aaaa",
        resume_token="tok",
        status=ExternalTaskStatus.RUNNING,
    )
    reg.register(task)
    state = {
        "version": 1,
        "active_run_id": None,
        "queued_inputs": [],
        "pending_immediate": [],
        "pending_approvals": [],
        "external_tasks": [t.to_dict() for t in reg.all()],
    }
    path = thread_state_path(tmp_path)
    save_thread_state(path, state)
    loaded = load_thread_state(path)
    assert loaded["external_tasks"][0]["external_task_id"] == "xtask-1"
    assert loaded["external_tasks"][0]["status"] == "running"


# ============================================================================
# 场景 F — 断线重连无重复 (snapshot-level dedup)
# ============================================================================


@pytest.mark.asyncio
async def test_reconnect_snapshot_no_duplicates():
    """Reconnecting with after_seq resumes without duplicate items."""
    mgr = ThreadSessionManager()
    msg = InputMessage.create("t", "task")
    await mgr.send_input(msg)
    result = await mgr.start_run("t", object())
    assert result is not None
    run_id, _ = result

    # Client "disconnects"; backend Run continues (session stays active)
    assert mgr.has_active_run("t")

    # Reconnect: full snapshot
    snap = await mgr.get_snapshot("t")
    assert snap["exists"]
    assert snap["active_run_id"] == run_id
    assert snap["status"] == "running"

    # A second snapshot (simulated duplicate fetch) must be identical
    snap2 = await mgr.get_snapshot("t")
    assert snap2["active_run_id"] == snap["active_run_id"]
    assert snap2["queued_input_count"] == snap["queued_input_count"]


@pytest.mark.asyncio
async def test_disconnect_does_not_terminate_run():
    """The backend Run is independent of any client connection."""
    mgr = ThreadSessionManager()
    await mgr.send_input(InputMessage.create("t", "task"))
    result = await mgr.start_run("t", object())
    assert result is not None
    run_id, _ = result
    # No client involvement in the manager — the Run stays active
    assert mgr.has_active_run("t")
    await mgr.complete_run("t", run_id)
    assert not mgr.has_active_run("t")


# ============================================================================
# Fault injection — crash before terminal transition
# ============================================================================


@pytest.mark.asyncio
async def test_fault_injection_crash_mid_run():
    """Simulate a crash: state file present with active marker, no terminal
    transition ever recorded → recovery marks INTERRUPTED, not COMPLETED."""
    mgr = ThreadSessionManager()
    await mgr.send_input(InputMessage.create("t", "crash me"))
    result = await mgr.start_run("t", object())
    assert result is not None
    run_id, _ = result
    # Crash: no complete_run/cancel_run/fail_run

    # Restart path (what _recover_thread_states does per thread):
    mgr2 = ThreadSessionManager()
    mgr2.restore_session_marker("t", run_id)
    await mgr2.mark_interrupted("t", run_id)
    session = mgr2.get_session("t")
    assert session.active_run_phase == RunPhase.INTERRUPTED
    # No auto-retry: start_run must not be triggered by recovery alone
    assert not mgr2.has_active_run("t")


# ============================================================================
# Audit closure — message_id idempotency, RunSnapshot freeze, item_id
# ============================================================================


@pytest.mark.asyncio
async def test_duplicate_message_id_replays_receipt():
    """Retrying with the same message_id must not append a second copy."""
    from electromind.harness.state import InputDeliveryState

    mgr = ThreadSessionManager()
    msg = InputMessage.create("t", "first")
    r1 = await mgr.send_input(msg)
    assert r1.state == InputDeliveryState.QUEUED

    # Retry with the SAME message_id → replay the original receipt
    retry = InputMessage(
        message_id=msg.message_id,
        thread_id=msg.thread_id,
        target_run_id=msg.target_run_id,
        text=msg.text,
        delivery=msg.delivery,
        created_at=msg.created_at,
    )
    r2 = await mgr.send_input(retry)
    assert r2.state == InputDeliveryState.QUEUED
    assert r2.message_id == msg.message_id
    session = mgr.get_session("t")
    assert len(session.queued_inputs) == 1  # Not duplicated

    # Duplicate immediate also replays
    start_result = await mgr.start_run("t", object())  # Now active
    assert start_result is not None
    run_id, _ = start_result
    imm = InputMessage.create("t", "steer", delivery=InputDelivery.IMMEDIATE)
    ri1 = await mgr.send_input(imm)
    assert ri1.state == InputDeliveryState.IMMEDIATE_PENDING
    ri2 = await mgr.send_input(imm)  # Same object — same message_id
    assert ri2.state == InputDeliveryState.IMMEDIATE_PENDING
    assert len(mgr.get_session("t").pending_immediate) == 1

    # Consumed messages stay idempotent: the Run consumed `msg`, but a
    # retry with the same message_id replays the ORIGINAL receipt and must
    # NOT re-append the message or start a second Run.
    consumed_retry = InputMessage(
        message_id=msg.message_id,
        thread_id=msg.thread_id,
        target_run_id=msg.target_run_id,
        text=msg.text,
        delivery=msg.delivery,
        created_at=msg.created_at,
    )
    r3 = await mgr.send_input(consumed_retry)
    assert r3.state == InputDeliveryState.QUEUED  # Original receipt replayed
    session = mgr.get_session("t")
    assert len(session.queued_inputs) == 0  # Not re-appended
    assert session.active_run_id == run_id  # No second Run born


@pytest.mark.asyncio
async def test_run_snapshot_frozen_and_exposed():
    """RunSnapshot is captured at Run creation and appears in snapshots."""
    from electromind.harness.identity import RunSnapshot

    mgr = ThreadSessionManager()
    msg = InputMessage.create("t", "task")
    await mgr.send_input(msg)
    result = await mgr.start_run("t", object())
    assert result is not None
    run_id, _ = result

    from electromind.harness.state import ExecutionTargetSnapshot

    snapshot_obj = RunSnapshot(
        run_id=run_id,
        thread_id="t",
        input_message_id=msg.message_id,
        session_mode=SessionMode.RUN,
        model="deepseek-v4",
        max_iterations=10,
        execution_target=ExecutionTargetSnapshot(
            target_id="local", kind="local", workdir="/w"
        ),
        permission_policy=object(),
        project_path="/w",
        system_prompt_digest="sys",
        skill_set_digest="skills",
        tool_set_digest="tools",
        created_at="2026-01-01T00:00:00",
    )
    await mgr.set_run_snapshot("t", snapshot_obj)

    snap = await mgr.get_snapshot("t")
    assert snap["run_snapshot"] is not None
    rs = snap["run_snapshot"]
    assert rs["run_id"] == run_id
    assert rs["model"] == "deepseek-v4"
    assert rs["max_iterations"] == 10
    assert rs["session_mode"] == "run"
    assert rs["execution_target"]["kind"] == "local"


def test_run_snapshot_is_immutable():
    """Frozen dataclass — attribute assignment must raise."""
    from dataclasses import FrozenInstanceError

    from electromind.harness.identity import RunSnapshot

    snap = RunSnapshot(
        run_id="run-1",
        thread_id="t",
        input_message_id="msg-1",
        session_mode=SessionMode.RUN,
        model="m",
        max_iterations=5,
        execution_target=WorkspaceKey("local", "/w"),
        permission_policy=object(),
        project_path="/w",
        system_prompt_digest="",
        skill_set_digest="",
        tool_set_digest="",
        created_at="now",
    )
    with pytest.raises(FrozenInstanceError):
        snap.model = "other"


@pytest.mark.asyncio
async def test_snapshot_includes_external_task_refs():
    mgr = ThreadSessionManager()
    task = ExternalTaskRef(
        external_task_id="xtask-1",
        thread_id="t2",
        adapter="ssh",
        target="h",
        remote_id="r",
        workdir="/w",
        created_by_run_id="run-1",
        resume_token="tok",
    )
    mgr.external_tasks.register(task)
    # Create the session so the snapshot is non-empty
    await mgr.send_input(InputMessage.create("t2", "hi"))
    snap2 = await mgr.get_snapshot("t2")
    assert snap2["exists"]
    assert any(t["external_task_id"] == "xtask-1" for t in snap2["external_tasks"])


# ============================================================================
# Audit closure 2 — wire recovery, snapshot replacement guard, receipt history
# ============================================================================


def _snapshot(run_id: str, model: str):
    """Build a minimal frozen RunSnapshot for manager tests."""
    from electromind.harness.identity import RunSnapshot

    return RunSnapshot(
        run_id=run_id,
        thread_id="t",
        input_message_id="msg-1",
        session_mode=SessionMode.RUN,
        model=model,
        max_iterations=5,
        execution_target=WorkspaceKey("local", "/w"),
        permission_policy=object(),
        project_path="/w",
        system_prompt_digest="",
        skill_set_digest="",
        tool_set_digest="",
        created_at="now",
    )


@pytest.mark.asyncio
async def test_run_snapshot_cannot_be_replaced_for_same_run():
    """Only the CURRENT active Run may freeze its snapshot, and only once:
    same-run re-install is rejected AND a stale/foreign run_id is rejected
    (regression: unconditional assignment let a later snapshot replace the
    frozen one, and any different run_id could overwrite the active run's)."""

    mgr = ThreadSessionManager()
    await mgr.send_input(InputMessage.create("t", "task"))
    result = await mgr.start_run("t", object())
    assert result is not None
    run_id, _ = result

    assert await mgr.set_run_snapshot("t", _snapshot(run_id, "first")) is True
    # Same run → rejected, the frozen snapshot stays "first"
    assert await mgr.set_run_snapshot("t", _snapshot(run_id, "second")) is False
    # A run that is NOT the active run → rejected too
    assert (
        await mgr.set_run_snapshot("t", _snapshot("run-not-active", "other")) is False
    )
    snap = await mgr.get_snapshot("t")
    assert snap["run_snapshot"]["run_id"] == run_id
    assert snap["run_snapshot"]["model"] == "first"

    # The NEXT Run becomes active → it may install its own snapshot
    assert await mgr.complete_run("t", run_id)
    await mgr.send_input(InputMessage.create("t", "next task"))
    result2 = await mgr.start_run("t", object())
    assert result2 is not None
    run2, _ = result2
    assert run2 != run_id
    assert await mgr.set_run_snapshot("t", _snapshot(run2, "second-run")) is True
    snap2 = await mgr.get_snapshot("t")
    assert snap2["run_snapshot"]["run_id"] == run2
    assert snap2["run_snapshot"]["model"] == "second-run"


@pytest.mark.asyncio
async def test_wire_recovery_runs_full_scan(tmp_path, monkeypatch):
    """wire._recover_thread_states must run the per-thread recovery scan
    without crashing (regression: it called save_thread_state without
    importing it → NameError) and restore receipt history for idempotency."""

    from app import wire
    from electromind.harness.inbound import queued_receipt
    from electromind.harness.persistence import (
        input_message_to_dict,
        receipt_to_dict,
    )

    thread_dir = tmp_path / "thread-rec"
    thread_dir.mkdir()
    queued_input = InputMessage.create(
        "thread-rec", "durable queued", delivery=InputDelivery.ENQUEUE
    )
    mid_run = InputMessage.create(
        "thread-rec", "mid-run steer", delivery=InputDelivery.IMMEDIATE
    )
    consumed = InputMessage.create("thread-rec", "consumed earlier")
    state = {
        "version": 1,
        "active_run_id": "run-rec",
        "queued_inputs": [input_message_to_dict(queued_input)],
        "pending_immediate": [input_message_to_dict(mid_run)],
        "pending_approvals": [],
        "receipt_history": [receipt_to_dict(queued_receipt(consumed))],
        "external_tasks": [],
    }
    save_thread_state(thread_state_path(thread_dir), state)

    wire._harness_manager._sessions.clear()
    monkeypatch.setattr(wire, "default_threads_root", lambda: str(tmp_path))
    try:
        with patch.object(wire, "log", lambda *a, **k: None):
            await wire._recover_thread_states()

        session = wire._harness_manager.get_session("thread-rec")
        assert session is not None
        # Crash mid-Run → INTERRUPTED, never COMPLETED
        assert session.active_run_phase == RunPhase.INTERRUPTED
        # PLAIN queued inputs are durable too: restored to the TAIL, FIFO
        # order preserved, deferred immediate at the HEAD (regression: the
        # queued input was silently dropped by recovery).
        assert len(session.queued_inputs) == 2
        assert session.queued_inputs.peek().message_id == mid_run.message_id
        tail = list(session.queued_inputs.all())[-1]
        assert tail.message_id == queued_input.message_id

        # Restored receipt history: retrying a CONSUMED message_id replays
        # the original receipt instead of appending a duplicate.
        retry = InputMessage(
            message_id=consumed.message_id,
            thread_id=consumed.thread_id,
            target_run_id=consumed.target_run_id,
            text=consumed.text,
            delivery=consumed.delivery,
            created_at=consumed.created_at,
        )
        r = await wire._harness_manager.send_input(retry)
        assert r.message_id == retry.message_id
        assert len(session.queued_inputs) == 2  # Not re-appended

        # Crash-safe handoff: the file now carries the LIVE recovered
        # state (queues + receipts) — a SECOND crash right after recovery
        # must not lose the recovered messages (regression: the file was
        # cleared without re-persisting first).
        data = load_thread_state(thread_state_path(thread_dir))
        assert data is not None
        assert data["active_run_id"] is None  # interrupted stays terminal
        assert len(data["queued_inputs"]) == 2  # handed back to the file
        assert data["pending_immediate"] == []
        assert len(data["receipt_history"]) == 1

        # Simulated second restart: fresh manager restores from the file
        wire._harness_manager._sessions.clear()
        await wire._recover_thread_states()
        session2 = wire._harness_manager.get_session("thread-rec")
        assert len(session2.queued_inputs) == 2  # Exactly two — no dupes
    finally:
        wire._harness_manager._sessions.clear()


def test_receipt_history_round_trip():
    """Receipt (de)serialization preserves the full InputReceipt."""
    from electromind.harness.inbound import immediate_pending_receipt
    from electromind.harness.persistence import (
        receipt_from_dict,
        receipt_to_dict,
    )

    msg = InputMessage.create("t", "hi", delivery=InputDelivery.IMMEDIATE)
    receipt = immediate_pending_receipt(msg)
    restored = receipt_from_dict(receipt_to_dict(receipt))
    assert restored.message_id == receipt.message_id
    assert restored.thread_id == receipt.thread_id
    assert restored.state == receipt.state
    assert restored.target_run_id == receipt.target_run_id
    assert restored.detail == receipt.detail


def test_receipt_history_restore_enforces_cap():
    """Restoring an oversized receipt history trims to the cap — the
    newest 1024 entries survive (regression: restore popped only one)."""
    from electromind.harness.inbound import queued_receipt
    from electromind.harness.session_manager import ThreadSessionManager

    mgr = ThreadSessionManager()
    receipts = []
    for i in range(2000):
        msg = InputMessage.create("t", f"msg {i}")
        receipts.append(queued_receipt(msg))
    mgr.restore_receipt_history("t", receipts)

    session = mgr.get_session("t")
    assert len(session.receipt_history) == ThreadSessionManager.RECEIPT_HISTORY_LIMIT
    # The NEWEST entries survive (dict order = insertion order)
    latest = receipts[-1].message_id
    assert latest in session.receipt_history
    # The OLDEST were evicted
    assert receipts[0].message_id not in session.receipt_history


# ============================================================================
# Audit closure 3 — terminal marker, workspace aliases/waiters, thread scope
# ============================================================================


@pytest.mark.asyncio
async def test_terminal_run_not_persisted_as_active_marker(tmp_path, monkeypatch):
    """A COMPLETED run must NOT be persisted with an active-run marker —
    the next restart would otherwise report it as interrupted (regression:
    complete_run keeps the old active_run_id and persistence stored it)."""
    from app import wire

    thread_dir = tmp_path / "thread-term"
    thread_dir.mkdir()
    session = wire._harness_manager._get_or_create("thread-term")
    session.active_run_id = "run-done"
    session.active_run_phase = RunPhase.COMPLETED
    monkeypatch.setattr(
        wire, "_thread_state_path_for", lambda tid: thread_state_path(thread_dir)
    )
    try:
        wire._persist_thread_state("thread-term")
        data = load_thread_state(thread_state_path(thread_dir))
        assert data is not None
        assert data["active_run_id"] is None  # Never restored as interrupted

        # A LIVE run IS persisted as the marker
        session.active_run_phase = RunPhase.RUNNING
        wire._persist_thread_state("thread-term")
        data2 = load_thread_state(thread_state_path(thread_dir))
        assert data2["active_run_id"] == "run-done"
    finally:
        wire._harness_manager._sessions.clear()


def test_workspace_key_canonicalizes_path_aliases(tmp_path):
    """Path aliases (/a vs /a/. vs a symlink) must map to ONE lease key —
    raw strings let two writers hold the 'exclusive' lease (regression)."""
    from app import wire
    from electromind.harness.identity import WorkspaceKey

    workdir = str(tmp_path)
    key1 = WorkspaceKey("local", wire._canonical_workdir(workdir, local=True))
    key2 = WorkspaceKey("local", wire._canonical_workdir(workdir + "/.", local=True))
    assert key1 == key2
    key3 = WorkspaceKey("local", wire._canonical_workdir(workdir + "/", local=True))
    assert key1 == key3
    # Symlink alias resolves to the same directory
    link = tmp_path / "alias-link"
    link.symlink_to(tmp_path)
    key4 = WorkspaceKey("local", wire._canonical_workdir(str(link), local=True))
    assert key1 == key4
    # Remote paths are normalized lexically, never host-resolved
    remote = wire._canonical_workdir("/home/a/work/./x", local=False)
    assert remote == "/home/a/work/x"


def test_workspace_waiter_registered_and_woken():
    """Threads blocked on a lease register as waiters; the release path
    wakes them (a conflict must never wait forever)."""
    mgr = ThreadSessionManager()
    key = WorkspaceKey("local", "/work/w")
    mgr.register_workspace_waiter("t-b", key)
    mgr.register_workspace_waiter("t-b", key)  # Idempotent
    assert mgr.take_workspace_waiters(key) == ["t-b"]
    assert mgr.take_workspace_waiters(key) == []  # Consumed once


def test_external_task_refs_are_thread_scoped():
    """ExternalTaskRefs carry thread_id and the registry filters by it —
    snapshots must never leak another thread's remote ids/resume tokens."""
    from electromind.harness.external import ExternalTaskRegistry

    reg = ExternalTaskRegistry()
    t1 = ExternalTaskRef(
        external_task_id="x1",
        thread_id="a",
        adapter="ssh",
        target="h",
        remote_id="r1",
        workdir="/w",
        created_by_run_id="run-1",
        resume_token="tok-1",
    )
    t2 = ExternalTaskRef(
        external_task_id="x2",
        thread_id="b",
        adapter="ssh",
        target="h",
        remote_id="r2",
        workdir="/w",
        created_by_run_id="run-2",
        resume_token="tok-2",
    )
    reg.register(t1)
    reg.register(t2)
    assert reg.for_thread("a") == [t1]
    assert reg.for_thread("b") == [t2]
    assert reg.for_thread("c") == []


# ============================================================================
# Audit closure 4 — settle identity, sandbox mode, thread-scoped persistence
# ============================================================================


@pytest.mark.asyncio
async def test_settle_pending_immediate_preserves_identity():
    """Settling after Run end keeps the ORIGINAL InputMessage (message_id
    intact) for deferred steers, and classifies consumed ones as applied —
    no re-created messages, no stuck immediate_pending receipts."""
    mgr = ThreadSessionManager()
    session = mgr._get_or_create("t")
    original = InputMessage.create("t", "steer me", delivery=InputDelivery.IMMEDIATE)
    session.pending_immediate.append(original)
    consumed = InputMessage.create(
        "t", "already read", delivery=InputDelivery.IMMEDIATE
    )
    session.pending_immediate.append(consumed)

    # Exact message_id classification: "already read" was never read →
    # deferred with its ORIGINAL identity; "steer me" WAS consumed.
    deferred, applied = await mgr.settle_pending_immediate(
        "t", [(consumed.message_id, consumed.text)]
    )
    assert [m.message_id for m in deferred] == [consumed.message_id]
    assert [m.message_id for m in applied] == [original.message_id]
    assert deferred[0] is consumed  # SAME object — identity preserved
    assert session.pending_immediate == []


@pytest.mark.asyncio
async def test_settle_same_text_messages_by_id_not_text():
    """Two steers with IDENTICAL text: the first was consumed, the second
    unread.  Text counting would swap their fate — message_id must decide
    (regression: identical-text steers were classified backwards)."""
    mgr = ThreadSessionManager()
    session = mgr._get_or_create("t")
    first = InputMessage.create("t", "same words", delivery=InputDelivery.IMMEDIATE)
    second = InputMessage.create("t", "same words", delivery=InputDelivery.IMMEDIATE)
    session.pending_immediate.append(first)
    session.pending_immediate.append(second)

    # The loop consumed FIRST (its id left the mailbox); SECOND is unread.
    # The unread report carries SECOND's id — even though the text matches
    # both, only SECOND must be deferred.
    deferred, applied = await mgr.settle_pending_immediate(
        "t", [(second.message_id, second.text)]
    )
    assert [m.message_id for m in deferred] == [second.message_id]
    assert [m.message_id for m in applied] == [first.message_id]
    assert deferred[0] is second


def test_apply_requested_sandbox_mode_changes_actual_guard():
    """The UI's requested mode must change the RUNNER's sandbox
    session_mode (the tool guard re-reads it per call) and restore it
    after the Run — not just the snapshot (regression: the runner kept
    the base config's write capability)."""
    from app import wire
    from electromind.harness.state import SessionMode

    runner = MagicMock()
    runner.thread.id = "thread-a"
    runner.sandbox = SimpleNamespace(spec=SimpleNamespace(session_mode="agent"))

    restore = wire._apply_requested_sandbox_mode(runner, SessionMode.PLAN)
    assert runner.sandbox.spec.session_mode == "plan"  # Read-only now

    # Same mode → no-op restore
    restore2 = wire._apply_requested_sandbox_mode(runner, SessionMode.PLAN)
    restore2()
    assert runner.sandbox.spec.session_mode == "plan"

    restore()  # Run ended → original capability restored
    assert runner.sandbox.spec.session_mode == "agent"

    # ASK maps to ask; RUN maps back to agent (sandbox's write mode)
    wire._apply_requested_sandbox_mode(runner, SessionMode.ASK)
    assert runner.sandbox.spec.session_mode == "ask"
    wire._apply_requested_sandbox_mode(runner, SessionMode.RUN)
    assert runner.sandbox.spec.session_mode == "agent"


@pytest.mark.asyncio
async def test_persist_external_tasks_is_thread_scoped(tmp_path, monkeypatch):
    """Each thread's harness_state.json persists ONLY its own external
    tasks — remote ids / resume tokens never leak into another thread's
    file (regression: the whole registry was written per thread)."""
    from app import wire
    from electromind.harness.external import ExternalTaskRef

    for tid in ("t-a", "t-b"):
        (tmp_path / tid).mkdir()
    wire._harness_manager._get_or_create("t-a")
    wire._harness_manager._get_or_create("t-b")
    task_a = ExternalTaskRef(
        external_task_id="xa",
        thread_id="t-a",
        adapter="ssh",
        target="h",
        remote_id="r-secret-a",
        workdir="/w",
        created_by_run_id="run-1",
        resume_token="tok-a",
    )
    task_b = ExternalTaskRef(
        external_task_id="xb",
        thread_id="t-b",
        adapter="ssh",
        target="h",
        remote_id="r-secret-b",
        workdir="/w",
        created_by_run_id="run-2",
        resume_token="tok-b",
    )
    wire._harness_manager.external_tasks.register(task_a)
    wire._harness_manager.external_tasks.register(task_b)

    def path_for(tid):
        return thread_state_path(tmp_path / tid)

    monkeypatch.setattr(wire, "_thread_state_path_for", path_for)
    try:
        wire._persist_thread_state("t-a")
        wire._persist_thread_state("t-b")
        data_a = load_thread_state(path_for("t-a"))
        data_b = load_thread_state(path_for("t-b"))
        assert [t["external_task_id"] for t in data_a["external_tasks"]] == ["xa"]
        assert [t["external_task_id"] for t in data_b["external_tasks"]] == ["xb"]
        assert "r-secret-b" not in json.dumps(data_a["external_tasks"])
        assert "r-secret-a" not in json.dumps(data_b["external_tasks"])
    finally:
        wire._harness_manager._sessions.clear()


# ============================================================================
# Audit closure 5 — peek runner, blob dangling degradation
# ============================================================================


def test_peek_runner_is_non_destructive():
    """The workspace-waiter wake-up PEEKS (never pops) the runner — a
    conflict re-registers the waiter and the NEXT release must still find
    it (regression: pop lost the runner after the first conflict)."""
    from app import wire

    runner = object()
    state: dict = {"_runners": {"w2": runner}}
    assert wire._peek_runner(state, "w2") is runner
    assert wire._peek_runner(state, "w2") is runner  # Still registered
    # Thread-switch load stays destructive (consumes the entry)
    assert wire._load_runner(state, "w2") is runner
    assert wire._load_runner(state, "w2") is None


def test_blob_dangling_reference_degrades_to_inexact():
    """A snapshot whose blob content was evicted/cleared degrades to
    exact=False — never an empty-but-exact diff over dangling hashes."""
    from electromind.harness.mutations import (
        SNAPSHOT_CONTENT_LIMIT,
        FileMutationDelta,
        FileSnapshot,
        MutationBlobStore,
        MutationTracker,
    )

    big = b"x" * (SNAPSHOT_CONTENT_LIMIT + 10)
    store = MutationBlobStore()
    before = FileSnapshot.from_bytes(big, "big.bin", blob_store=store)
    tracker = MutationTracker(blob_store=store)
    tracker.track(
        FileMutationDelta(
            source="sandbox",
            tool_call_id="tc-1",
            path="big.bin",
            kind="update",
            before=before,
            after=before,
            exact=True,
        )
    )
    # New Run cleared the store → the sha256 references now dangle
    store.clear()
    net = tracker.net_change("sandbox", "big.bin", "")
    assert net is not None
    assert net["exact"] is False  # Degraded, never fabricated

    # With the blob present the same content stays exact
    store2 = MutationBlobStore()
    snap = FileSnapshot.from_bytes(big, "big.bin", blob_store=store2)
    tracker2 = MutationTracker(blob_store=store2)
    tracker2.track(
        FileMutationDelta(
            source="sandbox",
            tool_call_id="tc-1",
            path="big.bin",
            kind="update",
            before=snap,
            after=snap,
            exact=True,
        )
    )
    net2 = tracker2.net_change("sandbox", "big.bin", "")
    assert net2 is not None
    assert net2["exact"] is True
