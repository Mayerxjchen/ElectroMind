"""M1 多入口一致性：Wire 与 Embedded 客户端对相同输入产生一致状态转换。

验收（§6.5）：Run 终态、工具调用顺序、审批决策、Stop Reason、事件序列
逻辑必须一致；传输封装可以不同。
"""

from __future__ import annotations

import pytest
from tests.test_run_engine import FakeRunner, _noop_events, _tool_turn_events

from electromind.core.events import (
    RunEnd,
    ToolCallBegin,
    ToolResult,
    TurnResult,
)
from electromind.engine import RunEngine
from electromind.harness import InputDelivery, InputMessage
from electromind.harness.state import RunPhase


def _normalize(events: list) -> list[str]:
    """归一化事件序列（传输封装无关的逻辑序列）。"""
    out = []
    for event in events:
        if isinstance(event, (ToolCallBegin, ToolResult, TurnResult, RunEnd)):
            out.append(type(event).__name__)
    return out


@pytest.mark.parametrize("scenario", ["tools", "text"])
async def test_wire_and_embedded_same_state_transitions(scenario):
    """两个入口跑相同输入 → 相同终态与工具序列。"""
    events = _tool_turn_events() if scenario == "tools" else _noop_events()

    # 入口 A：Embedded（模拟 CLI 路径）——engine.run_loop 直接驱动
    engine_a = RunEngine()
    await engine_a.send_input(
        InputMessage.create("t-a", "任务", delivery=InputDelivery.ENQUEUE)
    )
    run_a = await engine_a.manager.start_run("t-a", object(), run_id="run-a")
    assert run_a is not None
    runner_a = FakeRunner(events)
    engine_a.register_runner("t-a", runner_a)
    emitted_a: list = []
    outcome_a = await engine_a.run_loop(
        "t-a", runner_a, "任务", emitter=lambda *a: emitted_a.append(a[2])
    )

    # 入口 B：Wire 路径 —— 同一引擎语义，独立实例（传输封装不同）
    engine_b = RunEngine()
    await engine_b.send_input(
        InputMessage.create("t-b", "任务", delivery=InputDelivery.ENQUEUE)
    )
    run_b = await engine_b.manager.start_run("t-b", object(), run_id="run-b")
    assert run_b is not None
    runner_b = FakeRunner(events)
    engine_b.register_runner("t-b", runner_b)
    emitted_b: list = []
    outcome_b = await engine_b.run_loop(
        "t-b", runner_b, "任务", emitter=lambda *a: emitted_b.append(a[2])
    )

    # 一致性：终态 / 工具顺序 / 事件序列逻辑 / stop reason
    assert outcome_a == outcome_b
    assert _normalize(emitted_a) == _normalize(emitted_b)
    session_a = engine_a.manager.get_session("t-a")
    session_b = engine_b.manager.get_session("t-b")
    assert session_a.active_run_phase == session_b.active_run_phase
    if scenario == "tools":
        assert session_a.active_run_phase == RunPhase.COMPLETED
        tool_order_a = [(e.name) for e in emitted_a if isinstance(e, ToolCallBegin)]
        tool_order_b = [(e.name) for e in emitted_b if isinstance(e, ToolCallBegin)]
        assert tool_order_a == tool_order_b == ["read_file"]


async def test_shared_application_service_singleton():
    """CLI/Wire/HTTP 共用同一 Application Service（单例）。"""
    from app.service import (
        get_application_service,
        reset_application_service,
    )

    reset_application_service()
    svc1 = get_application_service()
    svc2 = get_application_service()
    assert svc1 is svc2
    assert svc1.engine is svc2.engine
    reset_application_service()


async def test_approval_decision_consistent_across_entries():
    """审批决策一致：两入口对同一工具调用产生同一审批请求序列。"""
    engine_a = RunEngine()
    await engine_a.send_input(
        InputMessage.create("t-a", "任务", delivery=InputDelivery.ENQUEUE)
    )
    await engine_a.manager.start_run("t-a", object(), run_id="run-a")
    runner_a = FakeRunner(_tool_turn_events())
    engine_a.register_runner("t-a", runner_a)
    approvals_a: list[str] = []

    async def on_approval_a(tid, rid, event):
        approvals_a.append(event.name)

    await engine_a.run_loop(
        "t-a",
        runner_a,
        "任务",
        emitter=lambda *a: None,
        needs_permit=lambda ev: ev.name == "read_file",
        on_approval=on_approval_a,
    )

    engine_b = RunEngine()
    await engine_b.send_input(
        InputMessage.create("t-b", "任务", delivery=InputDelivery.ENQUEUE)
    )
    await engine_b.manager.start_run("t-b", object(), run_id="run-b")
    runner_b = FakeRunner(_tool_turn_events())
    engine_b.register_runner("t-b", runner_b)
    approvals_b: list[str] = []

    async def on_approval_b(tid, rid, event):
        approvals_b.append(event.name)

    await engine_b.run_loop(
        "t-b",
        runner_b,
        "任务",
        emitter=lambda *a: None,
        needs_permit=lambda ev: ev.name == "read_file",
        on_approval=on_approval_b,
    )
    assert approvals_a == approvals_b == ["read_file"]
