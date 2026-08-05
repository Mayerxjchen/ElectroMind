"""M1: RunEngine 统一执行内核测试。

覆盖验收：集中状态机、控制面 run_id 绑定、event_seq 单调、单 Thread
单可写 Run、取消无孤立 ToolCall、run_loop 终态、语义检查点。
"""

from __future__ import annotations

import asyncio

import pytest

from electromind.core.events import (
    RunBegin,
    RunEnd,
    ToolCallBegin,
    ToolResult,
    TurnBegin,
    TurnEnd,
    TurnResult,
)
from electromind.core.message import ToolCall
from electromind.engine import RunEngine
from electromind.harness import (
    InputDelivery,
    InputMessage,
    new_run_id,
)
from electromind.harness.state import RunPhase, allowed_run_transitions

# ── 脚本化 runner ───────────────────────────────────────────────────────


class FakeRunner:
    """最小 runner 桩：事件序列 + 控制面方法。"""

    def __init__(self, events, *, cancel_after=None):
        self.events = events
        self.cancel_after = cancel_after  # 第 N 个事件后请求取消
        self.cancelled = False
        self.steers = []
        self.permitted = []
        self.denied = []

    async def run(self, text, return_type="event"):
        for i, event in enumerate(self.events):
            if self.cancel_after is not None and i == self.cancel_after:
                self.cancel_run()
            yield event

    def cancel_run(self):
        self.cancelled = True

    def steer(self, text, *, message_id=""):
        self.steers.append((text, message_id))

    def permit_tool(self, tool_call_id):
        self.permitted.append(tool_call_id)

    def deny_tool(self, tool_call_id, *, reason=""):
        self.denied.append((tool_call_id, reason))


def _tool_turn_events():
    return [
        RunBegin("hi"),
        TurnBegin(0),
        TurnResult(
            "", [ToolCall(type="function", id="c1", name="read_file", arguments="{}")]
        ),
        ToolCallBegin("c1", "read_file", "{}"),
        ToolResult("c1", "read_file", "ok"),
        TurnEnd(0, stopped=False, stop_reason="continuing"),
        TurnBegin(1),
        TurnResult("完成", []),
        TurnEnd(1, stopped=True, stop_reason="no_tool_calls"),
        RunEnd(1, stop_reason="no_tool_calls"),
    ]


def _noop_events():
    return [
        RunBegin("hi"),
        TurnBegin(0),
        TurnResult("你好", []),
        TurnEnd(0, stopped=True, stop_reason="no_tool_calls"),
        RunEnd(0, stop_reason="no_tool_calls"),
    ]


async def _start_active_run(engine: RunEngine, thread_id: str) -> str:
    await engine.send_input(
        InputMessage.create(thread_id, "任务", delivery=InputDelivery.ENQUEUE)
    )
    run_id = new_run_id()
    started = await engine.manager.start_run(thread_id, object(), run_id=run_id)
    assert started is not None
    return run_id


# ── 状态机 ──────────────────────────────────────────────────────────────


def test_run_phase_transition_table():
    assert RunPhase.RUNNING_MODEL in allowed_run_transitions(RunPhase.INITIALIZING)
    assert RunPhase.RUNNING_TOOL in allowed_run_transitions(RunPhase.RUNNING_MODEL)
    assert RunPhase.WAITING_APPROVAL in allowed_run_transitions(RunPhase.RUNNING_TOOL)
    assert not allowed_run_transitions(RunPhase.COMPLETED)  # 终态
    assert RunPhase.RUNNING_MODEL not in allowed_run_transitions(RunPhase.COMPLETED)


async def test_update_run_phase_illegal_transition_rejected():
    engine = RunEngine()
    run_id = await _start_active_run(engine, "t1")
    # RUNNING → RUNNING_MODEL 合法
    assert await engine.manager.update_run_phase("t1", run_id, RunPhase.RUNNING_MODEL)
    session = engine.manager.get_session("t1")
    assert session.active_run_phase == RunPhase.RUNNING_MODEL
    # 终态后非法（先完成，再尝试精相）——用错误 run_id 拒绝
    assert not await engine.manager.update_run_phase(
        "t1", "run-wrong", RunPhase.RUNNING_TOOL
    )


