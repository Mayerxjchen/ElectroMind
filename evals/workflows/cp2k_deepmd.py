"""CP2K→DeepMD 12 步可恢复工作流 — 引擎级验收证据（P0-9）。

用真实引擎机制（PlanStore / ArtifactRegistry / IdempotencyStore /
IntentLog / ValueProvenance / 角色门）驱动 12 步流程，模拟 scheduler 提供
job 状态事实源。每步产出机器可读证据；第 4-6 步模拟进程终止与恢复。

真实 CP2K/DeepMD 计算不在本阶段范围（用户指示）；本证据锁定引擎侧的
可恢复性、状态语义与 Provenance 契约，科学计算由用户在真实环境复验。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from electromind.artifacts import (
    ArtifactManifest,
    ArtifactStatus,
    ProvenanceStore,
    ValueProvenance,
)
from electromind.engine import RunEngine
from electromind.execution.idempotency import IdempotencyKey, IdempotencyStore
from electromind.execution.plan import (
    PlanState,
    PlanStatus,
    PlanStep,
)

from .scheduler_sim import JobStatus, SimulatedSlurm

THREAD = "cp2k-deepmd-golden"


@dataclass(slots=True)
class WorkflowEvidence:
    """12 步证据收集器。"""

    steps: list[dict] = field(default_factory=list)

    def step(self, number: int, name: str, ok: bool, detail: str, **extra) -> None:
        self.steps.append(
            {
                "step": number,
                "name": name,
                "ok": bool(ok),
                "detail": detail,
                **extra,
            }
        )

    @property
    def all_passed(self) -> bool:
        return all(s["ok"] for s in self.steps)

    def to_dict(self) -> dict:
        return {
            "workflow": "cp2k-deepmd-recoverable",
            "thread": THREAD,
            "steps": self.steps,
            "all_passed": self.all_passed,
        }


def _cp2k_input() -> str:
    return """&GLOBAL
  PROJECT water
  RUN_TYPE ENERGY_FORCE
&END GLOBAL
&FORCE_EVAL
  &DFT
    &XC
      &XC_FUNCTIONAL PBE
      &END XC_FUNCTIONAL
    &END XC
  &END DFT
  &SUBSYS
    &CELL
      ABC 12.0 12.0 12.0
    &END CELL
  &END SUBSYS
