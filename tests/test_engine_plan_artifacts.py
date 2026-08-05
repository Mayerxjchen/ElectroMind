"""G1: RunEngine Plan / Artifact 领域状态接线测试。

覆盖：
- Plan 生命周期（propose → approve → revise / cancel）与磁盘持久化恢复
- 版本门（已批准版本不可覆盖）与 Evidence 门（无证据不得 COMPLETED）
- Artifact 生命周期（register → complete → validate → accept）与转换门
- state_emitter 变更推送（wire / CLI client 的接线契约）
- 协议常量（plan/state、artifact/state 进入 v2 协议）

conftest 的 HOME 隔离保证每个用例独立 home；同用例内两个引擎实例
共享同一磁盘（验证跨进程恢复语义）。
"""

from __future__ import annotations

import pytest

from electromind.artifacts.manifest import ArtifactManifest, ArtifactStatus
from electromind.engine import RunEngine
from electromind.execution.plan import (
    Evidence,
    PlanState,
    PlanStatus,
    PlanStep,
    StepStatus,
    StepTransitionError,
)
from electromind.harness.protocol_v2 import SERVER_EVENTS, VALID_COMMANDS

THREAD = "thread-g1-test"


def make_plan(objective: str = "测试目标") -> PlanState:
    return PlanState(
        plan_id="default",
        version=1,
        status=PlanStatus.DRAFT,
        objective=objective,
        steps=(PlanStep(id="s1", title="第一步", description="生成文件"),),
        verification=("文件存在且内容匹配",),
    )


def make_artifact(
    artifact_id: str = "a1", *, created_by: str = "tool-1"
) -> ArtifactManifest:
    return ArtifactManifest(
        artifact_id=artifact_id,
        type="data",
        path="out.txt",
        sha256="a" * 64,
        created_by=created_by,
    )


# ── Plan 生命周期 ─────────────────────────────────────────────────────


def test_plan_propose_approve_lifecycle():
    engine = RunEngine()
    proposed = engine.plan_propose(THREAD, make_plan())
    assert proposed.status == PlanStatus.READY  # propose 即冻结为 READY
    assert proposed.fingerprint  # 内容指纹已计算

    approved = engine.plan_approve(THREAD)
    assert approved is not None and approved.status == PlanStatus.APPROVED
    assert engine.plan_state(THREAD).status == PlanStatus.APPROVED

    # revise → 新版本（REVISING），已批准版本未被修改
    revised = engine.plan_revise(THREAD)
    assert revised is not None
    assert revised.version == 2 and revised.status == PlanStatus.REVISING

    cancelled = engine.plan_cancel(THREAD)
    assert cancelled is not None and cancelled.status == PlanStatus.CANCELLED


def test_plan_persists_and_restores_across_engine_instances():
    """PlanStore 落盘 <thread>/plans/；新引擎实例从磁盘恢复（跨进程恢复）。"""
    engine1 = RunEngine()
    engine1.plan_propose(THREAD, make_plan())
    engine1.plan_approve(THREAD)

    engine2 = RunEngine()  # 全新实例：内存空，从磁盘恢复
    restored = engine2.plan_state(THREAD)
    assert restored is not None
    assert restored.status == PlanStatus.APPROVED
    assert restored.objective == "测试目标"
    assert restored.steps[0].id == "s1"


def test_plan_version_gate_blocks_overwrite():
    engine = RunEngine()
    engine.plan_propose(THREAD, make_plan())
    engine.plan_approve(THREAD)
    # 已批准到 v1，再以 v1 覆盖必须被拒（必须 revise 提版本）
    with pytest.raises(ValueError, match="必须创建新版本"):
        engine.plan_propose(THREAD, make_plan(objective="篡改目标"))


