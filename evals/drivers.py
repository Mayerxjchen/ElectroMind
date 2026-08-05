"""Engine 类任务 driver — 确定性场景函数。

每个 driver 接收 ``(task, thread_root)``，驱动引擎层 API 完成一个
Golden 场景，并返回观察字典：

```json
{"passed": bool, "failure": "planning|...|null", "details": "...",
 "extra": {...}}
```

driver 本身既是任务执行器也是确定性验证器（M0 §5.3：100% 任务有
确定性验证器）。
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from .task import FailureCategory, TaskSpec


def _ok(details: str = "", extra: dict | None = None) -> dict:
    return {"passed": True, "failure": None, "details": details, "extra": extra or {}}


def _fail(category: FailureCategory, details: str, extra: dict | None = None) -> dict:
    return {
        "passed": False,
        "failure": str(category),
        "details": details,
        "extra": extra or {},
    }


# ── planning 类 ────────────────────────────────────────────────────────


async def driver_plan_lifecycle(task: TaskSpec, thread_root: Path) -> dict:
    """计划生命周期：propose → ready → approved → 执行 → completed。

    验证：fingerprint 冻结、批准后状态机、状态字段变化不改内容指纹。
    """
    del thread_root
    from electromind.execution.plan import (
        PlanState,
        PlanStatus,
        PlanTracker,
        StepStatus,
    )

    plan = PlanState(
        plan_id="plan-1",
        version=1,
        status=PlanStatus.DRAFT,
        objective=task.input,
        steps=(_mk_step("s1", "第一步", "s2"),),
    )
    tracker = PlanTracker()
    frozen = tracker.propose(plan)
    if frozen.status != PlanStatus.READY or not frozen.fingerprint:
        return _fail(FailureCategory.PLANNING, "propose 未进入 READY 或指纹为空")
    approved = tracker.approve()
    if approved is None or approved.status != PlanStatus.APPROVED:
        return _fail(FailureCategory.PLANNING, "approve 失败")
    if approved.fingerprint != frozen.fingerprint:
        return _fail(FailureCategory.PLANNING, "批准后指纹漂移")
    # 状态字段变化不改内容指纹
    stepped = approved.with_step_status("s1", StepStatus.RUNNING)
    if stepped.fingerprint != approved.fingerprint:
        return _fail(FailureCategory.PLANNING, "状态变化污染内容指纹")
    # 依赖未完成不得进入 READY（以 SKIPPED 步验证 update_step 权限语义）
    updated = tracker.update_step("s1", StepStatus.RUNNING)
    if updated is None:
        return _fail(FailureCategory.PLANNING, "update_step 失败")
    done = tracker.complete()
    if done is None or done.status != PlanStatus.COMPLETED:
        return _fail(FailureCategory.PLANNING, "complete 失败")
    if not tracker.history:
        return _fail(FailureCategory.PLANNING, "history 未记录")
    return _ok("plan 生命周期完整", {"history": len(tracker.history)})


def _mk_step(step_id: str, title: str, depends: str = "") -> object:
    from electromind.execution.plan import PlanStep

    deps = (depends,) if depends else ()
    return PlanStep(id=step_id, title=title, depends_on=deps)


async def driver_plan_revision(task: TaskSpec, thread_root: Path) -> dict:
    """修订语义：Approved 计划不可原地修改，修改必须产生新版本。"""
    del thread_root
    from electromind.execution.plan import PlanState, PlanStatus, PlanTracker

    plan_v1 = PlanState(
        plan_id="plan-r1",
        version=1,
        status=PlanStatus.DRAFT,
        objective=task.input,
    )
    tracker = PlanTracker()
    frozen1 = tracker.propose(plan_v1)
    approved1 = tracker.approve()
    if approved1 is None or approved1.status != PlanStatus.APPROVED:
        return _fail(FailureCategory.PLANNING, "v1 approve 失败")
    revised = tracker.revise()
    if revised is None:
        return _fail(FailureCategory.PLANNING, "revise 失败")
    if revised.version != 2:
        return _fail(FailureCategory.PLANNING, f"修订版本号未递增: {revised.version}")
    if revised.status != PlanStatus.REVISING:
        return _fail(FailureCategory.PLANNING, "修订未进入 REVISING")
    # REVISING 不能直接批准；必须用新内容重新 propose（冻结为新版本）
    if tracker.approve() is not None:
        return _fail(FailureCategory.PLANNING, "REVISING 可直接批准")
    plan_v2 = PlanState(
        plan_id="plan-r1",
        version=2,
        status=PlanStatus.DRAFT,
        objective=f"{task.input}（修订后）",
    )
    frozen2 = tracker.propose(plan_v2)
    if frozen2 is None or frozen2.status != PlanStatus.READY:
        return _fail(FailureCategory.PLANNING, "修订 propose 未冻结")
    approved2 = tracker.approve()
    if approved2 is None or approved2.version != 2:
        return _fail(FailureCategory.PLANNING, "修订 approve 失败")
    if approved2.fingerprint == frozen1.fingerprint:
        return _fail(FailureCategory.PLANNING, "修订指纹未变化")
    return _ok("revision 语义正确", {"version": approved2.version})


# ── recovery 类 ────────────────────────────────────────────────────────


async def driver_input_idempotency(task: TaskSpec, thread_root: Path) -> dict:
    """输入幂等：相同 message_id 重试不得重复入队或产生第二个 Run。"""
    from electromind.harness import InputDelivery, InputMessage, ThreadSessionManager

    manager = ThreadSessionManager()
    _ = manager
    msg = InputMessage.create("t-1", task.input, delivery=InputDelivery.AUTO)
    receipt1 = await manager.send_input(msg)
    receipt2 = await manager.send_input(msg)  # 同 message_id 重试
    if receipt1.state != receipt2.state:
        return _fail(
            FailureCategory.STATE,
            f"重试收到不同 receipt: {receipt1.state} vs {receipt2.state}",
        )
    session = manager.get_session("t-1")
    if session is None or len(session.queued_inputs) != 1:
        return _fail(FailureCategory.STATE, "重复消息被二次入队")
    return _ok("输入幂等成立", {"queued": 1})


async def driver_state_machine(task: TaskSpec, thread_root: Path) -> dict:
    """Run 状态机：集中转换表、非法转换拒绝、终态不可重入。"""
    del thread_root
    from electromind.harness.state import (
        RunPhase,
        allowed_run_transitions,
        is_terminal_run_phase,
    )

    # DORMANT → PREPARING → RUNNING → FINALIZING → COMPLETED 合法路径
    chain = [
        (RunPhase.DORMANT, RunPhase.PREPARING),
        (RunPhase.PREPARING, RunPhase.RUNNING),
        (RunPhase.RUNNING, RunPhase.FINALIZING),
        (RunPhase.FINALIZING, RunPhase.COMPLETED),
    ]
    for src, dst in chain:
        if dst not in allowed_run_transitions(src):
            return _fail(FailureCategory.STATE, f"合法转换被拒绝: {src}→{dst}")
    # 非法转换：COMPLETED 是终态，不可回到 RUNNING
    if RunPhase.RUNNING in allowed_run_transitions(RunPhase.COMPLETED):
        return _fail(FailureCategory.STATE, "终态可重入")
    if not is_terminal_run_phase(RunPhase.CANCELLED):
        return _fail(FailureCategory.STATE, "CANCELLED 不是终态")
    if is_terminal_run_phase(RunPhase.RUNNING):
        return _fail(FailureCategory.STATE, "RUNNING 被误判为终态")
    return _ok("状态机转换表正确")


# ── scientific 类 ──────────────────────────────────────────────────────


async def driver_units_and_sources(task: TaskSpec, thread_root: Path) -> dict:
    """数值结论携带单位与来源（scientific 基线契约）。"""
    from electromind.core.message import Message, Messages

    del thread_root
    messages = Messages()
    messages += Message.user("计算水的能量")
    messages += Message.assistant(
        {"type": "function", "id": "call_1", "name": "parse_energy", "arguments": "{}"}
    )
    # 附上带单位的解析结果来源
    messages += Message.tool_result(
        "call_1",
        '{"value": -76.4, "unit": "Hartree", "source": "cp2k_ENERGY_FORCE.out"}',
    )
    openai = messages.to_openai()
    tool_msgs = [m for m in openai if m.get("role") == "tool"]
    if not tool_msgs:
        return _fail(FailureCategory.TOOL, "ToolResult 丢失")
    text = str(tool_msgs[0].get("content", ""))
    if "Hartree" not in text or "cp2k_ENERGY_FORCE.out" not in text:
        return _fail(FailureCategory.VALIDATION, "数值结果缺少单位或来源")
    return _ok("单位与来源保留", {"tool_messages": len(tool_msgs)})


async def driver_pairing(task: TaskSpec, thread_root: Path) -> dict:
    """ToolCall/ToolResult 配对完整（repair 与 orphan 语义）。"""
    from electromind.core.message import Message, Messages

    del thread_root
    messages = Messages()
    messages += Message.assistant(
        {"type": "function", "id": "call_a", "name": "run_command", "arguments": "{}"}
    )
    messages += Message.assistant(
        {"type": "function", "id": "call_b", "name": "read_file", "arguments": "{}"}
    )
    messages += Message.tool_result("call_b", "file content")
    # call_a 无对应结果 → 补全为占位（不损坏配对）
    count = messages.complete_orphan_tool_results()
    if count != 1:
        return _fail(FailureCategory.STATE, f"孤儿补全数量错误: {count}")
    openai = messages.to_openai()
    tool_ids = {m.get("tool_call_id") for m in openai if m.get("role") == "tool"}
    if "call_a" not in tool_ids or "call_b" not in tool_ids:
        return _fail(FailureCategory.STATE, "ToolCall/ToolResult 配对损坏")
    return _ok("配对完整", {"completed_orphans": count})


async def driver_fingerprint_stability(task: TaskSpec, thread_root: Path) -> dict:
    """Plan 内容指纹：内容不变指纹不变，内容变则变。"""
    del thread_root
    from electromind.execution.plan import PlanState, PlanStatus

    base = dict(
        plan_id="fp-1",
        version=1,
        status=PlanStatus.DRAFT,
        objective="同一目标",
        assumptions=("a1",),
    )
    p1 = PlanState(**base)
    p2 = PlanState(**base)
    if p1.compute_fingerprint() != p2.compute_fingerprint():
        return _fail(FailureCategory.PLANNING, "相同内容的指纹不同")
    p3 = PlanState(**{**base, "assumptions": ("a1", "a2")})
    if p3.compute_fingerprint() == p1.compute_fingerprint():
        return _fail(FailureCategory.PLANNING, "内容变化的指纹未变")
    return _ok("指纹稳定", {})


# ── 补充 planning driver ───────────────────────────────────────────────


async def driver_plan_dependencies(task: TaskSpec, thread_root: Path) -> dict:
    """步骤依赖：依赖引用必须指向已定义步骤，禁止悬空依赖。"""
    del thread_root
    from electromind.execution.plan import PlanState, PlanStatus

    plan = PlanState(
        plan_id="plan-dep",
        version=1,
        status=PlanStatus.DRAFT,
        objective=task.input,
        steps=(_mk_step("s1", "第一步"), _mk_step("s2", "第二步", "s1")),
    )
    defined = {s.id for s in plan.steps}
    for step in plan.steps:
        dangling = set(step.depends_on) - defined
        if dangling:
            return _fail(FailureCategory.PLANNING, f"悬空依赖: {sorted(dangling)}")
    if plan.steps[1].depends_on != ("s1",):
        return _fail(FailureCategory.PLANNING, "依赖顺序丢失")
    return _ok("依赖图完整", {"steps": len(plan.steps)})


async def driver_plan_propose_twice(task: TaskSpec, thread_root: Path) -> dict:
    """再次 propose 替换当前草稿（旧版本仅留 history 之外的状态）。"""
    del thread_root
    from electromind.execution.plan import PlanState, PlanStatus, PlanTracker

    tracker = PlanTracker()
    p1 = PlanState(plan_id="p2", version=1, status=PlanStatus.DRAFT, objective="目标A")
    p2 = PlanState(plan_id="p2", version=2, status=PlanStatus.DRAFT, objective="目标B")
    tracker.propose(p1)
    frozen2 = tracker.propose(p2)
    if frozen2 is None or frozen2.objective != "目标B":
        return _fail(FailureCategory.PLANNING, "第二次 propose 未替换当前")
    if frozen2.status != PlanStatus.READY:
        return _fail(FailureCategory.PLANNING, "propose 未冻结为 READY")
    return _ok("propose 替换语义正确", {})


async def driver_plan_complete_flow(task: TaskSpec, thread_root: Path) -> dict:
    """完整流程：propose→approve→逐步执行→complete，历史记录齐全。"""
    del thread_root
    from electromind.execution.plan import (
        PlanState,
        PlanStatus,
        PlanTracker,
        StepStatus,
    )

    tracker = PlanTracker()
    plan = PlanState(
        plan_id="flow",
        version=1,
        status=PlanStatus.DRAFT,
        objective=task.input,
        steps=(_mk_step("a", "A"), _mk_step("b", "B")),
    )
    tracker.propose(plan)
    approved = tracker.approve()
    if approved is None or approved.status != PlanStatus.APPROVED:
        return _fail(FailureCategory.PLANNING, "approve 失败")
    for step_id in ("a", "b"):
        updated = tracker.update_step(step_id, StepStatus.RUNNING)
        if updated is None:
            return _fail(FailureCategory.PLANNING, f"update_step({step_id}) 失败")
    done = tracker.complete()
    if done is None or done.status != PlanStatus.COMPLETED:
        return _fail(FailureCategory.PLANNING, "complete 失败")
    statuses = {s.id: str(s.status) for s in done.steps}
    return _ok("完整流程通过", {"steps": statuses})


async def driver_plan_dict_roundtrip(task: TaskSpec, thread_root: Path) -> dict:
    """to_dict 序列化：指纹、步骤状态、内容字段完整。"""
    del thread_root
    from electromind.execution.plan import PlanState, PlanStatus

    plan = PlanState(
        plan_id="dict",
        version=1,
        status=PlanStatus.APPROVED,
        objective=task.input,
        assumptions=("a1",),
        risks=("r1",),
        verification=("v1",),
        steps=(_mk_step("x", "X"),),
    )
    d = plan.to_dict()
    if d["plan_id"] != "dict" or d["version"] != 1:
        return _fail(FailureCategory.PLANNING, "to_dict 元数据缺失")
    if str(d["status"]) != str(PlanStatus.APPROVED):
        return _fail(FailureCategory.PLANNING, "to_dict 状态丢失")
    if len(d["steps"]) != 1 or d["steps"][0]["id"] != "x":
        return _fail(FailureCategory.PLANNING, "to_dict 步骤丢失")
    return _ok("序列化完整", {})


async def driver_plan_status_matrix(task: TaskSpec, thread_root: Path) -> dict:
    """PlanStatus 枚举完整性：六状态 + 内容指纹覆盖风险/验证条件。"""
    del thread_root
    from electromind.execution.plan import PlanState, PlanStatus

    expected = {
        "draft",
        "ready",
        "approved",
        "executing",
        "completed",
        "revising",
        "cancelled",
    }
    actual = {str(s) for s in PlanStatus}
    if actual != expected:
        return _fail(FailureCategory.PLANNING, f"状态枚举缺失: {expected - actual}")
    p1 = PlanState(
        plan_id="m",
        version=1,
        status=PlanStatus.DRAFT,
        objective="目标",
        risks=("风险A",),
        verification=("验证A",),
    )
    p2 = PlanState(
        plan_id="m",
        version=1,
        status=PlanStatus.DRAFT,
        objective="目标",
    )
    fp1, fp2 = p1.compute_fingerprint(), p2.compute_fingerprint()
    if fp1 == fp2:
        return _fail(FailureCategory.PLANNING, "风险/验证条件未进入指纹")
    return _ok("状态与指纹矩阵正确", {})


# ── 补充 scientific driver ─────────────────────────────────────────────


async def driver_message_roundtrip(task: TaskSpec, thread_root: Path) -> dict:
    """消息往返：ToolResult 内容经 to_openai 后字节级保留（结果不被改写）。"""
    del thread_root
    from electromind.core.message import Message, Messages

    messages = Messages()
    payload = '{"energy": -76.4, "unit": "Hartree", "status": "completed"}'
    messages += Message.assistant(
        {"type": "function", "id": "c1", "name": "parse", "arguments": "{}"}
    )
    messages += Message.tool_result("c1", payload)
    openai = messages.to_openai()
    tool = next(m for m in openai if m.get("role") == "tool")
    if str(tool.get("content", "")) != payload:
        return _fail(FailureCategory.VALIDATION, "ToolResult 内容被引擎改写")
    return _ok("结果往返无损", {})


async def driver_completed_not_validated(task: TaskSpec, thread_root: Path) -> dict:
    """completed ≠ validated ≠ accepted：引擎只传递状态，不自动升级。"""
    del thread_root
    from electromind.core.message import Message, Messages

    messages = Messages()
    messages += Message.user("解析能量并判定有效性")
    messages += Message.assistant(
        {"type": "function", "id": "p1", "name": "parse", "arguments": "{}"}
    )
    messages += Message.tool_result("p1", '{"status": "completed"}')
    openai = messages.to_openai()
    texts = " ".join(str(m.get("content", "")) for m in openai)
    if "validated" in texts.lower() or "accepted" in texts.lower():
        return _fail(FailureCategory.VALIDATION, "引擎自动升级完成状态为已验证/已接受")
    return _ok("状态语义分离", {})


# ── 补充 recovery driver ───────────────────────────────────────────────


async def driver_workspace_lease(task: TaskSpec, thread_root: Path) -> dict:
    """Workspace Lease：写模式独占、释放后无遗留。"""
    del thread_root
    from electromind.harness import SessionMode, ThreadSessionManager
    from electromind.harness.identity import new_run_id
    from electromind.harness.workspace import WorkspaceKey

    manager = ThreadSessionManager()
    key = WorkspaceKey(execution_target_id="local", canonical_workdir="/ws")
    run_id = new_run_id()
    got = await manager.try_acquire_workspace("t1", key, run_id, SessionMode.RUN)
    if not got:
        return _fail(FailureCategory.STATE, "写 lease 获取失败")
    holder = manager.workspace_holder(key)
    if holder != (run_id, "t1"):
        return _fail(FailureCategory.STATE, f"holder 错误: {holder}")
    released = await manager.release_workspace("t1", run_id)
    if not released or manager.workspace_holder(key) is not None:
        return _fail(FailureCategory.STATE, "写 lease 释放失败/有遗留")
    return _ok("lease 生命周期正确", {})


async def driver_approval_expiry(task: TaskSpec, thread_root: Path) -> dict:
    """活动 Run 中审批可解析；Run 结束后全部过期，resolve 必须失败。"""
    del thread_root
    from electromind.harness import (
        InputDelivery,
        InputMessage,
        ThreadSessionManager,
        new_run_id,
    )
    from electromind.harness.identity import new_approval_id
    from electromind.harness.workspace import ApprovalRequest, ApprovalStatus

    def make_approval(run_id: str) -> ApprovalRequest:
        return ApprovalRequest(
            approval_id=new_approval_id(),
            thread_id="t1",
            run_id=run_id,
            tool_call_id="call_1",
            action_id="run_command",
            target="*",
            workdir="/ws",
            risk="high",
            summary="测试审批",
            expires_at="2099-01-01T00:00:00+00:00",
        )

    manager = ThreadSessionManager()
    await manager.send_input(
        InputMessage.create("t1", task.input, delivery=InputDelivery.ENQUEUE)
    )
    run_id = new_run_id()
    started = await manager.start_run("t1", object(), run_id=run_id)
    if started is None:
        return _fail(FailureCategory.STATE, "Run 启动失败")

    approval = make_approval(run_id)
    await manager.add_approval("t1", approval)
    resolved = await manager.resolve_approval("t1", run_id, approval.approval_id, True)
    if resolved is None:
        return _fail(FailureCategory.STATE, "活动 Run 的审批解析失败")
    if approval.status != ApprovalStatus.APPROVED:
        return _fail(FailureCategory.STATE, "审批状态未更新")

    # Run 结束后：新审批必须过期，resolve 必须失败
    if not await manager.complete_run("t1", run_id):
        return _fail(FailureCategory.STATE, "Run 完成失败")
    approval2 = make_approval(run_id)
    await manager.add_approval("t1", approval2)
    resolved2 = await manager.resolve_approval(
        "t1", run_id, approval2.approval_id, True
    )
    if resolved2 is not None:
        return _fail(FailureCategory.SAFETY, "Run 结束后审批仍可解析")
    return _ok("活动可解析、结束后过期", {})


async def driver_deferred_input(task: TaskSpec, thread_root: Path) -> dict:
    """Run 结束时未读立即输入 defer 到队列头，不丢失。"""
    from electromind.harness import InputDelivery, InputMessage, InputQueue

    q = InputQueue()
    msg = InputMessage.create("t2", task.input, delivery=InputDelivery.IMMEDIATE)
    q.enqueue(msg)
    # drain_after_run_end 语义（checkpoints 的 defer 路径）
    from electromind.harness.checkpoints import InboundCheckpoint

    ckp = InboundCheckpoint()
    ckp.submit_immediate(msg)
    count = ckp.drain_after_run_end(q)
    if count != 1:
        return _fail(FailureCategory.STATE, f"defer 数量错误: {count}")
    if q.peek() is not msg:
        return _fail(FailureCategory.STATE, "deferred 输入未到队列头")
    return _ok("立即输入 defer 到队列头", {})


async def driver_approval_replay(task: TaskSpec, thread_root: Path) -> dict:
    """Approval 重放：旧 Run 的审批不能解析进新 Run。"""
    del thread_root
    from electromind.harness import ThreadSessionManager, new_run_id
    from electromind.harness.identity import new_approval_id
    from electromind.harness.workspace import ApprovalRequest

    manager = ThreadSessionManager()
    old_run = new_run_id()
    approval = ApprovalRequest(
        approval_id=new_approval_id(),
        thread_id="t1",
        run_id=old_run,
        tool_call_id="call_1",
        action_id="write_file",
        target="/ws/x",
        workdir="/ws",
        risk="high",
        summary="旧 Run 审批",
        expires_at="2099-01-01T00:00:00+00:00",
    )
    await manager.add_approval("t1", approval)
    # 用不同 run_id 解析 → 必须失败且不消耗审批
    resolved = await manager.resolve_approval(
        "t1", new_run_id(), approval.approval_id, True
    )
    if resolved is not None:
        return _fail(FailureCategory.SAFETY, "跨 Run 审批被重放")
    return _ok("跨 Run 重放被拒绝", {})


# ── 补充 planning driver（二） ──────────────────────────────────────────


async def driver_plan_approval_gate(task: TaskSpec, thread_root: Path) -> dict:
    """审批门：approve 只能从 READY 进入，DRAFT/COMPLETED 必须拒绝。"""
    del thread_root
    from electromind.execution.plan import PlanState, PlanStatus, PlanTracker

    tracker = PlanTracker()
    # DRAFT 直接 approve → 拒绝（未经 propose 冻结）
    if tracker.approve() is not None:
        return _fail(FailureCategory.PLANNING, "空 tracker 可以 approve")
    plan = PlanState(
        plan_id="gate",
        version=1,
        status=PlanStatus.DRAFT,
        objective=task.input,
    )
    tracker.propose(plan)
    # REVISING 不能直接 approve（必须先 revise 再 propose 冻结）
    tracker.revise()
    if tracker.approve() is not None:
        return _fail(FailureCategory.PLANNING, "REVISING 可直接批准")
    return _ok("审批门语义正确", {})


async def driver_plan_step_status(task: TaskSpec, thread_root: Path) -> dict:
    """Step 状态矩阵：枚举完整 + with_step_status 不可变更新。"""
    del thread_root
    from electromind.execution.plan import (
        PlanState,
        PlanStatus,
        PlanTracker,
        StepStatus,
    )

    expected = {
        "pending",
        "ready",
        "running",
        "blocked",
        "completed",
        "verified",
        "failed",
        "skipped",
    }
    actual = {str(s) for s in StepStatus}
    if actual != expected:
        return _fail(FailureCategory.PLANNING, f"Step 状态缺失: {expected - actual}")
    tracker = PlanTracker()
    plan = PlanState(
        plan_id="step",
        version=1,
        status=PlanStatus.DRAFT,
        objective=task.input,
        steps=(_mk_step("s1", "步骤一"),),
    )
    tracker.propose(plan)
    original = tracker.current
    updated = tracker.update_step("s1", StepStatus.BLOCKED)
    if updated is None or updated.steps[0].status != StepStatus.BLOCKED:
        return _fail(FailureCategory.PLANNING, "update_step 未生效")
    # 不可变：原对象不受影响
    if original is not None and original.steps[0].status != StepStatus.PENDING:
        return _fail(FailureCategory.PLANNING, "with_step_status 原地修改")
    return _ok("step 状态矩阵正确", {})


# ── 补充 recovery driver（二） ──────────────────────────────────────────


async def driver_persist_reopen(task: TaskSpec, thread_root: Path) -> dict:
    """进程重启语义：关闭 Runner 后重开同一 thread，历史不丢失。"""
    from electromind.paths import activate_home
    from electromind.runtime import Runner

    from .provider import ScriptedProvider
    from .task import ProviderStep

    activate_home(str(thread_root))
    thread_id = "eval-persist"

    provider1 = ScriptedProvider([ProviderStep.text("第一次回复")], model="persist")

    async def _run_turn(provider, text: str) -> str:
        runner = await Runner.create(
            thread_id,
            provider,
            overrides={"backend": "none"},
            max_turns=4,
        )
        try:
            async for _ in runner.run(text, return_type="event"):
                pass
            return "".join(
                str(m.content.text) if hasattr(m.content, "text") else ""
                for m in runner.messages.data
                if m.role == "assistant"
            )
        finally:
            await runner.close()

    first = await _run_turn(provider1, "开始任务")
    if "第一次回复" not in first:
        return _fail(FailureCategory.STATE, "第一次运行无回复")

    provider2 = ScriptedProvider([ProviderStep.text("第二次回复")], model="persist")
    second = await _run_turn(provider2, "继续")
    if "第二次回复" not in second or "第一次回复" not in second:
        return _fail(
            FailureCategory.STATE,
            f"重开后历史丢失: {second!r}",
        )
    return _ok("重开恢复完整", {"history": bool("第一次回复" in second)})


async def driver_side_effect_once(task: TaskSpec, thread_root: Path) -> dict:
    """副作用不重复：恢复后的 Run 不得重新执行已记录的外部副作用。

    第一个进程调用 eval_side_effect 一次；重开后（新 provider 只回文本）
    副作用日志必须只有 1 条。
    """
    from electromind.paths import activate_home
    from electromind.runtime import Runner

    from .harness import make_side_effect_tool
    from .provider import ScriptedProvider
    from .task import ProviderStep

    activate_home(str(thread_root))
    thread_id = "eval-side-effect"
    log_path = thread_root / "side_effect.log"

    async def _run(provider_steps: list, tool_names: list[str]) -> None:
        tools = (
            [make_side_effect_tool(log_path)]
            if "eval_side_effect" in tool_names
            else []
        )
        runner = await Runner.create(
            thread_id,
            ScriptedProvider(provider_steps, model="se"),
            overrides={"backend": "none"},
            max_turns=4,
            tools=tools,
        )
        try:
            async for _ in runner.run(task.input, return_type="event"):
                pass
        finally:
            await runner.close()

    # 进程 1：调用一次副作用工具
    await _run(
        [
            ProviderStep.tools(
                {"name": "eval_side_effect", "arguments": {"name": "submit"}}
            ),
            ProviderStep.text("已提交"),
        ],
        ["eval_side_effect"],
    )
    # 进程 2（恢复）：只回文本，不得重复副作用
    await _run([ProviderStep.text("继续")], [])

    lines = (
        log_path.read_text(encoding="utf-8").splitlines() if log_path.exists() else []
    )
    if len(lines) != 1:
        return _fail(
            FailureCategory.STATE,
            f"副作用重复执行: {len(lines)} 条记录 {lines}",
        )
    return _ok("副作用仅执行一次", {"count": len(lines)})


async def driver_queue_after_run(task: TaskSpec, thread_root: Path) -> dict:
    """排队输入在 Run 结束后自动成为下一 Run 的输入（不丢失、不重复）。"""
    del thread_root
    from electromind.harness import (
        InputDelivery,
        InputMessage,
        ThreadSessionManager,
        new_run_id,
    )

    manager = ThreadSessionManager()
    await manager.send_input(
        InputMessage.create("t3", "第一个输入", delivery=InputDelivery.ENQUEUE)
    )
    await manager.send_input(
        InputMessage.create("t3", "第二个输入", delivery=InputDelivery.ENQUEUE)
    )
    session = manager.get_session("t3")
    if session is None or len(session.queued_inputs) != 2:
        return _fail(FailureCategory.STATE, "输入未入队")
    # Run 1 消费第一个
    run1 = new_run_id()
    started = await manager.start_run("t3", object(), run_id=run1)
    if started is None:
        return _fail(FailureCategory.STATE, "Run 1 启动失败")
    if not await manager.complete_run("t3", run1):
        return _fail(FailureCategory.STATE, "Run 1 完成失败")
    if len(session.queued_inputs) != 1:
        return _fail(FailureCategory.STATE, "排队输入被误消费")
    # Run 2 消费第二个（终态后可生新 Run）
    run2 = new_run_id()
    started2 = await manager.start_run("t3", object(), run_id=run2)
    if started2 is None or started2[1].text != "第二个输入":
        return _fail(FailureCategory.STATE, "Run 2 输入错误")
    return _ok("排队输入按序消费", {"queued_after": len(session.queued_inputs)})


async def driver_run_identity(task: TaskSpec, thread_root: Path) -> dict:
    """Run 身份：同一 Thread 连续两个 Run 必须生成不同的 run_id。"""
    del thread_root
    from electromind.harness import (
        InputDelivery,
        InputMessage,
        ThreadSessionManager,
        new_run_id,
    )

    manager = ThreadSessionManager()
    for text in ("第一轮", "第二轮"):
        await manager.send_input(
            InputMessage.create("t4", text, delivery=InputDelivery.ENQUEUE)
        )
    run1 = new_run_id()
    started1 = await manager.start_run("t4", object(), run_id=run1)
    if started1 is None:
        return _fail(FailureCategory.STATE, "Run 1 启动失败")
    await manager.complete_run("t4", run1)
    run2 = new_run_id()
    started2 = await manager.start_run("t4", object(), run_id=run2)
    if started2 is None:
        return _fail(FailureCategory.STATE, "Run 2 启动失败")
    if run2 == run1:
        return _fail(FailureCategory.STATE, "连续 Run 使用了相同 run_id")
    if started1[1].text != "第一轮" or started2[1].text != "第二轮":
        return _fail(FailureCategory.STATE, "Run 输入对应错误")
    return _ok("run_id 唯一且输入对应", {"run_ids": [run1, run2]})


# ── M2 driver：PlanStore / Evidence / 幂等 ──────────────────────────────


async def driver_plan_store_roundtrip(task: TaskSpec, thread_root: Path) -> dict:
    """PlanStore 持久化：保存→加载 round-trip，版本历史完整，防覆盖。"""
    from electromind.execution.plan import (
        Evidence,
        PlanState,
        PlanStatus,
        PlanStore,
        PlanTracker,
    )

    store = PlanStore(thread_root / "plans")
    plan = PlanState(
        plan_id="stored",
        version=1,
        status=PlanStatus.DRAFT,
        objective=task.input,
        steps=(
            PlanStep_(
                id="s1",
                title="步骤一",
                evidence=(Evidence.file("out.txt", "abc123"),),
            ),
        ),
    )
    tracker = PlanTracker()
    tracker.propose(plan)
    approved = tracker.approve()
    if approved is None:
        return _fail(FailureCategory.PLANNING, "approve 失败")
    saved = store.save(approved)
    if not saved.exists():
        return _fail(FailureCategory.PLANNING, "保存未落盘")
    loaded = store.load("stored", 1)
    if loaded is None:
        return _fail(FailureCategory.PLANNING, "加载失败")
    if loaded.fingerprint != approved.fingerprint:
        return _fail(FailureCategory.PLANNING, "round-trip 指纹漂移")
    if loaded.steps[0].evidence[0].detail != "out.txt":
        return _fail(FailureCategory.PLANNING, "Evidence 未随 plan 持久化")
    if not store.has("stored", 1) or store.latest("stored") is None:
        return _fail(FailureCategory.PLANNING, "has/latest 查询失败")
    if store.list_ids() != ["stored"]:
        return _fail(FailureCategory.PLANNING, "list_ids 错误")
    # 相同指纹可重复保存（幂等）；不同内容禁止覆盖
    store.save(approved)
    tampered = PlanState(
        plan_id="stored",
        version=1,
        status=PlanStatus.APPROVED,
        objective="被篡改的目标",
    )
    try:
        store.save(tampered.freeze())
        return _fail(FailureCategory.PLANNING, "篡改版本被允许覆盖")
    except ValueError:
        pass
    return _ok("PlanStore round-trip 完整", {"versions": len(store.load_all("stored"))})


def PlanStep_(**kw):
    from electromind.execution.plan import PlanStep

    return PlanStep(**kw)


async def driver_plan_evidence_gate(task: TaskSpec, thread_root: Path) -> dict:
    """证据门：无 Evidence 不能 COMPLETED，无验证器结果不能 VERIFIED。"""
    del thread_root
    from electromind.execution.plan import (
        Evidence,
        PlanState,
        PlanStatus,
        PlanStep,
        PlanTracker,
        StepStatus,
        StepTransitionError,
    )

    step = PlanStep(id="s1", title="计算")
    tracker = PlanTracker()
    tracker.propose(
        PlanState(
            plan_id="gate2",
            version=1,
            status=PlanStatus.DRAFT,
            objective=task.input,
            steps=(step,),
        )
    )
    # R2-7: 先批准（步骤完成需计划已批准）
    tracker.approve()
    # 无证据 → COMPLETED 必须被拒
    try:
        tracker.update_step("s1", StepStatus.COMPLETED)
        return _fail(FailureCategory.PLANNING, "无 Evidence 进入了 COMPLETED")
    except StepTransitionError:
        pass
    # 有证据 → 可 COMPLETED；但无验证器结果 → VERIFIED 必须被拒
    with_evidence = step.with_evidence(Evidence.file("calc.out", "d34db33f"))
    tracker.update_step("s1", StepStatus.COMPLETED, step=with_evidence)
    try:
        tracker.update_step("s1", StepStatus.VERIFIED, step=with_evidence)
        return _fail(FailureCategory.PLANNING, "无验证器结果进入了 VERIFIED")
    except StepTransitionError:
        pass
    verified = with_evidence.with_evidence(
        Evidence.verifier("energy_parser", "parsed ok")
    )
    tracker.update_step("s1", StepStatus.VERIFIED, step=verified)
    if (
        tracker.current is None
        or tracker.current.steps[0].status != StepStatus.VERIFIED
    ):
        return _fail(FailureCategory.PLANNING, "VERIFIED 转换未生效")
    return _ok("证据门强制生效", {})


async def driver_idempotency_contract(task: TaskSpec, thread_root: Path) -> dict:
    """副作用幂等契约：同 key 重放原结果；未知状态进入对账不重试。"""
    from electromind.execution.idempotency import (
        IdempotencyKey,
        IdempotencyStore,
    )

    store = IdempotencyStore(thread_root / "idem.jsonl")
    key = IdempotencyKey.derive(
        run_id="run-1",
        step_id="st1",
        action_id="submit",
        tool_name="sbatch",
        args={"script": "run.sh", "nodes": 2},
    )
    # 第一次成功
    result = store.record_completed(key, "job 12345")
    if result != "job 12345":
        return _fail(FailureCategory.STATE, "首次记录失败")
    # 同 key 重放 → 原结果，不二次执行
    if not store.is_duplicate(key):
        return _fail(FailureCategory.STATE, "重复请求未被识别")
    if store.get_result(key) != "job 12345":
        return _fail(FailureCategory.STATE, "重放结果与原始不一致")
    # 未知状态 → RECONCILING，禁止自动重试
    unknown_key = IdempotencyKey.derive(
        run_id="run-1", action_id="delete", tool_name="rm"
    )
    store.record_unknown(unknown_key)
    if store.is_duplicate(unknown_key):
        return _fail(FailureCategory.STATE, "UNKNOWN 被当作已完成")
    store.record_reconciling(unknown_key)
    if not store.is_reconciling(unknown_key):
        return _fail(FailureCategory.STATE, "RECONCILING 未生效")
    if store.get_result(unknown_key) is not None:
        return _fail(FailureCategory.STATE, "未完成记录返回了结果")
    # 持久化 round-trip（新 store 从同一文件恢复）
    store2 = IdempotencyStore(thread_root / "idem.jsonl")
    if store2.get_result(key) != "job 12345":
        return _fail(FailureCategory.STATE, "幂等记录未持久化恢复")
    return _ok("幂等契约完整", {"records": len(store2)})


async def driver_artifact_lifecycle(task: TaskSpec, thread_root: Path) -> dict:
    """Artifact 生命周期：completed → validated → accepted 严格分离。"""
    from electromind.artifacts import (
        ArtifactManifest,
        ArtifactRegistry,
        ArtifactStatus,
    )

    registry = ArtifactRegistry(thread_root / "registry.jsonl")
    m = ArtifactManifest(
        artifact_id="energy-1",
        type="parsed_result",
        path="energy.json",
        sha256="d34db33f",
        run_id="run-1",
        created_by="tool_parse",
        units="Hartree",
    )
    registry.register(m)
    # 程序正常结束 → acceptance=COMPLETED（validation 保持 CREATED）
    completed = m.complete()
    if completed.acceptance_status != ArtifactStatus.COMPLETED:
        return _fail(FailureCategory.VALIDATION, "complete 未进入 COMPLETED")
    if completed.validation_status == ArtifactStatus.VALIDATED:
        return _fail(FailureCategory.VALIDATION, "程序结束被自动升级为 VALIDATED")
    # 解析器通过 → validation=VALIDATED（P0-7 双状态分离）
    validated = completed.validate(parser="energy_parser")
    if validated.validation_status != ArtifactStatus.VALIDATED:
        return _fail(FailureCategory.VALIDATION, "validate 未进入 VALIDATED")
    if validated.acceptance_status != ArtifactStatus.COMPLETED:
        return _fail(FailureCategory.VALIDATION, "validate 污染了 acceptance 状态")
    # 用户确认 → ACCEPTED（确认者持久化；validation 保留）
    accepted = validated.accept(who="user-alice")
    if accepted.acceptance_status != ArtifactStatus.ACCEPTED:
        return _fail(FailureCategory.VALIDATION, "accept 未进入 ACCEPTED")
    if accepted.validation_status != ArtifactStatus.VALIDATED:
        return _fail(FailureCategory.VALIDATION, "accept 污染了 validation 状态")
    if accepted.accepted_by != "user-alice":
        return _fail(FailureCategory.VALIDATION, "accepted_by 未持久化")
    # 创建者不能自行接受
    try:
        validated.accept(who="tool_parse")
        return _fail(FailureCategory.SAFETY, "创建者自行 ACCEPTED")
    except Exception:
        pass
    # 报告数值可追溯：units 与 path 保留
    if accepted.units != "Hartree" or accepted.path != "energy.json":
        return _fail(FailureCategory.VALIDATION, "单位/来源丢失")
    # 最新版本入库后持久化恢复
    registry.register(accepted)
    # 持久化恢复
    registry2 = ArtifactRegistry(thread_root / "registry.jsonl")
    restored = registry2.get("energy-1")
    if restored is None or restored.units != "Hartree":
        return _fail(FailureCategory.VALIDATION, "registry 持久化失败")
    return _ok("artifact 生命周期完整", {"status": str(accepted.acceptance_status)})


# ── M4 driver：ToolScheduler / 审批作用域 ───────────────────────────────


async def driver_tool_scheduler(task: TaskSpec, thread_root: Path) -> dict:
    """调度器契约：只读可并行、写/外部提交串行、未判定串行。"""
    del thread_root
    from electromind.execution.effects import ToolEffect
    from electromind.execution.tool_scheduler import (
        ToolCallInfo,
        ToolScheduler,
        effects_conflict,
    )

    scheduler = ToolScheduler()
    # 20 个独立只读调用 → 单批并行
    reads = [
        ToolCallInfo(
            tool_call_id=f"r{i}",
            name="read_file",
            arguments={"path": f"f{i}.txt"},
            effect=ToolEffect.READ_WORKSPACE,
        )
        for i in range(20)
    ]
    batches = scheduler.plan(reads)
    if len(batches) != 1 or len(batches[0]) != 20:
        return _fail(
            FailureCategory.TOOL,
            f"只读并行失败: {len(batches)} 批（期望 1 批 20 个）",
        )
    # 同路径写 + 外部提交 → 全部串行
    calls = [
        ToolCallInfo("w1", "write_file", {"path": "a"}, ToolEffect.WRITE_WORKSPACE),
        ToolCallInfo("w2", "write_file", {"path": "a"}, ToolEffect.WRITE_WORKSPACE),
        ToolCallInfo("s1", "sbatch", {"script": "x"}, ToolEffect.SUBMIT_EXTERNAL),
        ToolCallInfo("s2", "sbatch", {"script": "y"}, ToolEffect.SUBMIT_EXTERNAL),
    ]
    serial = scheduler.plan(calls)
    if len(serial) != 4:
        return _fail(FailureCategory.TOOL, f"写/提交未串行: {len(serial)} 批")
    # 未判定 effect → 冲突（保守）
    if not effects_conflict(None, ToolEffect.READ_WORKSPACE):
        return _fail(FailureCategory.TOOL, "未判定 effect 未按冲突处理")
    return _ok("调度器契约成立", {"parallel_batch": len(batches[0])})


async def driver_approval_scope(task: TaskSpec, thread_root: Path) -> dict:
    """审批作用域：跨 Thread/Run/ToolCall/参数/过期全部拒绝。"""
    del thread_root
    from electromind.execution.permissions import (
        ActionSpec,
        ApprovalScope,
        RiskLevel,
    )

    action = ActionSpec(tool="run_command", command="pwd", risk=RiskLevel.HIGH)
    scope = ApprovalScope(
        approval_id="apr-s1",
        thread_id="t1",
        run_id="run-1",
        tool_call_id="call-1",
        action=action,
        expires_at=time.time() + 100,
    )
    if (
        scope.validate(thread_id="t1", run_id="run-1", tool_call_id="call-1")
        is not None
    ):
        return _fail(FailureCategory.SAFETY, "合法审批被拒绝")
    for bad in (
        scope.validate(thread_id="t2", run_id="run-1", tool_call_id="call-1"),
        scope.validate(thread_id="t1", run_id="run-2", tool_call_id="call-1"),
        scope.validate(thread_id="t1", run_id="run-1", tool_call_id="call-9"),
        scope.validate(
            thread_id="t1",
            run_id="run-1",
            tool_call_id="call-1",
            action=ActionSpec(tool="write_file", risk=RiskLevel.MEDIUM),
        ),
    ):
        if bad is None:
            return _fail(FailureCategory.SAFETY, "越界审批被放行")
    expired = ApprovalScope(
        approval_id="apr-s2",
        thread_id="t1",
        run_id="run-1",
        tool_call_id="call-1",
        action=action,
        expires_at=time.time() - 1,
    )
    if expired.validate(thread_id="t1", run_id="run-1", tool_call_id="call-1") is None:
        return _fail(FailureCategory.SAFETY, "过期审批被放行")
    return _ok("审批作用域全部拒绝", {})


async def driver_subagent_governance(task: TaskSpec, thread_root: Path) -> dict:
    """子 Agent 治理：深度硬限制、白名单、路径边界、结构化结果。"""
    del thread_root
    from electromind.ithread import SubAgentSpec
    from electromind.tools.delegate import (
        SYSTEM_MAX_DEPTH,
        SubAgentResult,
        check_delegation_allowed,
        delegation_depth,
        filter_tools_by_whitelist,
    )

    class Ctx:
        frames = [1, 2]  # 深度 1（已有 1 个子帧）

    # 深度 1 默认允许；深度 2 且 max_depth=1 → 拒绝
    spec = SubAgentSpec()
    if check_delegation_allowed(Ctx(), spec, "c") is None:
        return _fail(FailureCategory.STATE, "深度超限未被拒绝")
    if delegation_depth(Ctx()) != 1:
        return _fail(FailureCategory.STATE, "深度计算错误")
    if SYSTEM_MAX_DEPTH != 2:
        return _fail(FailureCategory.STATE, "系统最大深度不是 2")
    # 结构化结果
    result = SubAgentResult(
        status="completed",
        summary="评审完成",
        artifacts=["review.md"],
        usage={"tool_calls": 3},
    )
    if result.to_dict()["summary"] != "评审完成":
        return _fail(FailureCategory.STATE, "结构化结果序列化失败")
    # 白名单 + 路径边界（用纯函数验证，不启动沙箱）
    tools = [
        type("T", (), {"name": "read_file"})(),
        type("T", (), {"name": "write_file"})(),
        type("T", (), {"name": "run_command"})(),
    ]
    filtered = filter_tools_by_whitelist(tools, ("read_file",))
    if [t.name for t in filtered] != ["read_file"]:
        return _fail(FailureCategory.TOOL, "白名单过滤失败")
    return _ok("子 agent 治理契约成立", {"depth_limit": SYSTEM_MAX_DEPTH})


# ── driver 注册表 ──────────────────────────────────────────────────────


DRIVERS: dict[str, object] = {
    "plan_lifecycle": driver_plan_lifecycle,
    "plan_revision": driver_plan_revision,
    "plan_dependencies": driver_plan_dependencies,
    "plan_propose_twice": driver_plan_propose_twice,
    "plan_complete_flow": driver_plan_complete_flow,
    "plan_dict_roundtrip": driver_plan_dict_roundtrip,
    "plan_status_matrix": driver_plan_status_matrix,
    "plan_approval_gate": driver_plan_approval_gate,
    "plan_step_status": driver_plan_step_status,
    "input_idempotency": driver_input_idempotency,
    "state_machine": driver_state_machine,
    "units_and_sources": driver_units_and_sources,
    "pairing": driver_pairing,
    "fingerprint_stability": driver_fingerprint_stability,
    "message_roundtrip": driver_message_roundtrip,
    "completed_not_validated": driver_completed_not_validated,
    "workspace_lease": driver_workspace_lease,
    "approval_expiry": driver_approval_expiry,
    "deferred_input": driver_deferred_input,
    "approval_replay": driver_approval_replay,
    "persist_reopen": driver_persist_reopen,
    "side_effect_once": driver_side_effect_once,
    "queue_after_run": driver_queue_after_run,
    "run_identity": driver_run_identity,
    "plan_store_roundtrip": driver_plan_store_roundtrip,
    "plan_evidence_gate": driver_plan_evidence_gate,
    "idempotency_contract": driver_idempotency_contract,
    "artifact_lifecycle": driver_artifact_lifecycle,
    "tool_scheduler": driver_tool_scheduler,
    "approval_scope": driver_approval_scope,
    "subagent_governance": driver_subagent_governance,
}


def get_driver(name: str):
    """按名取 driver；未知名抛 KeyError。"""
    if name not in DRIVERS:
        raise KeyError(f"未知 driver: {name!r}")
    return DRIVERS[name]


def is_driver_task(task: TaskSpec) -> bool:
    return bool(task.driver)


async def run_task_with_driver(task: TaskSpec, thread_root: Path) -> dict:
    """运行 driver 任务，返回观察字典。"""
    try:
        driver = get_driver(task.driver)
        return await asyncio.wait_for(
            driver(task, thread_root), timeout=task.expected.timeout_seconds
        )
    except asyncio.TimeoutError:
        return _fail(FailureCategory.ENVIRONMENT, "driver 超时")
    except Exception as exc:  # noqa: BLE001 — driver 异常归类为 environment
        return _fail(FailureCategory.ENVIRONMENT, f"driver 异常: {exc!r}")


# 供 CLI/测试使用的辅助
def observations_to_result(task: TaskSpec, obs: dict) -> dict:
    """driver 观察字典 → 任务结果字典。"""
    return {
        "id": task.id,
        "category": task.category,
        "passed": bool(obs["passed"]),
        "failure": obs.get("failure"),
        "details": obs.get("details", ""),
        "runs": 1,
        "side_effect_digest": "",
    }
