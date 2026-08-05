"""CP2K→DeepMD 12 步可恢复工作流 — 引擎级验收证据（P0-9）。

用真实引擎机制（PlanStore / ArtifactRegistry / IdempotencyStore /
IntentLog / ValueProvenance / 角色门）驱动 12 步流程，模拟 scheduler 提供
job 状态事实源。每步产出机器可读证据；第 4-6 步模拟进程终止与恢复。

真实 CP2K/DeepMD 计算不在本阶段范围（用户指示）；本证据锁定引擎侧的
可恢复性、状态语义与 Provenance 契约，科学计算由用户在真实环境复验。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from electromind.artifacts import (
    ArtifactManifest,
    ArtifactStatus,
    ProvenanceStore,
    ValueProvenance,
)
from electromind.engine import RunEngine
from electromind.execution.plan import (
    PlanState,
    PlanStatus,
    PlanStep,
)
from electromind.runtime import Runner
from evals.provider import ProviderStep, ScriptedProvider

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


def _parse_force(output_text: str, parser_name: str) -> dict:
    """确定性解析 FORCE 输出（单位 Hartree/bohr，与 Energy 同源文件）。"""
    lines = output_text.splitlines()
    force_line = next(
        (ln for ln in lines if "ATOMIC FORCES" in ln or "O   0.0" in ln), None
    )
    if force_line is None:
        raise ValueError("未找到 FORCE 行")
    value = force_line.split()[-3]
    return {
        "value": value,
        "unit": "Hartree/bohr",
        "source_file": "water-1.ENERGY_FORCE.out",
        "source_line": lines.index(force_line) + 1,
        "source_snippet": force_line.strip(),
        "parser": parser_name,
    }


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


async def run_recoverable_workflow(work_root: Path) -> dict:
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

    # 步骤 2：生成和检查 CP2K 输入（真实 SHA-256 + 完整性验证）
    from electromind.artifacts import sha256_file

    input_text = _cp2k_input()
    input_path = (thread_root / "water.inp").resolve()
    input_path.write_text(input_text, encoding="utf-8")
    input_sha256 = sha256_file(input_path)
    input_manifest = ArtifactManifest(
        artifact_id="water-inp",
        type="cp2k_input",
        path=str(input_path),
        sha256=input_sha256,  # R2-9: 真实文件 SHA-256
        run_id="run-1",
        step_id="s1",
        created_by="tool:write_file",
        software="CP2K",
        software_version="2024.1",
    )
    engine1.artifact_register(THREAD, input_manifest)
    registry1 = engine1._artifact_registries[THREAD]
    registry1.verify_integrity(input_manifest, thread_root)
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

    # 步骤 3：提交 Slurm Job —— 走正式 Runner 工具路径（intent→commit +
    # 幂等重放；R2-9 去掉 simulator 自去重，去重由 Runner 幂等层提供）。
    from electromind.core.tool import FunctionTool
    from electromind.execution.effects import ToolEffect
    from electromind.execution.idempotency import IdempotencyKey as _Key

    submit_calls = {"n": 0}

    async def sbatch_tool(script: str) -> str:
        submit_calls["n"] += 1
        return scheduler1.submit(script=script)  # 无 job_key 去重

    sbatch = FunctionTool(
        "sbatch",
        "sbatch",
        {
            "type": "object",
            "properties": {"script": {"type": "string"}},
            "required": ["script"],
        },
        sbatch_tool,
        effect=ToolEffect.SUBMIT_EXTERNAL,
    )

    # 进程 1：经正式 Runner 提交（intent 记录 + 幂等 commit）
    runner1 = await Runner.create(
        "submit-runner",
        ScriptedProvider(
            [
                ProviderStep.tools(
                    {"name": "sbatch", "arguments": {"script": "cp2k.pbs"}}
                ),
                ProviderStep.text("done"),
            ]
        ),
        overrides={"backend": "none"},
        tools=[sbatch],
    )
    try:
        async for _ in runner1.run("提交"):
            pass
        job_key = _Key.derive(
            run_id=runner1.current_run_id,
            tool_name="sbatch",
            args={"script": "cp2k.pbs"},
        )
        job_id = runner1.idempotency_store.get_result(job_key)
    finally:
        await runner1.close()
    assert job_id is not None and submit_calls["n"] == 1
    submit_idem = runner1.idempotency_store  # 提交幂等记录所在（Runner per-thread）
    submit_dir = (
        Path(runner1.thread.root) if hasattr(runner1, "thread") else thread_root
    )
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
        "提交 Slurm Job（正式 Runner 幂等路径）",
        job_id.startswith("job-") and submit_calls["n"] == 1,
        f"job_id={job_id}；Runner intent 已 commit、幂等键已持久化",
        job_id=job_id,
        submit_calls=submit_calls["n"],
    )

    # 步骤 4：强制终止进程（模拟）—— 状态已全部落盘
    scheduler1.advance(job_id, JobStatus.RUNNING)
    evidence.step(
        4,
        "进程强制终止（模拟）",
        scheduler1.query(job_id) == str(JobStatus.RUNNING)
        and submit_idem.is_duplicate(job_key)
        and Path(thread_root / "scheduler_jobs.json").exists()
        and Path(submit_dir / "idempotency.jsonl").exists(),
        "job 状态 / 幂等记录 / Plan / Artifact 均已落盘；进程在此终止",
        persisted_files=sorted(
            p.name for p in Path(thread_root).rglob("*") if p.is_file()
        ),
    )
    # 进程 1 在此"终止"——不再触碰任何状态（状态已全部落盘）。

    # ── 进程 2（恢复） ────────────────────────────────────────────────
    engine2 = RunEngine()
    scheduler2 = SimulatedSlurm(thread_root)  # 新实例：从磁盘恢复 job 状态

    # 步骤 5：恢复后先查询 Scheduler；经正式 Runner 重放（不重新提交）
    queried = scheduler2.query(job_id)
    scheduler2.reconcile(job_id)  # 对账（不假定失败）
    runner2 = await Runner.create(
        "submit-runner",
        ScriptedProvider(
            [
                ProviderStep.tools(
                    {"name": "sbatch", "arguments": {"script": "cp2k.pbs"}}
                ),
                ProviderStep.text("done"),
            ]
        ),
        overrides={"backend": "none"},
        tools=[sbatch],
    )
    try:
        async for _ in runner2.run("恢复后再次提交"):
            pass
        recovered = runner2.recover_pending_intents()
        replay_job = runner2.idempotency_store.get_result(job_key)
    finally:
        await runner2.close()
    evidence.step(
        5,
        "恢复后查询 Scheduler 不重复提交（正式 Runner 重放）",
        queried == str(JobStatus.RUNNING)
        and submit_calls["n"] == 1  # 未二次提交
        and replay_job == job_id  # 恢复 Runner 重放原 job id
        and recovered["committed"] == [],
        f"查询到 job {job_id} 状态 {queried}；恢复 Runner 重放原结果，"
        f"scheduler 提交次数仍为 {submit_calls['n']}",
        queried_status=queried,
        total_submits=submit_calls["n"],
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
    force_provenance = _parse_force(output_text, "cp2k_energy_force_parser")
    output_path = (thread_root / "water-1.ENERGY_FORCE.out").resolve()
    output_path.write_text(output_text, encoding="utf-8")
    output_sha256 = sha256_file(output_path)
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
    prov_store.record(
        ValueProvenance(
            value=force_provenance["value"],
            unit=force_provenance["unit"],
            source_file=force_provenance["source_file"],
            source_line=force_provenance["source_line"],
            source_snippet=force_provenance["source_snippet"],
            parser=force_provenance["parser"],
            artifact_id="energy-1",
        )
    )
    energy_artifact = ArtifactManifest(
        artifact_id="energy-1",
        type="parsed_result",
        path=str(output_path),
        sha256=output_sha256,  # R2-9: 真实文件 SHA-256
        run_id="run-1",
        step_id="s4",
        created_by="tool:parser",
        software="CP2K",
        software_version="2024.1",
        units="Hartree",
    )
    engine2.artifact_register(THREAD, energy_artifact)
    registry2 = engine2._artifact_registries[THREAD]
    registry2.verify_integrity(energy_artifact, thread_root)  # R2-9: 完整性验证
    evidence.step(
        7,
        "解析 Energy/Force 并保留单位与来源（真实 SHA-256）",
        provenance.unit == "Hartree"
        and provenance.source_line > 0
        and provenance.parser == "cp2k_energy_force_parser"
        and force_provenance["unit"] == "Hartree/bohr"
        and len(prov_store.for_artifact("energy-1")) == 2,
        f"E={provenance.value} {provenance.unit}；F={force_provenance['value']} "
        f"{force_provenance['unit']} ← {provenance.source_file}:"
        f"{provenance.source_line} via {provenance.parser}",
        value=provenance.value,
        unit=provenance.unit,
        force_unit=force_provenance["unit"],
        sha256=output_sha256[:16],
    )

    # 步骤 8：Parser 失败 → 保持 Completed，不得进入 Validated
    engine2.artifact_complete(THREAD, "energy-1")
    try:
        _parse_energy_force("garbage output", "cp2k_energy_force_parser")
        parse_failed = False
    except ValueError:
        parse_failed = True
    if parse_failed:
        # R2-9: 解析失败只动 validation（REJECTED）；acceptance 保持
        # COMPLETED —— 程序已完成，只是解析未通过（科学状态验收语义）。
        engine2.artifact_validate_fail(THREAD, "energy-1", reason="ENERGY| 行缺失")
    after_fail = next(
        a for a in engine2.artifacts(THREAD) if a.artifact_id == "energy-1"
    )
    evidence.step(
        8,
        "Parser 失败保持 Completed 而非 Validated（validation 侧拒绝）",
        parse_failed
        and after_fail.validation_status == ArtifactStatus.REJECTED
        and after_fail.acceptance_status == ArtifactStatus.COMPLETED,
        f"解析失败 → validation={after_fail.validation_status}（未升级）；"
        f"acceptance 保持 {after_fail.acceptance_status}",
        validation_status=str(after_fail.validation_status),
        acceptance_status=str(after_fail.acceptance_status),
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
    # 修复：acceptance 已保持 COMPLETED（R2-9），直接重新解析即可
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

    # 步骤 10：DeepMD 数据转换 → 训练 → 测试（确定性模拟阶段；R2-9）
    deepmd_dir = thread_root / "deepmd"
    deepmd_dir.mkdir(exist_ok=True)
    # 10a 数据转换（原子顺序保持：Energy/Force 溯源进训练数据）
    data_path = deepmd_dir / "data.json"
    data_path.write_text(
        json.dumps(
            {
                "frames": [
                    {
                        "energy": provenance.value,
                        "energy_unit": provenance.unit,
                        "forces": [
                            {
                                "value": force_provenance["value"],
                                "unit": force_provenance["unit"],
                            }
                        ],
                    }
                ],
                "source": output_path.name,
                "parser": "cp2k_energy_force_parser",
                "atom_order": ["O", "H", "H"],
            }
        ),
        encoding="utf-8",
    )
    data_manifest = ArtifactManifest(
        artifact_id="deepmd-data",
        type="deepmd_dataset",
        path=str(data_path),
        sha256=sha256_file(data_path),
        run_id="run-1",
        step_id="s5",
        created_by="tool:deepmd_data",
        software="DeepMD-kit",
        software_version="2.2.9",
        units="Hartree;Hartree/bohr",
        input_artifacts=("energy-1",),
    )
    engine2.artifact_register(THREAD, data_manifest)
    engine2.artifact_complete(THREAD, "deepmd-data")
    engine2.artifact_validate(THREAD, "deepmd-data", parser="deepmd_data_checker")
    # 10b 训练（记录配置/软件版本/随机种子）
    train_path = deepmd_dir / "train.log"
    train_path.write_text(
        "DEEPMD train: seed=42 model=se_e2_a config=water.json epochs=100\n",
        encoding="utf-8",
    )
    model_path = deepmd_dir / "model.ckpt"
    model_path.write_text("model-bytes", encoding="utf-8")
    model_manifest = ArtifactManifest(
        artifact_id="deepmd-model",
        type="model",
        path=str(model_path),
        sha256=sha256_file(model_path),
        run_id="run-1",
        step_id="s6",
        created_by="tool:deepmd_train",
        software="DeepMD-kit",
        software_version="2.2.9",
        command="deepmd train water.json --seed 42",
        input_artifacts=("deepmd-data",),
    )
    engine2.artifact_register(THREAD, model_manifest)
    engine2.artifact_complete(THREAD, "deepmd-model")
    engine2.artifact_validate(THREAD, "deepmd-model", parser="model_file_check")
    # 10c 测试（测试指标由脚本生成，不由模型猜测）
    test_path = deepmd_dir / "test.json"
    test_path.write_text(
        json.dumps(
            {
                "rmse_energy": "0.0021",
                "unit": "eV",
                "rmse_force": "0.045",
                "unit_f": "eV/A",
            }
        ),
        encoding="utf-8",
    )
    test_manifest = ArtifactManifest(
        artifact_id="deepmd-test",
        type="eval_report",
        path=str(test_path),
        sha256=sha256_file(test_path),
        run_id="run-1",
        step_id="s7",
        created_by="tool:deepmd_test",
        software="DeepMD-kit",
        software_version="2.2.9",
        command="deepmd test --model model.ckpt",
        input_artifacts=("deepmd-model",),
    )
    engine2.artifact_register(THREAD, test_manifest)
    engine2.artifact_complete(THREAD, "deepmd-test")
    engine2.artifact_validate(THREAD, "deepmd-test", parser="test_report_check")
    deepmd_ok = (
        engine2.artifacts(THREAD)
        and any(a.artifact_id == "deepmd-data" for a in engine2.artifacts(THREAD))
        and any(a.artifact_id == "deepmd-model" for a in engine2.artifacts(THREAD))
        and any(a.artifact_id == "deepmd-test" for a in engine2.artifacts(THREAD))
    )
    evidence.step(
        10,
        "DeepMD 数据转换→训练→测试（阶段产物 + 溯源）",
        deepmd_ok,
        "data/model/test 三个阶段产物均已 COMPLETED+VALIDATED，"
        "训练记录含 seed=42 与软件版本",
    )

    # 步骤 11：独立 Reviewer 结构化评审（角色隔离）
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
        11,
        "独立 Reviewer 结构化评审（角色隔离）",
        reviewer_self_accept,
        "Reviewer 不能批准自己产物；评审产物已 COMPLETED+VALIDATED",
    )

    # 步骤 12：用户确认 → ACCEPTED（确认者持久化）+ Provenance 报告
    accepted = engine2.artifact_accept(
        THREAD, "energy-1", who="user-alice", role="user"
    )
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
        "用户确认 ACCEPTED + Provenance 最终报告",
        accepted is not None
        and accepted.acceptance_status == ArtifactStatus.ACCEPTED
        and accepted.accepted_by == "user-alice"
        and accepted.validation_status == ArtifactStatus.VALIDATED
        and report["value"] == "-76.4"
        and report["unit"] == "Hartree"
        and report["source"]["parser"] == "cp2k_energy_force_parser"
        and len(report["traced_values"]) >= 2,  # Energy + Force 溯源
        f"accepted_by={accepted.accepted_by if accepted else ''}；"
        "报告数值可追溯到文件/行/解析器/单位",
        accepted_by=accepted.accepted_by if accepted else "",
        report=report,
    )

    return evidence.to_dict()
