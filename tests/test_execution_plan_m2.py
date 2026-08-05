"""M2: Plan 持久化 / Evidence / StepVerifier / 幂等契约测试。"""

from __future__ import annotations

import json

import pytest

from electromind.execution.idempotency import (
    IdempotencyKey,
    IdempotencyStore,
)
from electromind.execution.plan import (
    Evidence,
    EvidenceType,
    PlanState,
    PlanStatus,
    PlanStep,
    PlanStore,
    PlanTracker,
    StepStatus,
    StepTransitionError,
    StepVerifier,
)


def _step(step_id="s1", **kw) -> PlanStep:
    base = dict(id=step_id, title=f"步骤 {step_id}")
    base.update(kw)
    return PlanStep(**base)


def _plan(**kw) -> PlanState:
    base = dict(
        plan_id="p1",
        version=1,
        status=PlanStatus.DRAFT,
        objective="目标",
        steps=(_step("s1"), _step("s2", depends_on=("s1",))),
    )
    base.update(kw)
    return PlanState(**base)


# ── Evidence ────────────────────────────────────────────────────────────


def test_evidence_factories_and_roundtrip():
    e = Evidence.file("calc.out", "d34db33f", by="tool_call_1")
    assert e.kind == EvidenceType.FILE
    assert e.sha256 == "d34db33f"
    d = e.to_dict()
    assert Evidence.from_dict(d) == e

    assert Evidence.command("echo hi", 0).exit_code == 0
    assert Evidence.verifier("energy_parser", "ok").kind == EvidenceType.VERIFIER
    assert Evidence.approval("apr-1").by == "user"
    assert Evidence.job("job-1").detail == "job-1"
    assert Evidence.parser("p", "r").kind == EvidenceType.PARSER


# ── StepVerifier 门 ─────────────────────────────────────────────────────


def test_verifier_completed_requires_evidence():
    verifier = StepVerifier()
    step = _step()
    assert verifier.transition_error(step, StepStatus.COMPLETED) is not None
    with pytest.raises(StepTransitionError):
        verifier.assert_transition(step, StepStatus.COMPLETED)
    with_evidence = step.with_evidence(Evidence.tool_result("c1", "ok"))
    assert verifier.transition_error(with_evidence, StepStatus.COMPLETED) is None


def test_verifier_verified_requires_verifier_evidence():
    verifier = StepVerifier()
    step = _step(evidence=(Evidence.file("x", "y"),))
    assert verifier.transition_error(step, StepStatus.VERIFIED) is not None
    verified = step.with_evidence(Evidence.verifier("checker", "pass"))
    assert verifier.transition_error(verified, StepStatus.VERIFIED) is None


def test_verifier_skip_and_fail_require_reason():
    verifier = StepVerifier()
    assert verifier.transition_error(_step(), StepStatus.SKIPPED) is not None
    assert verifier.transition_error(_step(), StepStatus.FAILED) is not None
    assert (
        verifier.transition_error(_step(skipped_reason="用户要求"), StepStatus.SKIPPED)
        is None
    )
    assert (
        verifier.transition_error(_step(error="命令退出码 1"), StepStatus.FAILED)
        is None
    )


# ── PlanTracker 门 ──────────────────────────────────────────────────────


def test_tracker_blocks_completed_without_evidence():
    tracker = PlanTracker()
    tracker.propose(_plan())
    tracker.approve()  # R2-7: 步骤完成需计划已批准
    with pytest.raises(StepTransitionError):
        tracker.update_step("s1", StepStatus.COMPLETED)
    # 带证据可完成
    tracker.update_step(
        "s1",
        StepStatus.COMPLETED,
        step=_step("s1", evidence=(Evidence.file("a", "b"),)),
    )
    assert tracker.current.steps[0].status == StepStatus.COMPLETED


def test_tracker_rejects_overwrite_of_approved_version():
    tracker = PlanTracker()
    tracker.propose(_plan())
    tracker.approve()
    with pytest.raises(ValueError, match="已批准"):
        tracker.propose(_plan(version=1, objective="篡改"))
    # 新版本允许
    tracker.revise()
    tracker.propose(_plan(version=2, objective="修订版"))
    assert tracker.current.version == 2


