"""M4: ToolEffect / ToolScheduler / 风险审批测试。"""

from __future__ import annotations

import asyncio
import time

import pytest

from electromind.core.tool import FunctionTool
from electromind.execution.effects import (
    ToolEffect,
    ToolRegistrationError,
    apply_builtin_effects,
    assert_effects_declared,
    effect_for_name,
    risk_of_effect,
)
from electromind.execution.permissions import (
    ActionSpec,
    ApprovalScope,
    PermissionDecision,
    RiskLevel,
    RiskPolicy,
    risk_of_action,
)
from electromind.execution.tool_scheduler import (
    ToolCallInfo,
    ToolScheduler,
    effects_conflict,
)
from electromind.harness.state import SessionMode

# ── ToolEffect 注册门 ───────────────────────────────────────────────────


def test_effect_registration_gate():
    tool = FunctionTool("my_tool", "d", {})
    with pytest.raises(ToolRegistrationError, match="未声明 effect"):
        assert_effects_declared([tool])
    declared = tool.with_effect(ToolEffect.READ_WORKSPACE)
    assert_effects_declared([declared])  # 不抛
    assert declared.effect == ToolEffect.READ_WORKSPACE
    assert tool.effect is None  # with_effect 不原地改


def test_builtin_effect_table():
    assert effect_for_name("read_file") == ToolEffect.READ_WORKSPACE
    assert effect_for_name("run_command") == ToolEffect.EXECUTE
    assert effect_for_name("write_file") == ToolEffect.WRITE_WORKSPACE
    assert effect_for_name("fetch_url") == ToolEffect.NETWORK
    assert effect_for_name("unknown_tool") is None


def test_apply_builtin_effects():
    tools = [
        FunctionTool("read_file", "d", {}),
        FunctionTool("custom", "d", {}, effect=ToolEffect.PURE),
    ]
    resolved = apply_builtin_effects(tools)
    assert resolved[0].effect == ToolEffect.READ_WORKSPACE
    assert resolved[1].effect == ToolEffect.PURE  # 已声明不动
    assert tools[0].effect is None  # 原对象不变


def test_effect_risk():
    assert risk_of_effect(ToolEffect.PURE) == "low"
    assert risk_of_effect(ToolEffect.EXECUTE) == "high"
    assert risk_of_effect(ToolEffect.DESTRUCTIVE) == "critical"


# ── ToolScheduler ───────────────────────────────────────────────────────


def _call(cid, name, effect, **args) -> ToolCallInfo:
    return ToolCallInfo(tool_call_id=cid, name=name, arguments=args, effect=effect)


def test_effects_conflict_matrix():
    assert not effects_conflict(ToolEffect.READ_WORKSPACE, ToolEffect.READ_WORKSPACE)
    assert not effects_conflict(ToolEffect.READ_WORKSPACE, ToolEffect.READ_HOST)
    # P0-3: PURE 保守串行（纯计算工具也可能带副作用）
    assert effects_conflict(ToolEffect.PURE, ToolEffect.WRITE_WORKSPACE)
    assert effects_conflict(ToolEffect.PURE, ToolEffect.PURE)
    assert effects_conflict(ToolEffect.WRITE_WORKSPACE, ToolEffect.WRITE_WORKSPACE)
    assert effects_conflict(ToolEffect.EXECUTE, ToolEffect.READ_WORKSPACE)
    assert effects_conflict(None, ToolEffect.READ_WORKSPACE)  # 未判定 → 串行
    assert effects_conflict(ToolEffect.SUBMIT_EXTERNAL, ToolEffect.SUBMIT_EXTERNAL)


def test_scheduler_batches_parallel_reads():
    scheduler = ToolScheduler()
    calls = [
        _call("c1", "read_file", ToolEffect.READ_WORKSPACE, path="a.txt"),
        _call("c2", "read_file", ToolEffect.READ_WORKSPACE, path="b.txt"),
        _call("c3", "list_dir", ToolEffect.READ_WORKSPACE, path="."),
    ]
    batches = scheduler.plan(calls)
    assert len(batches) == 1  # 全部并行
    assert len(batches[0]) == 3