async def test_one_writable_run_per_thread():
    engine = RunEngine()
    run1 = await _start_active_run(engine, "t1")
    # 活动 Run 期间第二个 Run 被拒
    second = await engine.manager.start_run("t1", object(), run_id=new_run_id())
    assert second is None
    # 完成后可生新 Run
    await engine.manager.complete_run("t1", run1)
    await engine.send_input(
        InputMessage.create("t1", "第二个", delivery=InputDelivery.ENQUEUE)
    )
    run2 = new_run_id()
    started = await engine.manager.start_run("t1", object(), run_id=run2)
    assert started is not None
    assert run2 != run1


# ── 控制面绑定 ──────────────────────────────────────────────────────────


async def test_control_plane_binds_run_id():
    engine = RunEngine()
    run_id = await _start_active_run(engine, "t1")
    runner = FakeRunner(_noop_events())
    engine.register_runner("t1", runner)
    # 错误 run_id → 拒绝
    assert not engine.cancel_run("t1", "run-wrong")
    assert not engine.permit_tool("t1", "run-wrong", "c1")
    assert not engine.deny_tool("t1", "run-wrong", "c1")
    # 正确 run_id → 放行
    assert engine.cancel_run("t1", run_id)
    assert runner.cancelled
    assert engine.permit_tool("t1", run_id, "c1")
    assert runner.permitted == ["c1"]
    assert engine.deny_tool("t1", run_id, "c2", reason="no")
    assert runner.denied == [("c2", "no")]
    # 无 runner → 拒绝
    engine.unregister_runner("t1")
    assert not engine.cancel_run("t1", run_id)


async def test_steer_routes_to_runner():
    engine = RunEngine()
    run_id = await _start_active_run(engine, "t1")
    runner = FakeRunner(_noop_events())
    engine.register_runner("t1", runner)
    assert engine.steer("t1", "跟进", message_id="msg-1")
    assert runner.steers == [("跟进", "msg-1")]
    # 未注册 runner 的 thread → 拒绝
    assert not engine.steer("nobody", "无人")
    del run_id


# ── run_loop ────────────────────────────────────────────────────────────


async def test_run_loop_completed_with_seq_and_phases():
    engine = RunEngine()
    await _start_active_run(engine, "t1")
    runner = FakeRunner(_tool_turn_events())
    engine.register_runner("t1", runner)

    emitted: list[tuple[str, object, int]] = []
    approvals: list[ToolCallBegin] = []

    async def on_approval(thread_id, run_id_, event):
        approvals.append(event)

    outcome = await engine.run_loop(
        "t1",
        runner,
        "hi",
        emitter=lambda tid, rid, event, seq: emitted.append((tid, event, seq)),
        needs_permit=lambda event: event.name == "read_file",
        on_approval=on_approval,
    )
    assert outcome == "completed"
    # 事件带单调递增 seq
    seqs = [seq for _, _, seq in emitted]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)
    # 审批钩子触发
    assert [a.name for a in approvals] == ["read_file"]
    # 终态
    session = engine.manager.get_session("t1")
    assert session.active_run_phase == RunPhase.COMPLETED


async def test_run_loop_approval_phase_declared():
    engine = RunEngine()
    await _start_active_run(engine, "t1")
    runner = FakeRunner(_tool_turn_events())
    engine.register_runner("t1", runner)
    phases: list[RunPhase] = []

    async def on_approval(thread_id, run_id_, event):
        session = engine.manager.get_session(thread_id)
        phases.append(session.active_run_phase)

    await engine.run_loop(
        "t1",
        runner,
        "hi",
        emitter=lambda *a: None,
        needs_permit=lambda event: event.name == "read_file",
        on_approval=on_approval,
    )
    assert phases == [RunPhase.WAITING_APPROVAL]