def test_plan_step_evidence_gate():
    engine = RunEngine()
    engine.plan_propose(THREAD, make_plan())
    # 无 Evidence 标记 COMPLETED → 拒绝（禁止模型文本声明完成）
    with pytest.raises(StepTransitionError, match="无 Evidence"):
        engine.plan_update_step(THREAD, "s1", StepStatus.COMPLETED)
    # 带文件 Evidence 才可 COMPLETED
    step = PlanStep(
        id="s1",
        title="第一步",
        evidence=(Evidence.file("out.txt", "a" * 64, by="tool-1"),),
    )
    updated = engine.plan_update_step(THREAD, "s1", StepStatus.COMPLETED, step=step)
    assert updated is not None
    assert updated.steps[0].status == StepStatus.COMPLETED


def test_plan_noop_without_current():
    engine = RunEngine()
    assert engine.plan_state(THREAD) is None
    assert engine.plan_approve(THREAD) is None
    assert engine.plan_revise(THREAD) is None
    assert engine.plan_cancel(THREAD) is None


# ── Artifact 生命周期 ─────────────────────────────────────────────────


def test_artifact_full_lifecycle_with_transition_gates():
    engine = RunEngine()
    engine.artifact_register(THREAD, make_artifact())

    # CREATED → ACCEPTED 非法（跳过中间态）
    with pytest.raises(ValueError, match="非法转换"):
        engine.artifact_accept(THREAD, "a1", who="user")

    # 创建者不能自证 ACCEPTED
    engine.artifact_complete(THREAD, "a1")
    engine.artifact_validate(THREAD, "a1", parser="checker-1")
    with pytest.raises(ValueError, match="不能由创建者"):
        engine.artifact_accept(THREAD, "a1", who="tool-1")

    # 用户确认 → ACCEPTED
    accepted = engine.artifact_accept(THREAD, "a1", who="user")
    assert accepted is not None
    assert accepted.acceptance_status == ArtifactStatus.ACCEPTED

    # REJECTED 必须记录原因
    engine.artifact_register(THREAD, make_artifact(artifact_id="a2"))
    with pytest.raises(ValueError, match="必须记录原因"):
        engine.artifact_reject(THREAD, "a2", reason="")
    rejected = engine.artifact_reject(THREAD, "a2", reason="解析器报错")
    assert (
        rejected is not None and rejected.acceptance_status == ArtifactStatus.REJECTED
    )


def test_artifact_unknown_id_returns_none():
    engine = RunEngine()
    assert engine.artifact_accept(THREAD, "nope", who="user") is None
    assert engine.artifact_complete(THREAD, "nope") is None


def test_artifact_persists_across_engine_instances():
    engine1 = RunEngine()
    engine1.artifact_register(THREAD, make_artifact())
    engine1.artifact_complete(THREAD, "a1")

    engine2 = RunEngine()
    manifests = engine2.artifacts(THREAD)
    assert len(manifests) == 1
    assert manifests[0].artifact_id == "a1"
    assert manifests[0].acceptance_status == ArtifactStatus.COMPLETED


# ── state_emitter 推送契约 ────────────────────────────────────────────


def test_state_emitter_fires_on_mutations():
    engine = RunEngine()
    events: list[tuple[str, str, dict]] = []
    engine.state_emitter = lambda tid, kind, payload: events.append(
        (tid, kind, payload)
    )

    engine.plan_propose(THREAD, make_plan())
    engine.plan_approve(THREAD)
    engine.artifact_register(THREAD, make_artifact())

    kinds = [kind for _, kind, _ in events]
    assert kinds == ["plan", "plan", "artifact"]
    tid, kind, payload = events[0]
    assert tid == THREAD and kind == "plan"
    assert payload["plan"]["objective"] == "测试目标"
    assert events[2][2]["artifact"]["artifact_id"] == "a1"


# ── 协议常量 ──────────────────────────────────────────────────────────


def test_protocol_v2_declares_plan_artifact():
    for cmd in (
        "plan/state",
        "plan/propose",
        "plan/approve",
        "plan/revise",
        "plan/cancel",
        "plan/update-step",
        "artifact/state",
        "artifact/register",
        "artifact/accept",
        "artifact/reject",
        "artifact/complete",
        "artifact/validate",
    ):
        assert cmd in VALID_COMMANDS, cmd
    assert "plan/state" in SERVER_EVENTS
    assert "artifact/state" in SERVER_EVENTS