def test_tracker_cancel():
    tracker = PlanTracker()
    tracker.propose(_plan())
    tracker.approve()
    cancelled = tracker.cancel()
    assert cancelled.status == PlanStatus.CANCELLED


# ── PlanStore ───────────────────────────────────────────────────────────


def test_plan_store_roundtrip_and_history(tmp_path):
    store = PlanStore(tmp_path / "t")
    approved = _plan().freeze().approve()
    store.save(approved)
    loaded = store.load("p1", 1)
    assert loaded is not None
    assert loaded.fingerprint == approved.fingerprint
    assert loaded == approved  # frozen dataclass 相等
    assert store.has("p1", 1)
    assert store.latest("p1") == approved
    assert store.list_ids() == ["p1"]

    # 新版本写入，历史保留
    v2 = _plan(version=2, objective="修订").freeze().approve()
    store.save(v2)
    all_versions = store.load_all("p1")
    assert [p.version for p in all_versions] == [1, 2]
    assert store.latest("p1").version == 2


def test_plan_store_rejects_tampered_overwrite(tmp_path):
    store = PlanStore(tmp_path / "t")
    approved = _plan().freeze().approve()
    store.save(approved)
    tampered = _plan(objective="被篡改").freeze()
    with pytest.raises(ValueError, match="禁止覆盖"):
        store.save(tampered)
    # 同指纹重复保存幂等
    store.save(approved)
    assert store.load("p1", 1).objective == "目标"


def test_plan_store_evidence_persisted(tmp_path):
    store = PlanStore(tmp_path / "t")
    plan = _plan(
        steps=(
            _step(
                "s1",
                evidence=(Evidence.command("python calc.py", 0),),
                error="",
            ),
        )
    ).freeze()
    store.save(plan)
    loaded = store.load("p1", 1)
    assert loaded.steps[0].evidence[0].kind == EvidenceType.COMMAND
    assert loaded.steps[0].evidence[0].exit_code == 0


def test_plan_store_load_missing_and_delete(tmp_path):
    store = PlanStore(tmp_path / "t")
    assert store.load("nope", 1) is None
    plan = _plan().freeze()
    store.save(plan)
    assert store.delete("p1", 1)
    assert not store.delete("p1", 1)
    assert store.load("p1", 1) is None


def test_plan_store_files_are_valid_json(tmp_path):
    store = PlanStore(tmp_path / "t")
    store.save(_plan().freeze())
    for path in (tmp_path / "t" / "plans").glob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))


# ── 指纹 ────────────────────────────────────────────────────────────────


def test_fingerprint_covers_m2_content_fields():
    base = dict(plan_id="fp", version=1, status=PlanStatus.DRAFT, objective="目标")
    p1 = PlanState(**base)
    p2 = PlanState(**base, steps=(_step(expected_artifacts=("out.txt",)),))
    assert p1.compute_fingerprint() != p2.compute_fingerprint()
    p3 = PlanState(**base, steps=(_step(effects=("write:out.txt",)),))
    assert p1.compute_fingerprint() != p3.compute_fingerprint()
    p4 = PlanState(**base, steps=(_step(verification=("收敛检查",)),))
    assert p1.compute_fingerprint() != p4.compute_fingerprint()
    # 状态与证据不污染指纹（同内容步骤、不同证据 → 指纹相同）
    pa = PlanState(**base, steps=(_step(),))
    pb = PlanState(**base, steps=(_step(evidence=(Evidence.file("a", "b"),)),))
    assert pa.compute_fingerprint() == pb.compute_fingerprint()


# ── 幂等 ────────────────────────────────────────────────────────────────


