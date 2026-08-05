"""G1b: Plan / Artifact 模型工具桥 —— 模型接入 RunEngine 领域状态。

三个工具（effect 全部声明 WRITE_WORKSPACE，满足 M4 注册门）：

- ``plan_propose``：模型结构化提议计划（目标/步骤/依赖/验证）→ 引擎
  冻结为 READY 并落盘，等待用户批准。
- ``plan_step_update``：模型推进步骤状态。COMPLETED 仍受 M2 Evidence 门
  约束——LLM 文本声明不是证据，缺证据会被拒绝并引导先登记产物。
- ``artifact_register``：模型登记产物（经 sandbox.files 跨后端读文件 +
  SHA-256）→ 引擎注册；若关联步骤的 ``expected_artifacts`` 匹配该路径，
  自动附加文件证据（确定性来源：文件摘要 + 记录者 agent），步骤随后可
  COMPLETED。created_by="agent" 保证用户 accept 不触发自证守卫。

上下文：工具声明 ``context`` 形参 → Runner（``thread.id``）；
引擎经 ``engine.accessor`` 进程级访问器获取（App 层启动时注册）。
"""

from __future__ import annotations

import asyncio
import hashlib

from ..artifacts.manifest import ArtifactManifest
from ..core.tool import FunctionTool, ToolOutput
from ..engine.accessor import get_engine
from ..execution.effects import ToolEffect
from ..execution.plan import Evidence, PlanState, PlanStatus, PlanStep, StepStatus

PLAN_TOOL_NAMES = ("plan_propose", "plan_step_update", "artifact_register")


# ── 公共小工具 ─────────────────────────────────────────────────────────


def _thread_id(context) -> str:
    return str(getattr(getattr(context, "thread", None), "id", "") or "")


def _engine():
    return get_engine()


async def _read_file_sha256(context, path: str) -> tuple[str | None, str | None]:
    """跨后端读文件并计算 SHA-256；失败返回 (None, 错误消息)。"""
    files = getattr(getattr(context, "sandbox", None), "files", None)
    if files is None:
        return None, "沙箱不可用，无法读取产物文件"
    try:
        # 同步/异步双兼容（桩测试常用同步实现）
        result = files.read(path)
        if asyncio.iscoroutine(result):
            content = await result
        else:
            content = result
    except Exception as exc:  # noqa: BLE001 — 工具级错误转述
        return None, f"读取产物失败: {type(exc).__name__}: {exc}"
    if content is None:
        return None, f"读取产物为空: {path}"
    return hashlib.sha256(content).hexdigest(), None


# ── plan_propose ───────────────────────────────────────────────────────

PLAN_PROPOSE_PARAMETERS = {
    "type": "object",
    "properties": {
        "goal": {"type": "string", "description": "计划目标（Objective）"},
        "steps": {
            "type": "array",
            "description": "执行步骤（有序，id 自动编号 s1/s2/...）",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "步骤标题"},
                    "description": {"type": "string", "description": "步骤内容"},
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "本步骤涉及的文件",
                    },
                    "tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "本步骤需要的工具",
                    },
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "依赖的步骤 id（如 s1）",
                    },
                    "expected_artifacts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "预期产物路径（登记时自动形成完成证据）",
                    },
                    "verification": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "本步骤验证条件",
                    },
                },
                "required": ["title"],
            },
        },
        "assumptions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "前提假设",
        },
        "risks": {
            "type": "array",
            "items": {"type": "string"},
            "description": "风险评估",
        },
        "verification": {
            "type": "array",
            "items": {"type": "string"},
            "description": "整体完成标准",
        },
    },
    "required": ["goal", "steps"],
}


