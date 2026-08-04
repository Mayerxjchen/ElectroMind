"""Approval scope regression tests.

Covers the full chain at the wire level: permit/deny commands must carry
approval_id + thread_id + run_id + tool_call_id, the approval must be
registered in the harness session's pending_approvals, and the backend
must reject cross-Thread / cross-Run / unregistered / stale approvals.

Fail-closed: missing scope or unknown approval_id is REJECTED, never
silently permitted.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app import wire
from app.config import ReplConfig


@pytest.fixture(autouse=True)
def _reset_harness_sessions():
    """Isolate tests: clear the global harness manager between tests."""
    wire._harness_manager._sessions.clear()
    yield
    wire._harness_manager._sessions.clear()


def _make_runner(thread_id: str = "thread-a"):
    """Build a fake runner with inbound mailbox and deterministic
    snapshot inputs (agent with explicit system/tools, no sandbox, no
    skill runtime) — the auto-start path freezes a RunSnapshot."""
    runner = MagicMock()
    runner.thread.id = thread_id
    runner.thread.project_path = ""
    runner.agent = SimpleNamespace(system="test system prompt", tools=[])
    runner.sandbox = None
    runner.skill_runtime = None
    runner._execution = None
    runner.inbound = MagicMock()
    runner.inbound.permit = MagicMock()
    runner.inbound.deny = MagicMock()
    return runner


async def _register_approval(
    thread_id: str,
    run_id: str,
    approval_id: str,
    tool_call_id: str,
):
    """Register a pending approval in the harness session (as the real
    emit_permit_request does).  The session's active run is set so the
    run_id scope check passes."""
    from electromind.harness.state import RunPhase
    from electromind.harness.workspace import ApprovalRequest

    session = wire._harness_manager._get_or_create(thread_id)
    session.active_run_id = run_id
    session.active_run_phase = RunPhase.RUNNING
    approval = ApprovalRequest(
        approval_id=approval_id,
        thread_id=thread_id,
        run_id=run_id,
        tool_call_id=tool_call_id,
    )
    return await wire._harness_manager.add_approval(thread_id, approval)


@pytest.mark.asyncio
async def test_permit_passes_full_scope_to_inbound():
    """Permit with a REGISTERED approval routes to runner.inbound.permit."""
    runner = _make_runner("thread-a")
    await _register_approval("thread-a", "run-1", "apr-001", "tc-1")
    events: list[dict] = []

    def capture(line: str):
        events.append(json.loads(line.strip()))

    with patch.object(wire, "emit_line", capture):
        await wire.handle_command(
            {
                "cmd": "permit",
                "tool_call_id": "tc-1",
                "approval_id": "apr-001",
                "thread_id": "thread-a",
                "run_id": "run-1",
            },
            runner,
            ReplConfig(),
            {"turn": None},
        )

    runner.inbound.permit.assert_called_once_with("tc-1")
    resolved = [e for e in events if e.get("method") == "approval/resolved"]
    assert len(resolved) == 1
    assert resolved[0]["params"]["status"] == "approved"
    assert resolved[0]["params"]["approval_id"] == "apr-001"
    assert resolved[0]["params"]["tool_call_id"] == "tc-1"


@pytest.mark.asyncio
async def test_permit_unregistered_approval_rejected():
    """An approval_id that was never registered must be REJECTED."""
    runner = _make_runner("thread-a")
    events: list[dict] = []

    def capture(line: str):
        events.append(json.loads(line.strip()))

    with patch.object(wire, "log", lambda text: None):
        with patch.object(wire, "emit_line", capture):
            await wire.handle_command(
                {
                    "cmd": "permit",
                    "tool_call_id": "tc-1",
                    "approval_id": "apr-unknown",  # Never registered
                    "thread_id": "thread-a",
                    "run_id": "run-1",
                },
                runner,
                ReplConfig(),
                {"turn": None},
            )

    runner.inbound.permit.assert_not_called()
    resolved = [e for e in events if e.get("method") == "approval/resolved"]
    assert len(resolved) == 1
    assert resolved[0]["params"]["status"] == "expired"


@pytest.mark.asyncio
async def test_permit_wrong_tool_call_id_rejected():
    """approval_id bound to a different tool_call_id must be REJECTED."""
    runner = _make_runner("thread-a")
    await _register_approval("thread-a", "run-1", "apr-001", "tc-A")
    events: list[dict] = []

    def capture(line: str):
        events.append(json.loads(line.strip()))

    with patch.object(wire, "log", lambda text: None):
        with patch.object(wire, "emit_line", capture):
            await wire.handle_command(
                {
                    "cmd": "permit",
                    "tool_call_id": "tc-B",  # Different tool call
                    "approval_id": "apr-001",
                    "thread_id": "thread-a",
                    "run_id": "run-1",
                },
                runner,
                ReplConfig(),
                {"turn": None},
            )

    runner.inbound.permit.assert_not_called()
    resolved = [e for e in events if e.get("method") == "approval/resolved"]
    assert resolved[0]["params"]["status"] == "expired"


@pytest.mark.asyncio
async def test_permit_wrong_thread_rejected():
    """Permit for a different thread must NOT reach the runner."""
    runner = _make_runner("thread-a")
    await _register_approval("thread-a", "run-1", "apr-001", "tc-1")
    events: list[dict] = []

    def capture(line: str):
        events.append(json.loads(line.strip()))

    with patch.object(wire, "log", lambda text: None):
        with patch.object(wire, "emit_line", capture):
            await wire.handle_command(
                {
                    "cmd": "permit",
                    "tool_call_id": "tc-1",
                    "approval_id": "apr-001",
                    "thread_id": "thread-B",  # Wrong thread
                    "run_id": "run-1",
                },
                runner,
                ReplConfig(),
                {"turn": None},
            )

    runner.inbound.permit.assert_not_called()
    resolved = [e for e in events if e.get("method") == "approval/resolved"]
    assert len(resolved) == 1
    assert resolved[0]["params"]["status"] == "expired"


@pytest.mark.asyncio
async def test_permit_wrong_run_rejected():
    """Permit for a stale run must NOT reach the runner."""
    runner = _make_runner("thread-a")
    await _register_approval("thread-a", "run-9", "apr-001", "tc-1")
    events: list[dict] = []

    def capture(line: str):
        events.append(json.loads(line.strip()))

    with patch.object(wire, "log", lambda text: None):
        with patch.object(wire, "emit_line", capture):
            await wire.handle_command(
                {
                    "cmd": "permit",
                    "tool_call_id": "tc-1",
                    "approval_id": "apr-001",
                    "thread_id": "thread-a",
                    "run_id": "run-1",  # Stale run (registered under run-9)
                },
                runner,
                ReplConfig(),
                {"turn": None},
            )

    runner.inbound.permit.assert_not_called()
    resolved = [e for e in events if e.get("method") == "approval/resolved"]
    assert len(resolved) == 1
    assert resolved[0]["params"]["status"] == "expired"


@pytest.mark.asyncio
async def test_deny_passes_full_scope():
    """Deny with a registered approval routes to runner.inbound.deny."""
    runner = _make_runner("thread-a")
    await _register_approval("thread-a", "run-1", "apr-002", "tc-2")
    events: list[dict] = []

    def capture(line: str):
        events.append(json.loads(line.strip()))

    with patch.object(wire, "emit_line", capture):
        await wire.handle_command(
            {
                "cmd": "deny",
                "tool_call_id": "tc-2",
                "reason": "unsafe",
                "approval_id": "apr-002",
                "thread_id": "thread-a",
                "run_id": "run-1",
            },
            runner,
            ReplConfig(),
            {"turn": None},
        )

    runner.inbound.deny.assert_called_once_with("tc-2", reason="unsafe")
    resolved = [e for e in events if e.get("method") == "approval/resolved"]
    assert len(resolved) == 1
    assert resolved[0]["params"]["status"] == "denied"


@pytest.mark.asyncio
async def test_approval_cannot_be_resolved_twice():
    """After resolution the approval is consumed — a second permit fails."""
    runner = _make_runner("thread-a")
    await _register_approval("thread-a", "run-1", "apr-001", "tc-1")
    events: list[dict] = []

    def capture(line: str):
        events.append(json.loads(line.strip()))

    with patch.object(wire, "log", lambda text: None):
        with patch.object(wire, "emit_line", capture):
            # First permit succeeds
            await wire.handle_command(
                {
                    "cmd": "permit",
                    "tool_call_id": "tc-1",
                    "approval_id": "apr-001",
                    "thread_id": "thread-a",
                    "run_id": "run-1",
                },
                runner,
                ReplConfig(),
                {"turn": None},
            )
            # Second permit for same approval → consumed → rejected
            await wire.handle_command(
                {
                    "cmd": "permit",
                    "tool_call_id": "tc-1",
                    "approval_id": "apr-001",
                    "thread_id": "thread-a",
                    "run_id": "run-1",
                },
                runner,
                ReplConfig(),
                {"turn": None},
            )

    assert runner.inbound.permit.call_count == 1  # Only first resolved
    resolved = [e for e in events if e.get("method") == "approval/resolved"]
    assert len(resolved) == 2
    assert resolved[0]["params"]["status"] == "approved"
    assert resolved[1]["params"]["status"] == "expired"


@pytest.mark.asyncio
async def test_permit_without_scope_rejected():
    """Missing approval_id is REJECTED (fail-closed), not legacy-permitted."""
    runner = _make_runner("thread-a")
    events: list[dict] = []

    def capture(line: str):
        events.append(json.loads(line.strip()))

    with patch.object(wire, "log", lambda text: None):
        with patch.object(wire, "emit_line", capture):
            await wire.handle_command(
                {"cmd": "permit", "tool_call_id": "tc-1"},
                runner,
                ReplConfig(),
                {"turn": None},
            )

    runner.inbound.permit.assert_not_called()
    resolved = [e for e in events if e.get("method") == "approval/resolved"]
    assert len(resolved) == 1
    assert resolved[0]["params"]["status"] == "expired"


@pytest.mark.asyncio
async def test_permit_missing_tool_call_id_rejected():
    """Missing tool_call_id must be logged, not executed."""
    runner = _make_runner("thread-a")
    with patch.object(wire, "log", lambda text: None):
        await wire.handle_command(
            {"cmd": "permit"},
            runner,
            ReplConfig(),
            {"turn": None},
        )
    runner.inbound.permit.assert_not_called()


# ── Cancel semantics: user cancel → CANCELLED, not FAILED ──────────────


@pytest.mark.asyncio
async def test_run_user_turn_cancelled_stop_reason_marks_cancelled():
    """A run ending with stop_reason=cancelled must produce CANCELLED."""
    from electromind.core.events import RunEnd

    runner = _make_runner("thread-a")
    session = wire._harness_manager._get_or_create("thread-a")
    session.active_run_id = "run-1"
    session.active_run_phase = "running"

    async def fake_run(text, return_type="event"):
        del text, return_type
        yield RunEnd(0, stop_reason="cancelled")

    runner.run = fake_run

    with (
        patch.object(wire, "emit_line", lambda line: None),
        patch.object(wire, "install_subagent_observer", lambda r, s: lambda: None),
        patch.object(wire, "log", lambda text: None),
    ):
        await wire.run_user_turn(
            runner, "task", ReplConfig(), {"turn": None, "thread_id": "thread-a"}
        )

    assert session.active_run_phase == "cancelled"
    assert session.status == "idle"


@pytest.mark.asyncio
async def test_run_user_turn_cancelled_error_marks_cancelled():
    """A task.cancel() (CancelledError) must produce CANCELLED, not FAILED."""
    import asyncio

    from electromind.core.events import RunEnd

    runner = _make_runner("thread-a")
    session = wire._harness_manager._get_or_create("thread-a")
    session.active_run_id = "run-1"
    session.active_run_phase = "running"

    async def fake_run(text, return_type="event"):
        del text, return_type
        yield RunEnd(0, stop_reason="cancelled")
        raise asyncio.CancelledError()

    runner.run = fake_run

    with (
        patch.object(wire, "emit_line", lambda line: None),
        patch.object(wire, "install_subagent_observer", lambda r, s: lambda: None),
        patch.object(wire, "log", lambda text: None),
    ):
        try:
            await wire.run_user_turn(
                runner, "task", ReplConfig(), {"turn": None, "thread_id": "thread-a"}
            )
        except asyncio.CancelledError:
            pass  # Expected: propagates after marking cancelled

    assert session.active_run_phase == "cancelled"


@pytest.mark.asyncio
async def test_run_user_turn_error_marks_failed():
    """An unexpected error must produce FAILED."""
    from electromind.core.events import RunEnd

    runner = _make_runner("thread-a")
    session = wire._harness_manager._get_or_create("thread-a")
    session.active_run_id = "run-1"
    session.active_run_phase = "running"

    async def fake_run(text, return_type="event"):
        del text, return_type
        yield RunEnd(0, stop_reason="error")
        raise RuntimeError("boom")

    runner.run = fake_run

    with (
        patch.object(wire, "emit_line", lambda line: None),
        patch.object(wire, "install_subagent_observer", lambda r, s: lambda: None),
        patch.object(wire, "log", lambda text: None),
    ):
        await wire.run_user_turn(
            runner, "task", ReplConfig(), {"turn": None, "thread_id": "thread-a"}
        )

    assert session.active_run_phase == "failed"


# ── Frozen queue policy: cancel only stops the CURRENT run ─────────────


@pytest.mark.asyncio
async def test_cancel_runend_path_auto_starts_queued_input():
    """Frozen policy: RunEnd(cancelled) still auto-starts queued inputs."""
    import asyncio

    from electromind.core.events import RunEnd
    from electromind.harness.inbound import InputMessage

    runner = _make_runner("thread-a")
    session = wire._harness_manager._get_or_create("thread-a")
    session.active_run_id = "run-1"
    session.active_run_phase = "running"
    # Queue a next input before the run ends
    queued = InputMessage.create("thread-a", "next task", delivery="enqueue")
    session.queued_inputs.enqueue(queued)

    _calls = 0

    async def fake_run(text, return_type="event"):
        nonlocal _calls
        _calls += 1
        del text, return_type
        yield RunEnd(0, stop_reason="cancelled")
        if _calls == 1:
            return  # Parent ends cleanly
        await asyncio.sleep(30)  # Child stays alive for assertions

    runner.run = fake_run
    state: dict = {"turn": None, "thread_id": "thread-a"}

    with (
        patch.object(wire, "emit_line", lambda line: None),
        patch.object(wire, "install_subagent_observer", lambda r, s: lambda: None),
        patch.object(wire, "log", lambda text: None),
    ):
        await wire.run_user_turn(runner, "task", ReplConfig(), state)

    # The cancelled run was replaced by the next queued input (RUNNING).
    # The intermediate CANCELLED phase is not observable after auto-start.
    assert session.active_run_id != "run-1"
    assert session.active_run_phase == "running"
    # The auto-start path runs the FULL creation flow (Gate 1, 一-7):
    # a RunSnapshot is frozen for the new Run before its turn starts.
    snapshot = session.run_snapshot
    assert snapshot is not None, "auto-start must freeze a RunSnapshot"
    assert snapshot.run_id == session.active_run_id
    assert snapshot.input_message_id == queued.message_id
    assert snapshot.system_prompt_digest != ""
    # Turn was re-registered with a REAL asyncio.Task, still alive
    child = state["_turns"]["thread-a"]
    assert isinstance(child, asyncio.Task), f"expected real Task, got {type(child)}"
    assert not child.done()

    # Cleanup: cancel + await the child to avoid leaked coroutines
    child.cancel()
    try:
        await child
    except BaseException:
        pass


@pytest.mark.asyncio
async def test_cancel_taskcancel_path_auto_starts_queued_input():
    """Frozen policy: task.cancel() path ALSO auto-starts queued inputs."""
    import asyncio

    from electromind.core.events import RunEnd
    from electromind.harness.inbound import InputMessage

    runner = _make_runner("thread-a")
    session = wire._harness_manager._get_or_create("thread-a")
    session.active_run_id = "run-1"
    session.active_run_phase = "running"
    queued = InputMessage.create("thread-a", "next task", delivery="enqueue")
    session.queued_inputs.enqueue(queued)

    _calls = 0

    async def fake_run(text, return_type="event"):
        nonlocal _calls
        _calls += 1
        del text, return_type
        yield RunEnd(0, stop_reason="cancelled")
        if _calls == 1:
            raise asyncio.CancelledError()  # Parent cancelled
        await asyncio.sleep(30)  # Child survives, stays alive

    runner.run = fake_run
    state: dict = {"turn": None, "thread_id": "thread-a"}

    with (
        patch.object(wire, "emit_line", lambda line: None),
        patch.object(wire, "install_subagent_observer", lambda r, s: lambda: None),
        patch.object(wire, "log", lambda text: None),
    ):
        try:
            await wire.run_user_turn(runner, "task", ReplConfig(), state)
        except asyncio.CancelledError:
            pass

    # Both cancel paths behave identically: current CANCELLED, next RUNNING.
    # The child task is a REAL Task that SURVIVED the parent's CancelledError.
    assert session.active_run_id != "run-1"
    assert session.active_run_phase == "running"
    child = state["_turns"]["thread-a"]
    assert isinstance(child, asyncio.Task), f"expected real Task, got {type(child)}"
    assert not child.done(), "child run must survive parent cancellation"

    # Cleanup: cancel + await the child to avoid leaked coroutines
    child.cancel()
    try:
        await child
    except BaseException:
        pass


@pytest.mark.asyncio
async def test_failure_does_not_auto_start_queued_input():
    """Failures do NOT auto-start queued inputs (avoids failure loops)."""
    from electromind.core.events import RunEnd
    from electromind.harness.inbound import InputMessage

    runner = _make_runner("thread-a")
    session = wire._harness_manager._get_or_create("thread-a")
    session.active_run_id = "run-1"
    session.active_run_phase = "running"
    queued = InputMessage.create("thread-a", "next task", delivery="enqueue")
    session.queued_inputs.enqueue(queued)

    async def fake_run(text, return_type="event"):
        del text, return_type
        yield RunEnd(0, stop_reason="error")
        raise RuntimeError("boom")

    runner.run = fake_run
    state: dict = {"turn": None, "thread_id": "thread-a"}

    with (
        patch.object(wire, "emit_line", lambda line: None),
        patch.object(wire, "install_subagent_observer", lambda r, s: lambda: None),
        patch.object(wire, "log", lambda text: None),
    ):
        await wire.run_user_turn(runner, "task", ReplConfig(), state)

    # Run FAILED and the queued input stays queued
    assert session.active_run_phase == "failed"
    assert len(session.queued_inputs) == 1
    assert session.queued_inputs.peek().message_id == queued.message_id


# ── Run termination expires pending approvals ──────────────────────────


@pytest.mark.asyncio
async def test_complete_run_expires_approvals():
    """Approvals are expired + removed when the Run completes."""
    mgr = wire._harness_manager
    await _register_approval("thread-a", "run-1", "apr-001", "tc-1")

    ok = await mgr.complete_run("thread-a", "run-1")
    assert ok

    session = mgr.get_session("thread-a")
    assert len(session.pending_approvals) == 0
    # Expired approvals are available for event emission
    expired = await mgr.take_expired_approvals("thread-a")
    assert len(expired) == 1
    assert expired[0].approval_id == "apr-001"
    assert str(expired[0].status) == "expired"

    # Snapshot shows no pending approvals
    snap = await mgr.get_snapshot("thread-a")
    assert snap["pending_approval_count"] == 0
    assert snap["pending_approvals"] == []


@pytest.mark.asyncio
async def test_cancel_run_expires_approvals():
    """Approvals are expired + removed when the Run is cancelled."""
    mgr = wire._harness_manager
    await _register_approval("thread-a", "run-1", "apr-001", "tc-1")

    ok = await mgr.cancel_run("thread-a", "run-1")
    assert ok

    session = mgr.get_session("thread-a")
    assert len(session.pending_approvals) == 0
    expired = await mgr.take_expired_approvals("thread-a")
    assert len(expired) == 1
    assert str(expired[0].status) == "expired"


@pytest.mark.asyncio
async def test_fail_run_expires_approvals():
    """Approvals are expired + removed when the Run fails."""
    mgr = wire._harness_manager
    await _register_approval("thread-a", "run-1", "apr-001", "tc-1")

    ok = await mgr.fail_run("thread-a", "run-1")
    assert ok

    session = mgr.get_session("thread-a")
    assert len(session.pending_approvals) == 0
    expired = await mgr.take_expired_approvals("thread-a")
    assert len(expired) == 1
    assert str(expired[0].status) == "expired"


@pytest.mark.asyncio
async def test_approval_cannot_resolve_after_cancel():
    """After cancel, resolving the old approval must fail (phase check)."""
    mgr = wire._harness_manager
    await _register_approval("thread-a", "run-1", "apr-001", "tc-1")

    await mgr.cancel_run("thread-a", "run-1")

    # Even with the right run_id, resolution is blocked (phase = cancelled)
    resolved = await mgr.resolve_approval(
        "thread-a", "run-1", "apr-001", True, tool_call_id="tc-1"
    )
    assert resolved is None


@pytest.mark.asyncio
async def test_snapshot_excludes_expired_approvals():
    """A snapshot after Run end must not contain the expired approvals."""
    mgr = wire._harness_manager
    await _register_approval("thread-a", "run-1", "apr-001", "tc-1")
    await mgr.complete_run("thread-a", "run-1")

    snap = await mgr.get_snapshot("thread-a")
    assert snap["pending_approval_count"] == 0
    assert snap["pending_approvals"] == []
    # Expired approvals are queued for event emission and drained by wire
    expired = await mgr.take_expired_approvals("thread-a")
    assert len(expired) == 1
    assert str(expired[0].status) == "expired"
    # After draining, nothing remains
    assert await mgr.take_expired_approvals("thread-a") == []


# ── Production entry: emit_permit_request registers the approval ──────


@pytest.mark.asyncio
async def test_emit_permit_request_registers_before_emitting():
    """The REAL production path (async emit_permit_request) must register
    the approval in pending_approvals BEFORE the PermitRequest event."""

    from electromind.core.events import ToolCallBegin

    # Set up session with active run (as run_user_turn does)
    session = wire._harness_manager._get_or_create("thread-a")
    session.active_run_id = "run-1"
    session.active_run_phase = "running"

    event = ToolCallBegin("tc-1", "run_command", '{"cmd":"ls"}')
    events: list[dict] = []

    def capture(line: str):
        events.append(json.loads(line.strip()))

    with patch.object(wire, "emit_line", capture):
        ok = await wire.emit_permit_request(
            event,
            thread_id="thread-a",
            run_id="run-1",
        )

    assert ok
    # Approval is registered in the harness session
    assert len(session.pending_approvals) == 1
    approval_id, approval = next(iter(session.pending_approvals.items()))
    assert approval_id.startswith("apr-")
    assert approval.tool_call_id == "tc-1"
    assert approval.run_id == "run-1"
    # PermitRequest event carries the same approval_id
    permits = [e for e in events if e.get("method") == "PermitRequest"]
    assert len(permits) == 1
    assert permits[0]["params"]["approval_id"] == approval_id
    assert permits[0]["params"]["tool_call_id"] == "tc-1"
    assert permits[0]["params"]["thread_id"] == "thread-a"
    assert permits[0]["params"]["run_id"] == "run-1"


@pytest.mark.asyncio
async def test_emit_permit_request_failure_does_not_emit():
    """If registration fails, no PermitRequest may reach the client."""

    from electromind.core.events import ToolCallBegin

    event = ToolCallBegin("tc-1", "run_command", "{}")
    events: list[dict] = []

    def capture(line: str):
        events.append(json.loads(line.strip()))

    # No session for "unknown-thread" → add_approval returns False
    with patch.object(wire, "emit_line", capture):
        ok = await wire.emit_permit_request(
            event,
            thread_id="unknown-thread",
            run_id="run-1",
        )

    assert not ok
    permits = [e for e in events if e.get("method") == "PermitRequest"]
    assert len(permits) == 0


# ── Wrong tool_call_id must NOT consume the approval ──────────────────


@pytest.mark.asyncio
async def test_wrong_tool_call_does_not_consume_approval():
    """A wrong tool_call_id attempt must not invalidate the legitimate
    approval — a later correct permit still succeeds."""
    runner = _make_runner("thread-a")
    await _register_approval("thread-a", "run-1", "apr-001", "tc-A")

    # Attempt with the WRONG tool_call_id
    with patch.object(wire, "log", lambda text: None):
        await wire.handle_command(
            {
                "cmd": "permit",
                "tool_call_id": "tc-B",  # Wrong
                "approval_id": "apr-001",
                "thread_id": "thread-a",
                "run_id": "run-1",
            },
            runner,
            ReplConfig(),
            {"turn": None},
        )
    runner.inbound.permit.assert_not_called()

    # Approval must still be registered (not consumed)
    session = wire._harness_manager.get_session("thread-a")
    assert "apr-001" in session.pending_approvals

    # Retry with the CORRECT tool_call_id → succeeds
    await wire.handle_command(
        {
            "cmd": "permit",
            "tool_call_id": "tc-A",
            "approval_id": "apr-001",
            "thread_id": "thread-a",
            "run_id": "run-1",
        },
        runner,
        ReplConfig(),
        {"turn": None},
    )
    runner.inbound.permit.assert_called_once_with("tc-A")


# ── Gate 1, 八 — auto-start workspace lease & RunSnapshot creation flow ──


@pytest.mark.asyncio
async def test_auto_start_acquires_workspace_lease():
    """An auto-started Run acquires the workspace write lease exactly like
    the first Run (regression: auto-start skipped the lease entirely)."""
    import asyncio

    from electromind.core.events import RunEnd
    from electromind.harness.identity import WorkspaceKey
    from electromind.harness.inbound import InputMessage

    runner = _make_runner("thread-a")
    runner.sandbox = SimpleNamespace(workdir="/work/a", backend=None)
    session = wire._harness_manager._get_or_create("thread-a")
    session.active_run_id = "run-1"
    session.active_run_phase = "running"
    queued = InputMessage.create("thread-a", "next task", delivery="enqueue")
    session.queued_inputs.enqueue(queued)

    _calls = 0

    async def fake_run(text, return_type="event"):
        nonlocal _calls
        _calls += 1
        del text, return_type
        yield RunEnd(0, stop_reason="completed")
        if _calls == 1:
            return  # Parent ends cleanly
        await asyncio.sleep(30)  # Child stays alive for assertions

    runner.run = fake_run
    state: dict = {"turn": None, "thread_id": "thread-a"}

    with (
        patch.object(wire, "emit_line", lambda line: None),
        patch.object(wire, "install_subagent_observer", lambda r, s: lambda: None),
        patch.object(wire, "log", lambda text: None),
    ):
        await wire.run_user_turn(runner, "task", ReplConfig(), state)

    new_run = session.active_run_id
    assert new_run != "run-1"
    assert session.active_run_phase == "running"
    # The write lease is held by the auto-started Run (Gate 1, 八)
    holder = wire._harness_manager.workspace_holder(
        WorkspaceKey(execution_target_id="local", canonical_workdir="/work/a")
    )
    assert holder == (new_run, "thread-a"), f"lease not held by new run: {holder}"
    # RunSnapshot frozen with the workspace-backed execution target
    assert session.run_snapshot is not None
    assert session.run_snapshot.run_id == new_run

    # Cleanup: cancel the child and release the lease
    child = state["_turns"]["thread-a"]
    child.cancel()
    try:
        await child
    except BaseException:
        pass
    await wire._harness_manager.release_workspace("thread-a", new_run)


@pytest.mark.asyncio
async def test_auto_start_waits_on_workspace_conflict():
    """Workspace conflict blocks auto-start: the input stays queued and no
    second Run is born (regression: auto-start bypassed the lease)."""

    from electromind.core.events import RunEnd
    from electromind.harness.identity import WorkspaceKey
    from electromind.harness.inbound import InputMessage
    from electromind.harness.state import SessionMode

    runner = _make_runner("thread-a")
    runner.sandbox = SimpleNamespace(workdir="/work/a", backend=None)
    session = wire._harness_manager._get_or_create("thread-a")
    session.active_run_id = "run-1"
    session.active_run_phase = "running"
    queued = InputMessage.create("thread-a", "next task", delivery="enqueue")
    session.queued_inputs.enqueue(queued)

    # Another thread holds the write lease for the same workspace
    assert await wire._harness_manager.try_acquire_workspace(
        "thread-b",
        WorkspaceKey(execution_target_id="local", canonical_workdir="/work/a"),
        "run-other",
        SessionMode.RUN,
    )

    _calls = 0

    async def fake_run(text, return_type="event"):
        nonlocal _calls
        _calls += 1
        del text, return_type
        yield RunEnd(0, stop_reason="completed")

    runner.run = fake_run
    state: dict = {"turn": None, "thread_id": "thread-a"}

    with (
        patch.object(wire, "emit_line", lambda line: None),
        patch.object(wire, "install_subagent_observer", lambda r, s: lambda: None),
        patch.object(wire, "log", lambda text: None),
    ):
        await wire.run_user_turn(runner, "task", ReplConfig(), state)

    # No auto-start: the old run ended, the input stays queued for later
    assert session.active_run_id == "run-1"
    assert session.active_run_phase == "completed"
    assert len(session.queued_inputs) == 1  # still queued
    assert session.run_snapshot is None  # no new snapshot was frozen
    # No new turn task was spawned
    turns: dict = state["_turns"]
    assert turns.get("thread-a") is None

    await wire._harness_manager.release_workspace("thread-b", "run-other")


# ── Gate 1, 一-7 — RunSnapshot captures REAL system/tools/skills ──────────


@pytest.mark.asyncio
async def test_run_snapshot_captures_real_system_tools_skills():
    """_build_run_snapshot must freeze the REAL system prompt, tool names
    and the skill-set digest (regression: all three digests were empty)."""
    import hashlib

    def digest(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] if text else ""

    class FakeTool:
        def __init__(self, name: str):
            self.name = name

    runner = _make_runner("thread-a")
    runner.agent = SimpleNamespace(
        system="real assembled system prompt",
        tools=[FakeTool("write_file"), FakeTool("bash")],
    )
    set_snapshot = SimpleNamespace(digest="skill-set-digest-abc")
    runner.skill_runtime = SimpleNamespace(_set_snapshot=set_snapshot)

    snap = wire._build_run_snapshot(
        runner,
        ReplConfig(),
        "run-1",
        "thread-a",
        "msg-1",
    )
    # system prompt and tools come from runner.agent (BaseRunner layout)
    assert snap.system_prompt_digest == digest("real assembled system prompt")
    assert snap.tool_set_digest == digest("bash\nwrite_file")  # sorted names
    assert snap.skill_set_digest == "skill-set-digest-abc"  # ready-made digest

    # Without a skill runtime the digest falls back to the generation
    runner.skill_runtime = SimpleNamespace(_set_snapshot=None, _generation=3)
    snap2 = wire._build_run_snapshot(
        runner,
        ReplConfig(),
        "run-2",
        "thread-a",
        "msg-2",
    )
    assert snap2.skill_set_digest == digest("3")


# ── Audit closure 3: IMMEDIATE→checkpoint steer, session mode, mutation ──


@pytest.mark.asyncio
async def test_immediate_input_steered_to_runner_checkpoint():
    """An IMMEDIATE input during an active Run is delivered to the runner's
    inbound mailbox (applied at the next safe checkpoint) — not parked in
    pending_immediate until Run end (regression: wire never called steer)."""
    from unittest.mock import AsyncMock

    runner = _make_runner("thread-a")
    runner.inbound = MagicMock()
    runner.inbound.steer = MagicMock()
    session = wire._harness_manager._get_or_create("thread-a")
    session.active_run_id = "run-1"
    session.active_run_phase = "running"

    with (
        patch.object(wire, "log", lambda *a, **k: None),
        patch.object(wire, "touch_thread_metainfo", lambda *a, **k: None),
        # start_run is a slots attribute — patch at class level so the
        # "user" branch below short-circuits after steering happened
        patch.object(
            type(wire._harness_manager),
            "start_run",
            AsyncMock(return_value=None),
        ),
        patch.object(wire, "_persist_thread_state", lambda *a, **k: None),
    ):
        await wire.handle_command(
            {
                "cmd": "input/send",
                "text": "steer me",
                "delivery": "immediate",
                "thread_id": "thread-a",
            },
            runner,
            ReplConfig(),
            {"turn": None, "thread_id": "thread-a"},
        )

    # The message went into the Runner's mailbox AND stays durably in
    # pending_immediate (persisted) until the Run settles it — a crash
    # between steer and checkpoint must not lose it.
    # Steer carries the harness message_id for exact settle
    mid = session.pending_immediate[0].message_id
    runner.inbound.steer.assert_called_once_with("steer me", message_id=mid)
    assert len(session.pending_immediate) == 1


def test_session_mode_from_config_and_requested_mode():
    """_session_mode_for honors config.session_mode (ask|plan|run); the
    per-input requested mode wins for lease/snapshot decisions (regression:
    only command_policy==ask was ever read → plan ran with write power)."""
    from electromind.harness.state import SessionMode

    assert wire._session_mode_for(ReplConfig(session_mode="plan")) == SessionMode.PLAN
    assert wire._session_mode_for(ReplConfig(session_mode="ask")) == SessionMode.ASK
    assert wire._session_mode_for(ReplConfig(session_mode="run")) == SessionMode.RUN
    assert wire._session_mode_for(ReplConfig()) == SessionMode.RUN
    # UI requested mode beats config for the lease decision
    assert wire._resolved_session_mode(ReplConfig(), SessionMode.ASK) == SessionMode.ASK
    assert (
        wire._resolved_session_mode(ReplConfig(), SessionMode.PLAN) == SessionMode.PLAN
    )
    assert (
        wire._resolved_session_mode(ReplConfig(session_mode="plan"), None)
        == SessionMode.PLAN
    )


@pytest.mark.asyncio
async def test_failed_mutation_recorded_as_inexact(tmp_path):
    """A write tool that fails AFTER touching the disk still records an
    INEXACT mutation (regression: exceptions skipped the after-capture and
    the mutation vanished from the tracker entirely)."""
    from types import SimpleNamespace

    from electromind.core.events import RunEnd

    target = tmp_path / "f.txt"
    target.write_text("original", encoding="utf-8")

    runner = _make_runner("thread-a")

    async def fake_read(path):
        p = tmp_path / path
        if not p.is_file():
            raise FileNotFoundError(path)
        return p.read_bytes()

    runner.sandbox = SimpleNamespace(
        workdir="/w",
        backend=None,
        host_root=str(tmp_path),
        files=SimpleNamespace(read=fake_read),
    )
    _calls = {"n": 0}

    async def failing_write(tool_call):
        del tool_call
        # Partial write, THEN failure — the classic dangerous path
        target.write_text("partial write", encoding="utf-8")
        raise RuntimeError("tool exploded")

    runner.execute_tool = failing_write

    async def fake_run(text, return_type="event"):
        del text, return_type
        from electromind.core.events import ToolCallBegin

        yield ToolCallBegin(
            tool_call_id="tc-1", name="write_file", arguments='{"path": "f.txt"}'
        )
        try:
            await runner.execute_tool(
                SimpleNamespace(
                    name="write_file", arguments='{"path": "f.txt"}', id="tc-1"
                )
            )
        except RuntimeError:
            pass
        yield RunEnd(0, stop_reason="completed")

    runner.run = fake_run
    state: dict = {"turn": None, "thread_id": "thread-a"}

    with (
        patch.object(wire, "emit_line", lambda line: None),
        patch.object(wire, "install_subagent_observer", lambda r, s: lambda: None),
        patch.object(wire, "log", lambda text: None),
    ):
        await wire.run_user_turn(runner, "task", ReplConfig(), state)

    # The partial mutation was captured and tracked as INEXACT
    tracker = state["_mutation_trackers"]["thread-a"]
    net = tracker.net_change("sandbox", "f.txt", "")
    assert net is not None, "failed mutation must be recorded"
    assert net["exact"] is False
    assert net["after"]["sha256"] != net["before"]["sha256"]  # Disk DID change


# ── Audit closure 4: settle-on-RunEnd identity, snapshot-failure mutation ──


@pytest.mark.asyncio
async def test_unread_steer_deferred_with_original_identity():
    """A steer the Run never consumed is re-queued with its ORIGINAL
    message_id at Run end (regression: a NEW InputMessage was created,
    changing identity and stranding the receipt at immediate_pending)."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from electromind.core.events import RunEnd

    runner = _make_runner("thread-a")

    def drain():
        # Unread steers carry their harness message_id (exact identity)
        mids = [m.message_id for m in session.pending_immediate]
        texts = [m.text for m in session.pending_immediate]
        return SimpleNamespace(steers=tuple(texts), steer_ids=tuple(mids))

    runner.inbound = SimpleNamespace(steer=lambda text, **kw: None, drain=drain)
    session = wire._harness_manager._get_or_create("thread-a")
    session.active_run_id = "run-1"
    session.active_run_phase = "running"

    async def fake_run(text, return_type="event"):
        del text, return_type
        yield RunEnd(0, stop_reason="completed")

    runner.run = fake_run
    state: dict = {"turn": None, "thread_id": "thread-a"}
    acks: list[dict] = []

    def capture_ack(message_id, thread_id, ack_state, **kwargs):
        acks.append(
            {
                "message_id": message_id,
                "state": ack_state,
                "detail": kwargs.get("detail", ""),
            }
        )

    with (
        patch.object(wire, "emit_line", lambda line: None),
        patch.object(wire, "install_subagent_observer", lambda r, s: lambda: None),
        patch.object(wire, "log", lambda text: None),
        patch.object(wire, "_emit_input_state_ack", capture_ack),
        # Keep the "user" branch from starting a real second Run
        patch.object(
            type(wire._harness_manager),
            "start_run",
            AsyncMock(return_value=None),
        ),
    ):
        # Route an IMMEDIATE message into the active run (it gets steered)
        await wire.handle_command(
            {
                "cmd": "input/send",
                "text": "steer me",
                "delivery": "immediate",
                "thread_id": "thread-a",
            },
            runner,
            ReplConfig(),
            state,
        )
        assert len(session.pending_immediate) == 1
        original_id = session.pending_immediate[0].message_id

        await wire.run_user_turn(runner, "task", ReplConfig(), state)

    # The unread steer was deferred with its ORIGINAL identity
    assert len(session.queued_inputs) == 1
    deferred = session.queued_inputs.peek()
    assert deferred.message_id == original_id
    assert deferred.text == "steer me"
    assert len(session.pending_immediate) == 0
    # Terminal ACK for the deferred message (no longer stuck pending)
    deferred_acks = [a for a in acks if a["state"] == "deferred"]
    assert len(deferred_acks) == 1
    assert deferred_acks[0]["message_id"] == original_id