def test_idempotency_key_derive():
    k1 = IdempotencyKey.derive(
        run_id="r1", step_id="s", action_id="a", tool_name="sbatch", args={"x": 1}
    )
    k2 = IdempotencyKey.derive(
        run_id="r1", step_id="s", action_id="a", tool_name="sbatch", args={"x": 1}
    )
    k3 = IdempotencyKey.derive(
        run_id="r1", step_id="s", action_id="a", tool_name="sbatch", args={"x": 2}
    )
    assert k1 == k2
    assert k1 != k3
    assert str(k1).startswith("idem:r1:s:a:")
    # 参数顺序无关
    k4 = IdempotencyKey.derive(
        run_id="r1",
        step_id="s",
        action_id="a",
        tool_name="sbatch",
        args={"y": 2, "x": 1},
    )
    k5 = IdempotencyKey.derive(
        run_id="r1",
        step_id="s",
        action_id="a",
        tool_name="sbatch",
        args={"x": 1, "y": 2},
    )
    assert k4 == k5
    # 不同 run 隔离
    k6 = IdempotencyKey.derive(
        run_id="r2", step_id="s", action_id="a", tool_name="sbatch"
    )
    assert k6 != k1


def test_idempotency_store_replay_and_reconcile(tmp_path):
    store = IdempotencyStore(tmp_path / "idem.jsonl")
    key = IdempotencyKey.derive(run_id="r1", action_id="submit", tool_name="sbatch")
    assert store.record_completed(key, "job-1") == "job-1"
    # 重复请求重放原结果
    assert store.is_duplicate(key)
    assert store.get_result(key) == "job-1"
    assert store.record_completed(key, "job-2") == "job-1"  # 不二次执行
    # 未知 → 对账
    uk = IdempotencyKey.derive(run_id="r1", action_id="delete", tool_name="rm")
    store.record_unknown(uk)
    assert not store.is_duplicate(uk)
    assert store.get_result(uk) is None
    store.record_reconciling(uk)
    assert store.is_reconciling(uk)
    assert store.get_result(uk) is None