async def plan_propose_tool(
    goal: str,
    steps: list,
    assumptions: list | None = None,
    risks: list | None = None,
    verification: list | None = None,
    context=None,
) -> ToolOutput:
    """提议结构化计划（冻结 READY，等待用户批准）。"""
    engine = _engine()
    if engine is None:
        return ToolOutput.fail("引擎未就绪：plan_propose 不可用")
    thread_id = _thread_id(context)
    if not thread_id:
        return ToolOutput.fail("无法确定线程（缺少 runner 上下文）")
    if not goal.strip():
        return ToolOutput.fail("goal 不能为空")
    if not steps:
        return ToolOutput.fail("steps 不能为空：至少一个执行步骤")

    try:
        plan_steps = tuple(
            PlanStep(
                id=f"s{i + 1}",
                title=str(step.get("title", "")).strip() or f"步骤 {i + 1}",
                description=str(step.get("description", "")),
                files=tuple(step.get("files", [])),
                tools=tuple(step.get("tools", [])),
                depends_on=tuple(step.get("depends_on", [])),
                expected_artifacts=tuple(step.get("expected_artifacts", [])),
                verification=tuple(step.get("verification", [])),
            )
            for i, step in enumerate(steps)
        )
        current = engine.plan_state(thread_id)
        version = current.version + 1 if current is not None else 1
        plan = PlanState(
            plan_id="default",
            version=version,
            status=PlanStatus.DRAFT,
            objective=goal,
            assumptions=tuple(assumptions or ()),
            risks=tuple(risks or ()),
            verification=tuple(verification or ()),
            steps=plan_steps,
        )
        proposed = engine.plan_propose(thread_id, plan)
        step_summary = "；".join(f"{s.id} {s.title}" for s in proposed.steps)
        return ToolOutput.succeed(
            f"计划已提议（{proposed.plan_id}@{proposed.version}，状态 ready）："
            f"{proposed.objective}\n步骤：{step_summary}\n等待用户批准后执行。"
        )
    except ValueError as exc:
        return ToolOutput.fail(f"计划提议失败: {exc}")


# ── plan_step_update ───────────────────────────────────────────────────

PLAN_STEP_UPDATE_PARAMETERS = {
    "type": "object",
    "properties": {
        "step_id": {"type": "string", "description": "步骤 id（s1/s2/...）"},
        "status": {
            "type": "string",
            "enum": ["running", "completed", "failed", "skipped"],
            "description": "目标状态；completed 需要已有确定性证据（先 artifact_register）",
        },
        "error": {"type": "string", "description": "failed 时必填：失败原因"},
        "skipped_reason": {
            "type": "string",
            "description": "skipped 时必填：原因与授权来源",
        },
    },
    "required": ["step_id", "status"],
}

_STEP_STATUS_ENUM = {
    "running": StepStatus.RUNNING,
    "completed": StepStatus.COMPLETED,
    "failed": StepStatus.FAILED,
    "skipped": StepStatus.SKIPPED,
}


async def plan_step_update_tool(
    step_id: str,
    status: str,
    error: str = "",
    skipped_reason: str = "",
    context=None,
) -> ToolOutput:
    """推进计划步骤状态（M2 证据门：completed 无证据会被拒绝）。"""
    engine = _engine()
    if engine is None:
        return ToolOutput.fail("引擎未就绪：plan_step_update 不可用")
    thread_id = _thread_id(context)
    if not thread_id:
        return ToolOutput.fail("无法确定线程（缺少 runner 上下文）")
    target = _STEP_STATUS_ENUM.get(status)
    if target is None:
        return ToolOutput.fail(
            f"状态 {status!r} 非法（可选 running/completed/failed/skipped）"
        )
    if target == StepStatus.FAILED and not error:
        return ToolOutput.fail("failed 必须提供 error（失败原因）")
    if target == StepStatus.SKIPPED and not skipped_reason:
        return ToolOutput.fail("skipped 必须提供 skipped_reason（原因与授权来源）")

    plan = engine.plan_state(thread_id)
    if plan is None:
        return ToolOutput.fail("当前没有计划：先 plan_propose")
    step = next((s for s in plan.steps if s.id == step_id), None)
    if step is None:
        return ToolOutput.fail(
            f"步骤 {step_id} 不存在（现有: {', '.join(s.id for s in plan.steps)}）"
        )
    try:
        target_step = step.copy_with(
            status=target, error=error, skipped_reason=skipped_reason
        )
        engine.plan_update_step(thread_id, step_id, target, step=target_step)
        return ToolOutput.succeed(f"步骤 {step_id} → {target.value}")
    except ValueError as exc:
        hint = ""
        if "无 Evidence" in str(exc):
            hint = " 先用 artifact_register 登记该步骤的预期产物（自动附加文件证据）"
        return ToolOutput.fail(f"步骤状态更新失败: {exc}{hint}")


