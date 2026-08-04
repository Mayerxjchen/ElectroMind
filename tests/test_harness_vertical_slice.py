"""Vertical slice integration: Desktop Composer → input/send → ACK → Runner.

Verifies that the harness ThreadSessionManager is wired into the wire transport,
producing observable input/state ACKs and thread/snapshot responses.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app import wire
from app.config import ReplConfig

# ============================================================================
# input/send → input/state ACK
# ============================================================================


@pytest.mark.asyncio
async def test_input_send_empty_rejected():
    """Empty input via input/send → rejected ACK (no runner needed)."""
    events: list[dict] = []

    def capture(line: str):
        events.append(json.loads(line.strip()))

    with patch.object(wire, "emit_line", capture):
        await wire.handle_command(
            {"cmd": "input/send", "text": ""},
            None,
            ReplConfig(),
            {"turn": None},
        )

    input_events = [e for e in events if e.get("method") == "input/state"]
    assert len(input_events) == 1
    ack = input_events[0]["params"]
    assert ack["state"] == "rejected"


@pytest.mark.asyncio
async def test_input_send_accepted():
    """Valid input via input/send → queued ACK with message_id."""
    events: list[dict] = []

    def capture(line: str):
        events.append(json.loads(line.strip()))

    with patch.object(wire, "emit_line", capture):
        await wire.handle_command(
            {"cmd": "input/send", "text": "compute energy"},
            None,
            ReplConfig(),
            {"turn": None, "thread_id": "thread-test"},
        )

    input_events = [e for e in events if e.get("method") == "input/state"]
    assert len(input_events) == 1
    ack = input_events[0]["params"]
    assert ack["state"] in ("accepted", "queued")
    assert ack["message_id"].startswith("msg-")
    # thread_id may be empty if state has no thread_id set yet


@pytest.mark.asyncio
async def test_input_send_then_user_flow():
    """input/send rewrites to 'user' cmd; ensure_runner path still works."""
    runner = MagicMock()
    runner.thread.id = "thread-1"

    async def fake_ensure(r, cfg, st):
        return runner

    events: list[dict] = []

    def capture(line: str):
        events.append(json.loads(line.strip()))

    with (
        patch.object(wire, "ensure_runner", fake_ensure),
        patch.object(wire, "emit_current_thread", lambda r: None),
        patch.object(wire, "emit_execution_state", lambda r: None),
        patch.object(wire, "emit_execution_context", lambda r: None),
        patch.object(wire, "emit_history_replay", lambda r: None),
        patch.object(wire, "touch_thread_metainfo", lambda r, t: None),
        patch.object(wire, "emit_line", capture),
    ):
        result = await wire.handle_command(
            {"cmd": "input/send", "text": "hello"},
            None,
            ReplConfig(),
            {"turn": None},
        )
        assert result is runner

    # Should have input/state ACK
    methods = {e.get("method") for e in events}
    assert "input/state" in methods


# ============================================================================
# thread/snapshot
# ============================================================================


@pytest.mark.asyncio
async def test_thread_snapshot_nonexistent():
    """Snapshot of a nonexistent thread returns exists=False."""
    events: list[dict] = []

    def capture(line: str):
        events.append(json.loads(line.strip()))

    with patch.object(wire, "emit_line", capture):
        await wire.handle_command(
            {"cmd": "thread/snapshot", "thread_id": "no-such-thread"},
            None,
            ReplConfig(),
            {"turn": None},
        )

    snap_events = [e for e in events if e.get("method") == "thread/snapshot"]
    assert len(snap_events) == 1
    snap = snap_events[0]["params"]
    assert snap["thread_id"] == "no-such-thread"
    assert snap["exists"] is False


# ============================================================================
# Backward compatibility: old commands still work
# ============================================================================


@pytest.mark.asyncio
async def test_old_user_command_still_works():
    """The existing 'user' command handler must not be broken."""
    runner = MagicMock()
    runner.thread.id = "thread-old"

    async def fake_ensure(r, cfg, st):
        return runner

    with (
        patch.object(wire, "ensure_runner", fake_ensure),
        patch.object(wire, "emit_current_thread", lambda r: None),
        patch.object(wire, "emit_execution_state", lambda r: None),
        patch.object(wire, "emit_execution_context", lambda r: None),
        patch.object(wire, "emit_history_replay", lambda r: None),
        patch.object(wire, "touch_thread_metainfo", lambda r, t: None),
    ):
        result = await wire.handle_command(
            {"cmd": "user", "text": "hello"},
            None,
            ReplConfig(),
            {"turn": None},
        )
        assert result is runner


@pytest.mark.asyncio
async def test_cancel_command_still_works():
    """The existing 'cancel' command must not be broken."""
    runner = MagicMock()
    runner.cancel_run = MagicMock()

    with patch.object(wire, "_turn_active_for_thread", lambda s, tid: True):
        result = await wire.handle_command(
            {"cmd": "cancel"},
            runner,
            ReplConfig(),
            {"turn": object(), "thread_id": "thread-test", "_turns": {}},
        )
        assert result is runner
        runner.cancel_run.assert_called_once()


# ============================================================================
# Per-thread parallel execution
# ============================================================================


@pytest.mark.asyncio
async def test_two_threads_run_in_parallel():
    """Start A's run → switch to B → send input to B → both are active."""
    import asyncio as _asyncio

    runner_a = MagicMock()
    runner_a.thread.id = "thread-a"
    runner_b = MagicMock()
    runner_b.thread.id = "thread-b"

    state: dict = {
        "turn": None,
        "thread_id": "thread-a",
        "_runners": {},
        "_turns": {},
    }

    # Simulate A's turn running (blocking event)
    a_running = _asyncio.Event()

    async def fake_run_a(*args, **kwargs):
        a_running.set()
        # Block forever (simulating active agent loop)
        await _asyncio.Event().wait()

    task_a = _asyncio.create_task(fake_run_a())
    wire._set_turn(state, "thread-a", task_a)
    # Wait for A's turn to start
    await a_running.wait()
    assert not task_a.done(), "A should be running"

    # Resume to B
    with (
        patch.object(wire, "open_thread_history", lambda tid, pp=None: runner_b.thread),
        patch.object(wire, "thread_is_soft_deleted", lambda meta: False),
        patch.object(wire, "emit_execution_state_cleared", lambda: None),
        patch.object(wire, "emit_thread_history_replay", lambda t: None),
    ):
        result = await wire.handle_command(
            {"cmd": "resume", "thread_id": "thread-b"},
            runner_a,
            ReplConfig(),
            state,
        )

    # A should still be running
    assert not task_a.done(), "A should still run after switching to B"
    # Runner A should be cached
    assert state.get("_runners", {}).get("thread-a") is runner_a

    # Now send input to B via input/send
    with (
        patch.object(wire, "ensure_runner", _fake_ensure_runner(runner_b)),
        patch.object(wire, "emit_current_thread", lambda r: None),
        patch.object(wire, "emit_execution_state", lambda r: None),
        patch.object(wire, "emit_execution_context", lambda r: None),
        patch.object(wire, "emit_history_replay", lambda r: None),
        patch.object(wire, "touch_thread_metainfo", lambda r, t: None),
    ):
        _result_b = await wire.handle_command(
            {"cmd": "input/send", "text": "hello from B"},
            result,  # result from resume (may be None or cached)
            ReplConfig(),
            state,
        )

    # B should now have its own turn running
    b_turn = wire._turn_active_for_thread(state, "thread-b")
    # Both A and B can be independently tracked
    a_still_running = not task_a.done()
    assert a_still_running, "A should still be running"
    # B's turn should have started (since B was idle when we sent input)
    assert state.get("_turns", {}).get("thread-b") is not None or b_turn, (
        "B should have started a turn"
    )

    # Cleanup: cancel A's turn
    task_a.cancel()
    try:
        await task_a
    except _asyncio.CancelledError:
        pass


def _fake_ensure_runner(target_runner):
    """Return an async fake for ensure_runner."""

    async def fake(r, cfg, st):
        return target_runner

    return fake