def test_scheduler_serializes_writes_and_conflicts():
    scheduler = ToolScheduler()
    calls = [
        _call("w1", "write_file", ToolEffect.WRITE_WORKSPACE, path="a.txt"),
        _call("w2", "write_file", ToolEffect.WRITE_WORKSPACE, path="a.txt"),
        _call("r1", "read_file", ToolEffect.READ_WORKSPACE, path="a.txt"),
    ]
    batches = scheduler.plan(calls)
    # 写 a.txt 与读 a.txt 冲突 → 全串行
    assert batches == [[calls[0]], [calls[1]], [calls[2]]]
    # 不同路径的写：保守仍串行（WRITE 不与其他 WRITE 并行）
    calls2 = [
        _call("w1", "write_file", ToolEffect.WRITE_WORKSPACE, path="x"),
        _call("w2", "write_file", ToolEffect.WRITE_WORKSPACE, path="y"),
        _call("r1", "read_file", ToolEffect.READ_WORKSPACE, path="z"),
    ]
    assert len(scheduler.plan(calls2)) == 3


def test_scheduler_execute_batch_parallel():
    scheduler = ToolScheduler()
    order: list[str] = []

    async def execute_one(call: ToolCallInfo):
        await asyncio.sleep(0.05)
        order.append(call.tool_call_id)
        return "ok"

    calls = [
        _call("c1", "read_file", ToolEffect.READ_WORKSPACE, path="a"),
        _call("c2", "read_file", ToolEffect.READ_WORKSPACE, path="b"),
    ]
    results = asyncio.run(scheduler.execute_batch(calls, execute_one))
    assert len(results) == 2
    assert len(order) == 2
    # 并行执行：两个都在对方完成前开始 → 近似同时完成（用耗时验证）
    assert results[0]["tool_call_id"] == "c1"


def test_scheduler_serialize_all():
    scheduler = ToolScheduler()
    calls = [_call("c1", "x", None), _call("c2", "y", None)]
    assert scheduler.serialize_all(calls) == [[calls[0]], [calls[1]]]


# ── RiskPolicy ──────────────────────────────────────────────────────────


def test_policy_run_mode_medium_auto_allows():
    policy = RiskPolicy(SessionMode.RUN, allow_file_write=True)
    decision = policy.decide(
        ActionSpec(tool="write_file", target="/ws/a", risk=RiskLevel.MEDIUM)
    )
    assert decision == PermissionDecision.ALLOW_FOR_RUN


def test_policy_high_requires_ask():
    policy = RiskPolicy(SessionMode.RUN)
    decision = policy.decide(
        ActionSpec(tool="run_command", command="pwd", risk=RiskLevel.HIGH)
    )
    assert decision == PermissionDecision.ASK


def test_policy_critical_never_auto():
    policy = RiskPolicy(SessionMode.RUN, auto_approve=True)
    decision = policy.decide(
        ActionSpec(tool="run_command", command="rm -rf /tmp/x", risk=RiskLevel.CRITICAL)
    )
    assert decision == PermissionDecision.ASK


def test_policy_ask_mode_read_only():
    policy = RiskPolicy(SessionMode.ASK)
    assert policy.decide(ActionSpec(tool="read_file", risk=RiskLevel.LOW)) == (
        PermissionDecision.ALLOW_FOR_RUN
    )
    assert policy.decide(ActionSpec(tool="write_file", risk=RiskLevel.MEDIUM)) == (
        PermissionDecision.DENY
    )


def test_policy_external_side_effect_never_auto():
    policy = RiskPolicy(SessionMode.RUN, auto_approve=True)
    decision = policy.decide(
        ActionSpec(
            tool="submit_external", external_side_effect=True, risk=RiskLevel.HIGH
        )
    )
    assert decision == PermissionDecision.ASK


# ── risk_of_action ──────────────────────────────────────────────────────


def test_risk_of_action():
    assert risk_of_action(ActionSpec(tool="read_file")) == RiskLevel.LOW
    assert risk_of_action(ActionSpec(tool="write_file")) == RiskLevel.MEDIUM
    assert (
        risk_of_action(ActionSpec(tool="run_command", command="echo hi"))
        == RiskLevel.HIGH
    )
    assert (
        risk_of_action(ActionSpec(tool="run_command", command="rm -rf /"))
        == RiskLevel.CRITICAL
    )
    assert risk_of_action(ActionSpec(tool="copy_to_host")) == RiskLevel.HIGH
    assert risk_of_action(ActionSpec(tool="submit_external")) == RiskLevel.HIGH
    assert risk_of_action(ActionSpec(tool="fetch_url")) == RiskLevel.MEDIUM


# ── ApprovalScope ───────────────────────────────────────────────────────