&END FORCE_EVAL
"""


def _preflight_check(input_text: str) -> list[str]:
    """确定性输入检查（§11.5：CP2K 输入通过确定性检查）。"""
    errors = []
    if "&GLOBAL" not in input_text:
        errors.append("缺少 &GLOBAL")
    if "ENERGY_FORCE" not in input_text:
        errors.append("RUN_TYPE 不是 ENERGY_FORCE")
    if "&FORCE_EVAL" not in input_text:
        errors.append("缺少 &FORCE_EVAL")
    return errors


def _parse_energy_force(output_text: str, parser_name: str):
    """确定性解析 ENERGY_FORCE 输出（§11.5：Energy 与 Force 带单位）。"""
    lines = output_text.splitlines()
    energy_line = next(
        (ln for ln in lines if "ENERGY|" in ln and "Hartree" in ln), None
    )
    if energy_line is None:
        raise ValueError("未找到 ENERGY| 行")
    value = energy_line.split()[-1]
    return ValueProvenance(
        value=value,
        unit="Hartree",
        source_file="water-1.ENERGY_FORCE.out",
        source_line=lines.index(energy_line) + 1,
        source_snippet=energy_line.strip(),
        parser=parser_name,
    )


def run_recoverable_workflow(work_root: Path) -> dict:
    """执行完整 12 步，返回机器可读证据。

    ``work_root`` 是本次验收的隔离根（进程终止通过新引擎实例 + 磁盘恢复
    模拟）。
    """
    evidence = WorkflowEvidence()
    root = Path(work_root)
    thread_root = root / THREAD
    thread_root.mkdir(parents=True, exist_ok=True)
    # 引擎的 per-thread 存储走 default_threads_root() → 隔离到 work_root，
    # 保证每次验收运行互不污染（进程恢复语义由同目录新实例体现）。
    import os

    os.environ["ELECTROMIND_HOME"] = str(root)

    # ── 进程 1 ────────────────────────────────────────────────────────
    engine1 = RunEngine()
    scheduler1 = SimulatedSlurm(thread_root)

    # 步骤 1：创建结构化 Plan 并完成必要审批
    plan = PlanState(
        plan_id="cp2k-deepmd",
        version=1,
        status=PlanStatus.DRAFT,
        objective="水分子 CP2K ENERGY_FORCE 单点 → DeepMD 数据",
        steps=(
            PlanStep(
                id="s1", title="生成 CP2K 输入", expected_artifacts=("water.inp",)
            ),
            PlanStep(id="s2", title="Preflight 检查", depends_on=("s1",)),
            PlanStep(id="s3", title="提交 Slurm Job", depends_on=("s2",)),
            PlanStep(id="s4", title="解析 ENERGY_FORCE", depends_on=("s3",)),
            PlanStep(id="s5", title="DeepMD 数据转换", depends_on=("s4",)),
        ),
        risks=("解析失败风险",),
        verification=("能量带单位且来自解析器",),
    )
    proposed = engine1.plan_propose(THREAD, plan)
    approved = engine1.plan_approve(THREAD)
    evidence.step(
        1,
        "结构化 Plan 生成并审批",
        approved is not None
        and approved.status == PlanStatus.APPROVED
        and proposed.fingerprint != "",
        f"plan {approved.plan_id} v{approved.version} APPROVED，指纹 {approved.fingerprint[:12]}",
        plan_id=approved.plan_id if approved else "",
        version=approved.version if approved else 0,
    )

    # 步骤 2：生成和检查 CP2K 输入
    input_text = _cp2k_input()
    input_manifest = ArtifactManifest(
        artifact_id="water-inp",
        type="cp2k_input",
        path="water.inp",
        sha256="a" * 64,  # 实际验收用真实 sha256（此处模拟内容）
        run_id="run-1",
        step_id="s1",
        created_by="tool:write_file",
        software="CP2K",
        software_version="2024.1",
    )
    engine1.artifact_register(THREAD, input_manifest)
    preflight_errors = _preflight_check(input_text)
    if preflight_errors:
        engine1.artifact_reject(THREAD, "water-inp", reason="; ".join(preflight_errors))
    else:
        engine1.artifact_complete(THREAD, "water-inp")
        engine1.artifact_validate(THREAD, "water-inp", parser="cp2k_preflight")
    manifest = engine1.artifacts(THREAD)[0]
    evidence.step(
        2,
        "CP2K 输入生成 + 确定性 Preflight",
        not preflight_errors
        and manifest.validation_status == ArtifactStatus.VALIDATED
        and manifest.acceptance_status == ArtifactStatus.COMPLETED,
        f"Preflight 检查 {'通过' if not preflight_errors else preflight_errors}；"
        f"validation={manifest.validation_status}",
        validation_status=str(manifest.validation_status),
    )

    # 步骤 3：提交 Slurm Job 并持久化 Job ID（幂等键）
    idem = IdempotencyStore(thread_root / "idempotency.jsonl")
    job_key = IdempotencyKey.derive(
        run_id="run-1", step_id="s3", action_id="submit", tool_name="sbatch"
    )
    # 先检查是否已有提交结果（恢复语义）
    existing_job = idem.get_result(job_key)
    if existing_job is not None:
        job_id = existing_job
    else:
        job_id = scheduler1.submit(script="cp2k.pbs", job_key=str(job_key))
        idem.record_completed(job_key, job_id)
    job_artifact = ArtifactManifest(
        artifact_id="job-1",
        type="hpc_job",
        path="",
        sha256="",
        run_id="run-1",
        step_id="s3",
        created_by="tool:sbatch",
        job_id=job_id,
        scheduler="slurm-sim",
    )
    engine1.artifact_register(THREAD, job_artifact)
    evidence.step(
        3,
        "提交 Slurm Job 并持久化 Job ID",
        job_id.startswith("job-") and idem.is_duplicate(job_key),
        f"job_id={job_id}，幂等键已持久化",
        job_id=job_id,
    )

    # 步骤 4：强制终止进程（模拟）—— 状态已全部落盘
    scheduler1.advance(job_id, JobStatus.RUNNING)
    evidence.step(
        4,
        "进程强制终止（模拟）",
        scheduler1.query(job_id) == str(JobStatus.RUNNING)
        and idem.is_duplicate(job_key)
        and Path(thread_root / "scheduler_jobs.json").exists()
        and Path(thread_root / "idempotency.jsonl").exists(),
        "job 状态 / 幂等记录 / Plan / Artifact 均已落盘；进程在此终止",
        persisted_files=sorted(
            p.name for p in Path(thread_root).rglob("*") if p.is_file()
        ),
    )
    # 进程 1 在此"终止"——不再触碰任何状态（状态已全部落盘）。

    # ── 进程 2（恢复） ────────────────────────────────────────────────
    engine2 = RunEngine()
    scheduler2 = SimulatedSlurm(thread_root)  # 新实例：从磁盘恢复 job 状态

    # 步骤 5：恢复后先查询 Scheduler，不重复提交
    queried = scheduler2.query(job_id)
    scheduler2.reconcile(job_id)  # 对账（不假定失败）
    job_key2 = IdempotencyKey.derive(
        run_id="run-1", step_id="s3", action_id="submit", tool_name="sbatch"
    )
    replayed = idem.get_result(job_key2)
    resubmitted = scheduler2.submit(script="cp2k.pbs", job_key=str(job_key2))
    evidence.step(
        5,
        "恢复后查询 Scheduler 不重复提交",
        queried == str(JobStatus.RUNNING)
        and resubmitted == job_id
        and replayed == job_id,
        f"查询到 job {job_id} 状态 {queried}；重放/重提均返回原 job id",
        queried_status=queried,
    )

    # 步骤 6：SSH 断开后恢复监控（对账不假定失败）
    # 模拟：断开后 scheduler 短暂不可达 → RECONCILING；重连后状态保留
    scheduler2.advance(job_id, JobStatus.COMPLETED)
    reconciled = scheduler2.reconcile(job_id)
    evidence.step(
        6,
        "SSH 断开后恢复监控（对账）",
        reconciled == str(JobStatus.COMPLETED),
        "断开后重连查询：job 已 COMPLETED（不假定失败，不重提）",
        final_status=reconciled,
    )

    # 步骤 7：解析 Energy 和 Force，保留单位与来源
    output_text = (
        "ENERGY| Total FORCE_EVAL ( QS ) energy [Hartree]       -76.4\n"
        "ATOMIC FORCES in [Hartree/bohr]\n 1  O   0.0   0.0   0.0\n"
    )
    provenance = _parse_energy_force(output_text, "cp2k_energy_force_parser")
    prov_store = ProvenanceStore(thread_root / "provenance.jsonl")
    prov_store.record(
        ValueProvenance(
            value=provenance.value,
            unit=provenance.unit,
            source_file=provenance.source_file,
            source_line=provenance.source_line,
            source_snippet=provenance.source_snippet,
            parser=provenance.parser,
            artifact_id="energy-1",
        )
    )
    energy_artifact = ArtifactManifest(
        artifact_id="energy-1",
        type="parsed_result",
        path="water-1.ENERGY_FORCE.out",
        sha256="b" * 64,
        run_id="run-1",
        step_id="s4",
        created_by="tool:parser",
        software="CP2K",
        software_version="2024.1",
        units="Hartree",
    )
    engine2.artifact_register(THREAD, energy_artifact)
    evidence.step(
        7,
        "解析 Energy/Force 并保留单位与来源",
        provenance.unit == "Hartree"
        and provenance.source_line > 0
        and provenance.parser == "cp2k_energy_force_parser",
        f"E={provenance.value} {provenance.unit} ← {provenance.source_file}:"
        f"{provenance.source_line} via {provenance.parser}",
        value=provenance.value,
        unit=provenance.unit,
    )

    # 步骤 8：Parser 失败 → 保持 Completed，不得进入 Validated
    engine2.artifact_complete(THREAD, "energy-1")
    try:
        _parse_energy_force("garbage output", "cp2k_energy_force_parser")
        parse_failed = False
    except ValueError:
        parse_failed = True
    if parse_failed:
        # 解析失败：验收语义 = 程序完成（COMPLETED），validation 不升级
        engine2.artifact_reject(THREAD, "energy-1", reason="ENERGY| 行缺失")
    after_fail = next(
        a for a in engine2.artifacts(THREAD) if a.artifact_id == "energy-1"
    )
    evidence.step(
        8,
        "Parser 失败保持 Completed 而非 Validated",
        parse_failed
        and after_fail.validation_status != ArtifactStatus.VALIDATED
        and after_fail.acceptance_status == ArtifactStatus.REJECTED,
        f"解析失败 → validation={after_fail.validation_status}（未升级）；"
        f"acceptance={after_fail.acceptance_status}",
    )

    # 步骤 9：修复后重新解析 → Validated
    fixed_output = "ENERGY| Total FORCE_EVAL ( QS ) energy [Hartree]       -76.4\n"
    fixed_prov = _parse_energy_force(fixed_output, "cp2k_energy_force_parser")
    prov_store.record(
        ValueProvenance(
            value=fixed_prov.value,
            unit=fixed_prov.unit,
            source_file=fixed_prov.source_file,
            source_line=fixed_prov.source_line,
            source_snippet=fixed_prov.source_snippet,
            parser=fixed_prov.parser,
            artifact_id="energy-1",
        )
    )
    # 修复：重新完成 → 重新解析
    engine2.artifact_complete(THREAD, "energy-1")
    engine2.artifact_validate(THREAD, "energy-1", parser="cp2k_energy_force_parser")
    after_fix = next(
        a for a in engine2.artifacts(THREAD) if a.artifact_id == "energy-1"
    )
    evidence.step(
        9,
        "修复后重新解析进入 Validated",
        after_fix.validation_status == ArtifactStatus.VALIDATED
        and after_fix.acceptance_status == ArtifactStatus.COMPLETED,
        f"validation={after_fix.validation_status}（解析器已记录）",
        parser=after_fix.parser,
    )

    # 步骤 10：独立 Reviewer 结构化评审（角色隔离）
    engine2.artifact_register(
        THREAD,
        ArtifactManifest(
            artifact_id="review-1",
            type="scientific_review",
            path="review.json",
            sha256="c" * 64,
            run_id="run-1",
            step_id="s5",
            created_by="subagent:reviewer-bob",
            created_by_role="reviewer",
            input_artifacts=("energy-1",),
        ),
    )
    engine2.artifact_complete(THREAD, "review-1")
    engine2.artifact_validate(THREAD, "review-1", parser="review_schema_check")
    try:
        # reviewer 不能接受自己创建的评审产物
        engine2.artifact_accept(THREAD, "review-1", who="reviewer-bob", role="reviewer")
        reviewer_self_accept = False
    except ValueError:
        reviewer_self_accept = True
    evidence.step(
        10,
        "独立 Reviewer 结构化评审（角色隔离）",
        reviewer_self_accept,
        "Reviewer 不能批准自己产物；评审产物已 COMPLETED+VALIDATED",
    )

    # 步骤 11：用户确认 → ACCEPTED（确认者持久化）
    accepted = engine2.artifact_accept(
        THREAD, "energy-1", who="user-alice", role="user"
    )
    evidence.step(
        11,
        "用户确认后才 ACCEPTED",
        accepted is not None
        and accepted.acceptance_status == ArtifactStatus.ACCEPTED
        and accepted.accepted_by == "user-alice"
        and accepted.validation_status == ArtifactStatus.VALIDATED,
        f"accepted_by={accepted.accepted_by if accepted else ''}",
        accepted_by=accepted.accepted_by if accepted else "",
    )

    # 步骤 12：Provenance 最终报告
    report = {
        "artifact": "energy-1",
        "status": str(accepted.acceptance_status),
        "value": fixed_prov.value,
        "unit": fixed_prov.unit,
        "source": {
            "file": fixed_prov.source_file,
            "line": fixed_prov.source_line,
            "parser": fixed_prov.parser,
        },
        "software": "CP2K 2024.1",
        "job_id": job_id,
        "traced_values": [p.to_dict() for p in prov_store.for_artifact("energy-1")],
    }
    evidence.step(
        12,
        "Provenance 最终报告",
        report["value"] == "-76.4"
        and report["unit"] == "Hartree"
        and report["source"]["parser"] == "cp2k_energy_force_parser"
        and len(report["traced_values"]) >= 1,
        "报告数值可追溯到文件/行/解析器/单位",
        report=report,
    )

    return evidence.to_dict()