def test_idempotency_store_persistence(tmp_path):
    path = tmp_path / "idem.jsonl"
    store = IdempotencyStore(path)
    key = IdempotencyKey.derive(run_id="r9", action_id="upload", tool_name="scp")
    store.record_completed(key, "uploaded")
    store.record_reconciling(
        IdempotencyKey.derive(run_id="r9", action_id="del", tool_name="rm")
    )
    store2 = IdempotencyStore(path)
    assert store2.get_result(key) == "uploaded"
    assert len(store2) == 2
    # 损坏行 fail-soft
    path.write_text("not-json\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
    store3 = IdempotencyStore(path)
    assert store3.get_result(key) == "uploaded"


# ── P0-8 分支补足 ───────────────────────────────────────────────────────


def test_intent_log_branches(tmp_path):
    from electromind.execution.intent_log import IntentLog, IntentStatus

    log = IntentLog(tmp_path / "intent.jsonl")
    intent = log.record(
        run_id="r1", tool_call_id="c1", tool="write_file", arguments_digest="d"
    )
    # 未知 id 的 commit/reconcile/get → None
    assert log.commit("nope", "x") is None
    assert log.reconcile("nope") is None
    assert log.get("nope") is None
    # 正常 commit + 状态查询
    assert log.commit(intent.intent_id, "ref") is not None
    assert log.get(intent.intent_id).status == IntentStatus.COMMITTED
    assert log.committed_for("r1")[0].intent_id == intent.intent_id
    assert log.pending_for("r1") == []
    # reconcile
    i2 = log.record(run_id="r1", tool_call_id="c2", tool="rm", arguments_digest="d2")
    log.reconcile(i2.intent_id)
    assert log.pending_for("r1")[0].status == IntentStatus.RECONCILING
    # 持久化恢复 + 损坏行 fail-soft
    log2 = IntentLog(tmp_path / "intent.jsonl")
    assert len(log2) == 2
    path = tmp_path / "intent.jsonl"
    path.write_text("not-json\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
    log3 = IntentLog(path)
    assert len(log3) == 2


def test_idempotency_branches(tmp_path):
    from electromind.execution.idempotency import IdempotencyKey, IdempotencyStore

    store = IdempotencyStore(tmp_path / "idem.jsonl")
    key = IdempotencyKey.derive(run_id="r", tool_name="t")
    # record_unknown 覆盖已有 UNKNOWN
    store.record_unknown(key)
    store.record_unknown(key)
    assert not store.is_duplicate(key)
    assert not store.is_reconciling(key)
    # 未知 key 查询
    other = IdempotencyKey.derive(run_id="r2", tool_name="t2")
    assert store.get(other) is None
    assert not store.is_duplicate(other)
    assert not store.is_reconciling(other)
    assert store.get_result(other) is None
    # record_completed 覆盖 UNKNOWN
    store.record_completed(key, "ok")
    assert store.is_duplicate(key)
    assert store.get_result(key) == "ok"


def test_memory_branches():
    from electromind.context import ProjectMemory, ThreadMemory

    tm = ThreadMemory()
    tm.add_constraint("")
    tm.add_unresolved("")
    tm.add_decision("d1")
    for i in range(25):
        tm.add_decision(f"d{i}")
    assert len(tm.recent_decisions) == 20  # 裁剪
    pm = ProjectMemory()
    pm.set_convention("k", "v")
    assert pm.to_dict()["directory_conventions"] == {"k": "v"}


def test_tool_scheduler_branches():
    from electromind.execution.effects import ToolEffect
    from electromind.execution.tool_scheduler import ToolCallInfo, ToolScheduler

    scheduler = ToolScheduler()
    # resources() 无 path / 无 effect
    assert ToolCallInfo("a", "run_command", {}, None).resources() == set()
    assert ToolCallInfo(
        "b", "list_dir", {"path": "."}, ToolEffect.READ_WORKSPACE
    ).resources() == {"read_workspace:."}
    submit = ToolCallInfo("s", "sbatch", {}, ToolEffect.SUBMIT_EXTERNAL)
    assert "external:submit" in submit.resources()
    # serialize_all
    assert scheduler.serialize_all([submit]) == [[submit]]
    # effects_conflict 反向检查
    from electromind.execution.tool_scheduler import effects_conflict

    assert effects_conflict(ToolEffect.READ_HOST, ToolEffect.READ_WORKSPACE) is False
    assert effects_conflict(ToolEffect.READ_HOST, ToolEffect.WRITE_WORKSPACE) is True


def test_compactor_branches():
    from electromind.context import Compactor

    compactor = Compactor()
    assert compactor.compact([]) == ([], None)
    assert compactor.pairing_intact([]) is True
    # make_summary + to_dict
    c2 = Compactor(keep_recent_turns=1, make_summary=lambda t: "S")
    c2.compact([{"role": "user", "content": "a"}, {"role": "user", "content": "b"}])
    assert c2.to_dict()["keep_recent_turns"] == 1


def test_manifest_branches():
    from electromind.artifacts import ArtifactManifest
    from electromind.artifacts.manifest import ArtifactTransitionError

    m = ArtifactManifest(artifact_id="x", type="t", path="p", sha256="s")
    with pytest.raises(ArtifactTransitionError, match="替代者"):
        m.supersede(by="")
    with pytest.raises(ArtifactTransitionError, match="角色"):
        m.complete().accept(who="alice", role="robot")
    # from_dict 默认
    d = ArtifactManifest.from_dict(
        {"artifact_id": "y", "type": "t", "path": "p", "sha256": "s"}
    )
    assert d.accepted_by == "" and d.created_by_role == "agent"
    # accepted_by 保留 round-trip
    m2 = m.complete().validate(parser="p").accept(who="user")
    restored = ArtifactManifest.from_dict(m2.to_dict())
    assert restored.accepted_by == "user"
    assert restored.validation_status == "validated"
    assert restored.acceptance_status == "accepted"


def test_idempotency_no_path_branches(tmp_path):
    from electromind.execution.idempotency import IdempotencyKey, IdempotencyStore

    mem = IdempotencyStore()  # 无 path → 不落盘
    key = IdempotencyKey.derive(run_id="r", tool_name="t")
    mem.record_completed(key, "ok")
    assert mem.get_result(key) == "ok"
    # 损坏行 fail-soft
    path = tmp_path / "idem.jsonl"
    path.write_text("bad\n", encoding="utf-8")
    store = IdempotencyStore(path)
    assert len(store) == 0