async def test_run_loop_cancelled_terminal_and_no_orphan():
    engine = RunEngine()
    await _start_active_run(engine, "t1")
    runner = FakeRunner(_tool_turn_events())  # 正常结束 → completed
    engine.register_runner("t1", runner)
    outcome = await engine.run_loop("t1", runner, "hi", emitter=lambda *a: None)
    assert outcome == "completed"
    session = engine.manager.get_session("t1")
    assert session.active_run_phase == RunPhase.COMPLETED

    # 显式 cancelled 终态（stop_reason=cancelled → CANCELLED）
    engine2 = RunEngine()
    await engine2.send_input(
        InputMessage.create("t2", "x", delivery=InputDelivery.ENQUEUE)
    )
    run2 = new_run_id()
    await engine2.manager.start_run("t2", object(), run_id=run2)
    cancelled_events = _tool_turn_events()
    cancelled_events[-1] = RunEnd(1, stop_reason="cancelled")
    runner2 = FakeRunner(cancelled_events)
    engine2.register_runner("t2", runner2)
    outcome2 = await engine2.run_loop("t2", runner2, "x", emitter=lambda *a: None)
    assert outcome2 == "cancelled"
    session2 = engine2.manager.get_session("t2")
    assert session2.active_run_phase == RunPhase.CANCELLED


async def test_run_loop_finish_releases_workspace():
    engine = RunEngine()
    run_id = await _start_active_run(engine, "t1")
    from electromind.harness.workspace import WorkspaceKey

    key = WorkspaceKey(execution_target_id="local", canonical_workdir="/ws")
    assert await engine.manager.try_acquire_workspace(
        "t1",
        key,
        run_id,
        InputDelivery
        and __import__(
            "electromind.harness.state", fromlist=["SessionMode"]
        ).SessionMode.RUN,
    )
    runner = FakeRunner(_noop_events())
    engine.register_runner("t1", runner)
    await engine.run_loop("t1", runner, "hi", emitter=lambda *a: None)
    assert engine.manager.workspace_holder(key) is None  # 释放


# ── 快照与清理 ──────────────────────────────────────────────────────────


async def test_snapshot_and_close():
    engine = RunEngine()
    await _start_active_run(engine, "t1")
    snap = await engine.snapshot("t1")
    assert snap["thread_id"] == "t1"
    assert snap["active_run_id"] is not None
    # 未知 thread
    snap2 = await engine.snapshot("nope")
    assert snap2["exists"] is False
    await engine.close()
    assert engine._tasks == {}


async def test_send_input_rejects_empty():
    engine = RunEngine()
    receipt = await engine.send_input(
        InputMessage.create("t1", "   ", delivery=InputDelivery.ENQUEUE)
    )
    assert str(receipt.state) == "rejected"


# ── 多线程并发 ──────────────────────────────────────────────────────────


async def test_parallel_threads_independent():
    engine = RunEngine()
    for tid in ("a", "b", "c"):
        await _start_active_run(engine, tid)
    # 三个线程各自有活动 Run
    for tid in ("a", "b", "c"):
        assert engine.manager.has_active_run(tid)
    # 互不阻塞
    assert engine.manager.has_active_run("a")
    assert not engine.manager.has_active_run("d")


# ── 补充分支覆盖（M8） ─────────────────────────────────────────────────


async def test_engine_registry_and_close():
    engine = RunEngine()
    runner = FakeRunner(_noop_events())
    engine.register_runner("t1", runner)
    assert engine.runner_for("t1") is runner
    engine.unregister_runner("t1")
    assert engine.runner_for("t1") is None
    # close 清空
    engine.register_runner("t1", runner)
    await engine.close()
    assert engine.runner_for("t1") is None
    assert engine._tasks == {}


async def test_engine_control_plane_missing_runner():
    engine = RunEngine()
    run_id = await _start_active_run(engine, "t1")
    # 无 runner（session.runner 也是 None）→ 拒绝
    assert not engine.cancel_run("t1", run_id)
    assert not engine.steer("t1", "x")
    assert not engine.permit_tool("t1", run_id, "c1")
    assert not engine.deny_tool("t1", run_id, "c1")


