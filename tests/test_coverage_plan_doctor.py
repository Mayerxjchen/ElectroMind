"""Coverage fillers: execution/plan.py 与 app/commands/doctor.py 行为测试。

这些模块此前无测试（0% 覆盖）；补行为测试以满足 A+ v1.0 覆盖率门禁
（>= max(78%, baseline)）。
"""

from __future__ import annotations

from electromind.execution.plan import (
    PlanState,
    PlanStatus,
    PlanStep,
    PlanTracker,
    StepStatus,
)


def _step(step_id: str, **kw) -> PlanStep:
    base = dict(
        id=step_id,
        title=f"Step {step_id}",
        description="desc",
        files=(),
        tools=(),
        depends_on=(),
    )
    base.update(kw)
    return PlanStep(**base)


def _plan(**kw) -> PlanState:
    base = dict(
        plan_id="p1",
        version=1,
        status=PlanStatus.DRAFT,
        objective="objective",
        assumptions=("a1",),
        questions=("q1",),
        steps=(_step("s1"), _step("s2", depends_on=("s1",))),
        risks=("r1",),
        verification=("v1",),
    )
    base.update(kw)
    return PlanState(**base)


class TestPlanState:
    def test_fingerprint_content_addressed(self):
        p1 = _plan().freeze()
        p2 = _plan(objective="different").freeze()
        assert p1.fingerprint != p2.fingerprint
        assert len(p1.fingerprint) == 64

    def test_freeze_sets_ready_status(self):
        frozen = _plan().freeze()
        assert frozen.status == PlanStatus.READY
        assert frozen.fingerprint

    def test_approve_sets_approved_and_time(self):
        frozen = _plan().freeze()
        approved = frozen.approve()
        assert approved.status == PlanStatus.APPROVED
        assert approved.approved_at is not None
        assert approved.fingerprint == frozen.fingerprint

    def test_with_step_status_updates_one_step(self):
        frozen = _plan().freeze()
        updated = frozen.with_step_status("s2", StepStatus.RUNNING)
        statuses = {s.id: s.status for s in updated.steps}
        assert statuses["s2"] == StepStatus.RUNNING
        assert statuses["s1"] == StepStatus.PENDING
        assert updated.fingerprint == frozen.fingerprint

    def test_to_dict_round_trip(self):
        frozen = _plan().freeze()
        data = frozen.to_dict()
        assert data["plan_id"] == "p1"
        assert data["status"] == "ready"
        assert len(data["steps"]) == 2
        assert data["steps"][1]["depends_on"] == ["s1"]
        assert data["fingerprint"] == frozen.fingerprint


class TestPlanTracker:
    def test_propose_freeze_approve_complete_flow(self):
        tracker = PlanTracker()
        assert tracker.current is None
        assert tracker.approve() is None  # 无 plan
        assert tracker.complete() is None
        assert tracker.revise() is None
        assert tracker.update_step("s1", StepStatus.DONE) is None

        proposed = tracker.propose(_plan())
        assert tracker.current is not None
        assert proposed.status == PlanStatus.READY

        approved = tracker.approve()
        assert approved is not None
        assert approved.status == PlanStatus.APPROVED
        assert len(tracker.history) == 1

        # 已审批后再 approve → None（不能重复审批）
        assert tracker.approve() is None

        revised = tracker.revise()
        assert revised is not None
        assert revised.version == 2
        assert revised.status == PlanStatus.REVISING

        updated = tracker.update_step("s1", StepStatus.RUNNING)
        assert updated is not None
        statuses = {s.id: s.status for s in updated.steps}
        assert statuses["s1"] == StepStatus.RUNNING

        done = tracker.complete()
        assert done is not None
        assert done.status == PlanStatus.COMPLETED
        assert len(tracker.history) == 2


class TestDoctorCommand:
    def test_doctor_collects_checks_and_runs(self, tmp_path, monkeypatch):
        """doctor 收集检查项并输出报告；无 API key 时失败退出。"""

        from app.commands.doctor import collect_checks, run

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        report = collect_checks()
        assert len(report.checks) >= 1
        assert report.failed  # 无 key → 至少一项失败

        code = run([])
        assert code == 1  # 失败 → 退出 1

    def test_doctor_key_check_ok_when_configured(self, tmp_path, monkeypatch, capsys):
        """配置 API key 后 Provider Key 检查通过（check 级断言，不依赖容器）。"""
        from app.commands.doctor import collect_checks, run

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

        report = collect_checks()
        key_checks = [c for c in report.checks if "Provider Key" in c.name]
        assert key_checks and key_checks[0].ok

        # run() 正常输出报告且无异常（退出码反映全部检查）
        code = run([])
        assert code in (0, 1)
        out = capsys.readouterr().out
        assert "Provider Key" in out