@pytest.mark.asyncio
async def test_snapshot_read_failure_still_records_inexact(tmp_path):
    """A snapshot read error (SSH down etc.) must NOT make the mutation
    vanish: the tool still executes and the delta is recorded INEXACT
    (regression: MutationSnapshotError → None → no tracking at all)."""
    from types import SimpleNamespace

    from app.wire import MutationSnapshotError
    from electromind.core.events import RunEnd

    runner = _make_runner("thread-a")

    async def failing_read(path):
        del path
        raise MutationSnapshotError("ssh down")

    runner.sandbox = SimpleNamespace(
        workdir="/w",
        backend=None,
        host_root=str(tmp_path),
        files=SimpleNamespace(read=failing_read),
    )
    executed = {"n": 0}

    async def ok_write(tool_call):
        del tool_call
        executed["n"] += 1
        return SimpleNamespace(ok=True)

    runner.execute_tool = ok_write

    async def fake_run(text, return_type="event"):
        del text, return_type
        yield RunEnd(0, stop_reason="completed")
        from types import SimpleNamespace as SN

        await runner.execute_tool(
            SN(name="write_file", arguments='{"path": "f.txt"}', id="tc-1")
        )

    runner.run = fake_run
    state: dict = {"turn": None, "thread_id": "thread-a"}

    with (
        patch.object(wire, "emit_line", lambda line: None),
        patch.object(wire, "install_subagent_observer", lambda r, s: lambda: None),
        patch.object(wire, "log", lambda text: None),
    ):
        await wire.run_user_turn(runner, "task", ReplConfig(), state)

    assert executed["n"] == 1  # The tool ran despite the read failure
    tracker = state["_mutation_trackers"]["thread-a"]
    net = tracker.net_change("sandbox", "f.txt", "")
    assert net is not None, "snapshot-failed mutation must still be recorded"
    assert net["exact"] is False  # Cannot verify — never silently dropped