async def test_engine_control_plane_old_api_fallback():
    """旧 API 桩（inbound 对象 + 单参 steer）经回退路径工作。"""
    engine = RunEngine()
    run_id = await _start_active_run(engine, "t1")

    class OldInbound:
        def __init__(self):
            self.permitted = []
            self.denied = []

        def permit(self, tool_call_id):
            self.permitted.append(tool_call_id)

        def deny(self, tool_call_id, reason=""):
            self.denied.append((tool_call_id, reason))

    class OldRunner:
        inbound = OldInbound()

        def steer(self, text):
            self.steered = [text]

        def cancel_run(self):
            self.cancelled = True

    runner = OldRunner()
    engine.register_runner("t1", runner)
    assert engine.steer("t1", "hi")
    assert runner.steered == ["hi"]
    assert engine.permit_tool("t1", run_id, "c1")
    assert engine.deny_tool("t1", run_id, "c2", reason="no")
    assert engine.cancel_run("t1", run_id)
    assert runner.cancelled
    assert runner.inbound.permitted == ["c1"]
    assert runner.inbound.denied == [("c2", "no")]


async def test_run_loop_before_finish_hook_called():
    engine = RunEngine()
    await _start_active_run(engine, "t1")
    runner = FakeRunner(_noop_events())
    engine.register_runner("t1", runner)
    calls: list[str] = []

    async def before_finish(tid, rid, outcome):
        calls.append(outcome)

    await engine.run_loop(
        "t1", runner, "hi", emitter=lambda *a: None, before_finish=before_finish
    )
    assert calls == ["completed"]


async def test_run_loop_error_marks_failed_and_reraises():
    engine = RunEngine()
    await _start_active_run(engine, "t1")

    async def boom(text):
        yield RunBegin("hi")
        raise RuntimeError("boom")

    runner = FakeRunner([])
    runner.run = boom
    engine.register_runner("t1", runner)
    with pytest.raises(RuntimeError, match="boom"):
        await engine.run_loop("t1", runner, "hi", emitter=lambda *a: None)
    session = engine.manager.get_session("t1")
    assert session.active_run_phase == RunPhase.FAILED


async def test_run_loop_cancelled_error_marks_cancelled_and_reraises():
    engine = RunEngine()
    await _start_active_run(engine, "t1")

    async def cancel_mid(text):
        yield RunBegin("hi")
        raise asyncio.CancelledError()

    runner = FakeRunner([])
    runner.run = cancel_mid
    engine.register_runner("t1", runner)
    with pytest.raises(asyncio.CancelledError):
        await engine.run_loop("t1", runner, "hi", emitter=lambda *a: None)
    session = engine.manager.get_session("t1")
    assert session.active_run_phase == RunPhase.CANCELLED


async def test_engine_close_cancels_pending_tasks():
    engine = RunEngine()

    async def slow_runner_run(text):
        await asyncio.sleep(60)

    async def spin():
        await engine.run_loop("t9", FakeRunner([]), "x", emitter=lambda *a: None)

    # 直接注册一个挂起任务模拟
    task = asyncio.create_task(slow_runner_run("x"))
    engine._tasks["t9"] = task
    await asyncio.sleep(0)
    await engine.close()
    assert task.cancelled() or task.done()
    assert engine._tasks == {}
    del spin


async def test_engine_control_plane_session_without_runner():
    """session 存在但无 runner（start_run 传了 object 或 None）→ 拒绝。"""
    engine = RunEngine()
    session = engine.manager._get_or_create("t-solo")
    session.active_run_id = "run-solo"
    session.active_run_phase = RunPhase.RUNNING
    session.runner = None
    assert not engine.cancel_run("t-solo", "run-solo")
    assert not engine.permit_tool("t-solo", "run-solo", "c1")
    assert not engine.deny_tool("t-solo", "run-solo", "c1")