def test_approval_scope_validation():
    action = ActionSpec(tool="run_command", command="pwd", risk=RiskLevel.HIGH)
    scope = ApprovalScope(
        approval_id="apr-1",
        thread_id="t1",
        run_id="run-1",
        tool_call_id="call-1",
        action=action,
        expires_at=time.time() + 100,
    )
    assert scope.validate(thread_id="t1", run_id="run-1", tool_call_id="call-1") is None
    # 跨 Thread
    assert "Thread" in scope.validate(
        thread_id="t2", run_id="run-1", tool_call_id="call-1"
    )
    # 跨 Run
    assert "Run" in scope.validate(
        thread_id="t1", run_id="run-2", tool_call_id="call-1"
    )
    # 跨 ToolCall
    assert "ToolCall" in scope.validate(
        thread_id="t1", run_id="run-1", tool_call_id="call-2"
    )
    # 参数变化
    changed = ActionSpec(
        tool="run_command", command="rm -rf /", risk=RiskLevel.CRITICAL
    )
    assert "重新审批" in scope.validate(
        thread_id="t1", run_id="run-1", tool_call_id="call-1", action=changed
    )
    # 过期
    expired = ApprovalScope(
        approval_id="apr-2",
        thread_id="t1",
        run_id="run-1",
        tool_call_id="call-1",
        action=action,
        expires_at=time.time() - 10,
    )
    assert "过期" in expired.validate(
        thread_id="t1", run_id="run-1", tool_call_id="call-1"
    )


# ── 补充分支覆盖（M8） ─────────────────────────────────────────────────


def test_policy_plan_mode_ask_for_writes():
    policy = RiskPolicy(SessionMode.PLAN)
    assert policy.decide(ActionSpec(tool="read_file", risk=RiskLevel.LOW)) == (
        PermissionDecision.ALLOW_FOR_RUN
    )
    assert policy.decide(ActionSpec(tool="write_file", risk=RiskLevel.MEDIUM)) == (
        PermissionDecision.ASK
    )


def test_policy_run_command_medium_requires_ask_without_execute():
    policy = RiskPolicy(SessionMode.RUN)
    assert (
        policy.decide(
            ActionSpec(tool="run_command", command="pwd", risk=RiskLevel.MEDIUM)
        )
        == PermissionDecision.ASK
    )
    # 显式允许 execute → 放行
    policy2 = RiskPolicy(SessionMode.RUN, allow_execute=True)
    assert (
        policy2.decide(
            ActionSpec(tool="run_command", command="pwd", risk=RiskLevel.MEDIUM)
        )
        == PermissionDecision.ALLOW_FOR_RUN
    )


def test_policy_auto_allows_network_and_auto_approve():
    policy = RiskPolicy(SessionMode.RUN, allow_network=True)
    assert policy.decide(ActionSpec(tool="fetch_url", risk=RiskLevel.MEDIUM)) == (
        PermissionDecision.ALLOW_FOR_RUN
    )
    assert policy.decide(ActionSpec(tool="web_search", risk=RiskLevel.MEDIUM)) == (
        PermissionDecision.ALLOW_FOR_RUN
    )
    # 未知 medium 工具 → ASK
    assert policy.decide(ActionSpec(tool="mystery_tool", risk=RiskLevel.MEDIUM)) == (
        PermissionDecision.ASK
    )
    # auto_approve 但外部副作用 → 仍 ASK
    auto = RiskPolicy(SessionMode.RUN, auto_approve=True)
    assert (
        auto.decide(
            ActionSpec(
                tool="submit_external", external_side_effect=True, risk=RiskLevel.MEDIUM
            )
        )
        == PermissionDecision.ASK
    )


def test_risk_of_action_destructive_prefixes():
    for command in (
        "mkfs.ext4 /dev/sdb",
        "dd if=/dev/zero of=/dev/sda",
        "shutdown -h now",
        "reboot",
        ":(){ :|:& };:",
        "rm -fr /tmp/x",
    ):
        assert (
            risk_of_action(ActionSpec(tool="run_command", command=command))
            == RiskLevel.CRITICAL
        ), command
    assert risk_of_action(ActionSpec(tool="delete_file")) == RiskLevel.CRITICAL
    # 未在表中的工具：显式风险保留
    assert (
        risk_of_action(ActionSpec(tool="custom_tool", risk=RiskLevel.CRITICAL))
        == RiskLevel.CRITICAL
    )