# ── artifact_register ──────────────────────────────────────────────────

ARTIFACT_REGISTER_PARAMETERS = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "产物路径（相对沙箱工作区）"},
        "type": {
            "type": "string",
            "enum": ["data", "log", "parsed_result", "model", "report"],
            "description": "产物类型",
        },
        "units": {"type": "string", "description": "数值单位（eV/Hartree/Å 等）"},
        "software": {"type": "string", "description": "产生该产物的软件"},
        "software_version": {"type": "string"},
        "command": {"type": "string", "description": "产生该产物的命令"},
        "step_id": {
            "type": "string",
            "description": "关联的计划步骤（匹配 expected_artifacts 时自动附加证据）",
        },
    },
    "required": ["path"],
}


async def artifact_register_tool(
    path: str,
    type: str = "data",
    units: str = "",
    software: str = "",
    software_version: str = "",
    command: str = "",
    step_id: str = "",
    context=None,
) -> ToolOutput:
    """登记产物（SHA-256 + Provenance）；匹配步骤预期产物时自动附加证据。"""
    engine = _engine()
    if engine is None:
        return ToolOutput.fail("引擎未就绪：artifact_register 不可用")
    thread_id = _thread_id(context)
    if not thread_id:
        return ToolOutput.fail("无法确定线程（缺少 runner 上下文）")
    if not path.strip():
        return ToolOutput.fail("path 不能为空")

    sha256, error = await _read_file_sha256(context, path)
    if error is not None:
        return ToolOutput.fail(error)

    manifest = ArtifactManifest(
        artifact_id=path.rsplit("/", 1)[-1] or path,
        type=type or "data",
        path=path,
        sha256=sha256,
        created_by="agent",
        units=units,
        software=software,
        software_version=software_version,
        command=command,
    )
    engine.artifact_register(thread_id, manifest)

    evidence_added = ""
    if step_id:
        plan = engine.plan_state(thread_id)
        if plan is not None:
            step = next((s for s in plan.steps if s.id == step_id), None)
            if step is not None:
                basename = path.rsplit("/", 1)[-1]
                if (
                    path in step.expected_artifacts
                    or basename in step.expected_artifacts
                ):
                    with_evidence = step.with_evidence(
                        Evidence.file(path, sha256, by="agent")
                    )
                    engine.plan_update_step(
                        thread_id, step_id, with_evidence.status, step=with_evidence
                    )
                    evidence_added = f"；步骤 {step_id} 已附加文件证据（{sha256[:8]}），可标记 completed"
    return ToolOutput.succeed(
        f"已登记产物 {manifest.artifact_id}（{manifest.type}，sha256 {sha256[:8]}）"
        f"{evidence_added}"
    )


# ── 装配 ───────────────────────────────────────────────────────────────


def make_plan_tools() -> list[FunctionTool]:
    """G1b 工具集（effect 全部 WRITE_WORKSPACE，满足正式 Runner 注册门）。"""
    return [
        FunctionTool(
            "plan_propose",
            "提议一个结构化执行计划（目标/步骤/依赖/验证），等待用户批准。"
            "计划批准前不要开始执行步骤。",
            PLAN_PROPOSE_PARAMETERS,
            plan_propose_tool,
            effect=ToolEffect.WRITE_WORKSPACE,
        ),
        FunctionTool(
            "plan_step_update",
            "推进计划步骤状态：running/completed/failed/skipped。"
            "completed 需要该步骤已有确定性证据（登记产物或验证器结果），"
            "不能仅凭文本声明完成。",
            PLAN_STEP_UPDATE_PARAMETERS,
            plan_step_update_tool,
            effect=ToolEffect.WRITE_WORKSPACE,
        ),
        FunctionTool(
            "artifact_register",
            "登记科学产物（文件 + SHA-256 + Provenance 元数据）。"
            "登记匹配步骤预期产物时自动形成该步骤的完成证据。",
            ARTIFACT_REGISTER_PARAMETERS,
            artifact_register_tool,
            effect=ToolEffect.WRITE_WORKSPACE,
        ),
    ]
