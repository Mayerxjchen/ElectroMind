"""Plan protocol — structured plan generation, approval, execution, and recovery.

A Plan is a structured object (not just Markdown) that the agent
produces in Plan mode.  It contains:
- Objective, assumptions, open questions
- Ordered steps with dependencies
- Risk assessment
- Verification criteria

The lifecycle:
  draft → ready → approved → executing → completed
                                  ↓
                               revising → ready (user requested changes)

Key invariants (M2 contract):
- Once approved, the plan version is FROZEN.  Modifying an approved plan
  requires a new revision (version bump); ``PlanTracker.propose`` rejects
  any plan whose version is ≤ the last approved version of the same
  plan_id.
- Step transitions are gated deterministically: a step cannot enter
  ``COMPLETED`` without Evidence, and cannot enter ``VERIFIED`` without a
  verifier record (``EvidenceType.VERIFIER``).  LLM text claims are never
  evidence.
- State fields (status/evidence/error) do NOT change the content
  fingerprint; content fields (objective/steps/deps/risks/verification/
  expected_artifacts/effects) do.
- Plans persist to disk (``PlanStore``) with version history; approved
  versions are never overwritten.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, fields
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from ..atomicfile import atomic_write_text, load_json_recover

if TYPE_CHECKING:
    pass


class PlanStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    REVISING = "revising"
    CANCELLED = "cancelled"


class StepStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    VERIFIED = "verified"
    FAILED = "failed"
    SKIPPED = "skipped"
    # 兼容别名：旧代码的 ``DONE`` 归一为 ``COMPLETED``
    DONE = "completed"


# ── Evidence ────────────────────────────────────────────────────────────


class EvidenceType(StrEnum):
    FILE = "file"  # 生成文件 + sha256
    TOOL_RESULT = "tool_result"  # 工具结果
    COMMAND = "command"  # 命令 + 退出码
    JOB = "job"  # 外部任务 id
    PARSER = "parser"  # 解析器结果
    APPROVAL = "approval"  # 人工审批
    VERIFIER = "verifier"  # 确定性验证器报告


@dataclass(frozen=True, slots=True)
class Evidence:
    """步骤完成的确定性证据。禁止仅由模型文本声明完成。"""

    kind: EvidenceType
    detail: str  # 路径 / 摘要 / job id / parser 名 / 验证器名
    sha256: str = ""
    exit_code: int | None = None
    by: str = ""  # 记录者：tool_call_id / user / verifier 名
    recorded_at: float = field(default_factory=time.time)

    @classmethod
    def file(cls, path: str, sha256: str, *, by: str = "") -> "Evidence":
        return cls(EvidenceType.FILE, path, sha256=sha256, by=by)

    @classmethod
    def tool_result(
        cls, tool_call_id: str, summary: str, *, by: str = ""
    ) -> "Evidence":
        return cls(EvidenceType.TOOL_RESULT, summary, by=by or tool_call_id)

    @classmethod
    def command(cls, command: str, exit_code: int, *, by: str = "") -> "Evidence":
        return cls(EvidenceType.COMMAND, command, exit_code=exit_code, by=by)

    @classmethod
    def job(cls, job_id: str, *, by: str = "") -> "Evidence":
        return cls(EvidenceType.JOB, job_id, by=by)

    @classmethod
    def parser(cls, parser_name: str, result: str, *, by: str = "") -> "Evidence":
        return cls(EvidenceType.PARSER, result, by=by or parser_name)

    @classmethod
    def approval(cls, approval_id: str, *, by: str = "user") -> "Evidence":
        return cls(EvidenceType.APPROVAL, approval_id, by=by)

    @classmethod
    def verifier(cls, verifier_name: str, result: str, *, by: str = "") -> "Evidence":
        return cls(EvidenceType.VERIFIER, result, by=by or verifier_name)

    def to_dict(self) -> dict:
        return {
            "kind": str(self.kind),
            "detail": self.detail,
            "sha256": self.sha256,
            "exit_code": self.exit_code,
            "by": self.by,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Evidence":
        return cls(
            kind=EvidenceType(d["kind"]),
            detail=d.get("detail", ""),
            sha256=d.get("sha256", ""),
            exit_code=d.get("exit_code"),
            by=d.get("by", ""),
            recorded_at=d.get("recorded_at", time.time()),
        )


@dataclass(frozen=True, slots=True)
class PlanStep:
    id: str
    title: str
    description: str = ""
    files: tuple[str, ...] = ()  # expected files this step touches
    tools: tuple[str, ...] = ()  # tools this step needs
    depends_on: tuple[str, ...] = ()  # step ids that must complete first
    status: StepStatus = StepStatus.PENDING
    # M2 扩展
    expected_artifacts: tuple[str, ...] = ()  # 预期产物路径
    effects: tuple[str, ...] = ()  # 副作用类别（external/写路径）
    verification: tuple[str, ...] = ()  # 本步骤的验证条件
    evidence: tuple[Evidence, ...] = ()  # 完成证据（确定性）
    error: str = ""  # FAILED 原因
    retry_policy: str = ""  # "retry" | "fail" | "reconcile"
    skipped_reason: str = ""  # SKIPPED 原因与授权来源

    def copy_with(self, **kwargs) -> PlanStep:
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        d.update(kwargs)
        return PlanStep(**d)

    def with_evidence(self, evidence: Evidence) -> PlanStep:
        return self.copy_with(evidence=self.evidence + (evidence,))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "files": list(self.files),
            "tools": list(self.tools),
            "depends_on": list(self.depends_on),
            "status": str(self.status),
            "expected_artifacts": list(self.expected_artifacts),
            "effects": list(self.effects),
            "verification": list(self.verification),
            "evidence": [e.to_dict() for e in self.evidence],
            "error": self.error,
            "retry_policy": self.retry_policy,
            "skipped_reason": self.skipped_reason,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PlanStep":
        return cls(
            id=d["id"],
            title=d.get("title", ""),
            description=d.get("description", ""),
            files=tuple(d.get("files", [])),
            tools=tuple(d.get("tools", [])),
            depends_on=tuple(d.get("depends_on", [])),
            status=StepStatus(d.get("status", "pending")),
            expected_artifacts=tuple(d.get("expected_artifacts", [])),
            effects=tuple(d.get("effects", [])),
            verification=tuple(d.get("verification", [])),
            evidence=tuple(Evidence.from_dict(e) for e in d.get("evidence", [])),
            error=d.get("error", ""),
            retry_policy=d.get("retry_policy", ""),
            skipped_reason=d.get("skipped_reason", ""),
        )


@dataclass(frozen=True, slots=True)
class PlanState:
    plan_id: str
    version: int
    status: PlanStatus
    objective: str
    assumptions: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()  # open questions for the user
    steps: tuple[PlanStep, ...] = ()
    risks: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()  # how to verify completion
    created_at: float = field(default_factory=time.time)
    approved_at: float | None = None
    # Content-addressed fingerprint — changes whenever plan content changes
    fingerprint: str = ""

    def compute_fingerprint(self) -> str:
        """Return SHA-256 of all plan content fields (状态字段不参与)。"""
        h = hashlib.sha256()
        h.update(self.objective.encode())
        for a in sorted(self.assumptions):
            h.update(("a:" + a).encode())
        for q in sorted(self.questions):
            h.update(("q:" + q).encode())
        for s in self.steps:
            h.update(
                (
                    "s:"
                    + "|".join(
                        [
                            s.id,
                            s.title,
                            s.description,
                            ",".join(sorted(s.files)),
                            ",".join(sorted(s.tools)),
                            ",".join(sorted(s.depends_on)),
                            ",".join(sorted(s.expected_artifacts)),
                            ",".join(sorted(s.effects)),
                            ",".join(sorted(s.verification)),
                        ]
                    )
                ).encode()
            )
        for r in sorted(self.risks):
            h.update(("r:" + r).encode())
        for v in sorted(self.verification):
            h.update(("v:" + v).encode())
        return h.hexdigest()

    def freeze(self) -> PlanState:
        """Return a copy with computed fingerprint, ready for approval."""
        return PlanState(
            plan_id=self.plan_id,
            version=self.version,
            status=PlanStatus.READY,
            objective=self.objective,
            assumptions=self.assumptions,
            questions=self.questions,
            steps=self.steps,
            risks=self.risks,
            verification=self.verification,
            created_at=self.created_at,
            fingerprint=self.compute_fingerprint(),
        )

    def approve(self) -> PlanState:
        return PlanState(
            plan_id=self.plan_id,
            version=self.version,
            status=PlanStatus.APPROVED,
            objective=self.objective,
            assumptions=self.assumptions,
            questions=self.questions,
            steps=self.steps,
            risks=self.risks,
            verification=self.verification,
            created_at=self.created_at,
            approved_at=time.time(),
            fingerprint=self.fingerprint,
        )

    def with_step_status(self, step_id: str, status: StepStatus) -> PlanState:
        new_steps = tuple(
            s.copy_with(status=status) if s.id == step_id else s for s in self.steps
        )
        return PlanState(
            plan_id=self.plan_id,
            version=self.version,
            status=self.status,
            objective=self.objective,
            assumptions=self.assumptions,
            questions=self.questions,
            steps=new_steps,
            risks=self.risks,
            verification=self.verification,
            created_at=self.created_at,
            approved_at=self.approved_at,
            fingerprint=self.fingerprint,
        )

    def with_step(self, step: PlanStep) -> PlanState:
        """以完整新步骤替换（带证据/错误记录）。"""
        new_steps = tuple(step if s.id == step.id else s for s in self.steps)
        return PlanState(
            plan_id=self.plan_id,
            version=self.version,
            status=self.status,
            objective=self.objective,
            assumptions=self.assumptions,
            questions=self.questions,
            steps=new_steps,
            risks=self.risks,
            verification=self.verification,
            created_at=self.created_at,
            approved_at=self.approved_at,
            fingerprint=self.fingerprint,
        )

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "version": self.version,
            "status": str(self.status),
            "objective": self.objective,
            "assumptions": list(self.assumptions),
            "questions": list(self.questions),
            "steps": [s.to_dict() for s in self.steps],
            "risks": list(self.risks),
            "verification": list(self.verification),
            "created_at": self.created_at,
            "approved_at": self.approved_at,
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PlanState":
        return cls(
            plan_id=d["plan_id"],
            version=int(d["version"]),
            status=PlanStatus(d.get("status", "draft")),
            objective=d.get("objective", ""),
            assumptions=tuple(d.get("assumptions", [])),
            questions=tuple(d.get("questions", [])),
            steps=tuple(PlanStep.from_dict(s) for s in d.get("steps", [])),
            risks=tuple(d.get("risks", [])),
            verification=tuple(d.get("verification", [])),
            created_at=d.get("created_at", time.time()),
            approved_at=d.get("approved_at"),
            fingerprint=d.get("fingerprint", ""),
        )


# ── StepVerifier — 确定性步骤转换门 ────────────────────────────────────


class StepTransitionError(ValueError):
    """非法步骤转换（缺证据 / 缺验证器结果 / 依赖未完成）。"""


class StepVerifier:
    """确定性步骤验证。

    - ``COMPLETED`` 必须携带 Evidence（禁止模型文本声明完成）。
    - ``VERIFIED`` 必须携带 ``EvidenceType.VERIFIER`` 记录。
    - ``SKIPPED`` 必须记录原因与授权来源。
    - ``FAILED`` 必须记录失败原因。
    """

    def transition_error(self, step: PlanStep, target: StepStatus) -> str | None:
        """返回拒绝原因；None 表示允许。"""
        if target == StepStatus.COMPLETED:
            if not step.evidence:
                return f"步骤 {step.id} 无 Evidence，不能标记完成"
            return None
        if target == StepStatus.VERIFIED:
            if not any(e.kind == EvidenceType.VERIFIER for e in step.evidence):
                return f"步骤 {step.id} 无验证器结果，不能标记已验证"
            return None
        if target == StepStatus.SKIPPED:
            if not step.skipped_reason:
                return f"步骤 {step.id} 跳过必须记录原因与授权来源"
            return None
        if target == StepStatus.FAILED:
            if not step.error:
                return f"步骤 {step.id} 失败必须记录原因"
            return None
        return None

    def assert_transition(self, step: PlanStep, target: StepStatus) -> None:
        """强制转换门；非法时抛 ``StepTransitionError``。"""
        reason = self.transition_error(step, target)
        if reason is not None:
            raise StepTransitionError(reason)


# ── PlanTracker (per-thread) ────────────────────────────────────────────


class PlanTracker:
    """Tracks the current plan for a thread.

    Only one plan can be active at a time.  Approving a plan freezes it;
    changes require a new revision (version bump).  An approved version of
    a plan_id can never be replaced by a same-or-lower version.
    """

    def __init__(self, verifier: StepVerifier | None = None) -> None:
        self._current: PlanState | None = None
        self._history: list[PlanState] = []
        self.verifier = verifier or StepVerifier()

    @property
    def current(self) -> PlanState | None:
        return self._current

    def restore(self, plan: PlanState) -> None:
        """从磁盘恢复当前计划（G1：引擎接线；不触发版本检查）。

        Approved 版本同时记入历史，保证后续 propose 的版本门仍然生效。
        """
        self._current = plan
        if plan.status == PlanStatus.APPROVED:
            self._history.append(plan)

    def _latest_approved_version(self, plan_id: str) -> int | None:
        versions = [
            p.version
            for p in self._history
            if p.plan_id == plan_id and p.status == PlanStatus.APPROVED
        ]
        return max(versions) if versions else None

    def propose(self, plan: PlanState) -> PlanState:
        """Set a new draft plan.  Rejects overriding an approved version."""
        approved_version = self._latest_approved_version(plan.plan_id)
        if approved_version is not None and plan.version <= approved_version:
            raise ValueError(
                f"plan {plan.plan_id!r} 已批准到版本 {approved_version}；"
                f"不能以版本 {plan.version} 覆盖，必须创建新版本"
            )
        frozen = plan.freeze()
        self._current = frozen
        return frozen

    def approve(self) -> PlanState | None:
        if self._current is None:
            return None
        if self._current.status != PlanStatus.READY:
            return None
        approved = self._current.approve()
        self._history.append(approved)
        self._current = approved
        return approved

    def revise(self) -> PlanState | None:
        """Start a new revision of the current plan."""
        if self._current is None:
            return None
        revised = PlanState(
            plan_id=self._current.plan_id,
            version=self._current.version + 1,
            status=PlanStatus.REVISING,
            objective=self._current.objective,
            assumptions=self._current.assumptions,
            questions=self._current.questions,
            steps=self._current.steps,
            risks=self._current.risks,
            verification=self._current.verification,
            created_at=self._current.created_at,
            approved_at=self._current.approved_at,
            fingerprint=self._current.fingerprint,
        )
        self._current = revised
        return revised

    def update_step(
        self, step_id: str, status: StepStatus, *, step: PlanStep | None = None
    ) -> PlanState | None:
        """以状态或完整新步骤更新。COMPLETED/VERIFIED/SKIPPED/FAILED
        受 ``StepVerifier`` 门约束。"""
        if self._current is None:
            return None
        target = step
        if target is None:
            current_step = next(
                (s for s in self._current.steps if s.id == step_id), None
            )
            if current_step is None:
                return None
            target = current_step.copy_with(status=status)
        else:
            # 显式传入步骤时，以请求的状态为准（步骤自带的 status 被覆盖）
            target = target.copy_with(status=status)
        # 状态门：缺证据 / 缺验证器结果 / 无原因跳过 一律拒绝
        self.verifier.assert_transition(target, target.status)
        # R2-7: 步骤完成/验证要求计划已批准（未 APPROVED 的 READY 计划
        # 不能仅凭 Evidence 直接进入 COMPLETED/VERIFIED）。
        if target.status in (StepStatus.COMPLETED, StepStatus.VERIFIED):
            if self._current.status not in (
                PlanStatus.APPROVED,
                PlanStatus.EXECUTING,
            ):
                raise StepTransitionError(
                    f"步骤 {step_id} 不能进入 {target.status}："
                    f"计划尚未批准（status={self._current.status}）"
                )
        self._current = self._current.with_step(target)
        return self._current

    def complete(self) -> PlanState | None:
        if self._current is None:
            return None
        self._current = PlanState(
            plan_id=self._current.plan_id,
            version=self._current.version,
            status=PlanStatus.COMPLETED,
            objective=self._current.objective,
            assumptions=self._current.assumptions,
            questions=self._current.questions,
            steps=self._current.steps,
            risks=self._current.risks,
            verification=self._current.verification,
            created_at=self._current.created_at,
            approved_at=self._current.approved_at,
            fingerprint=self._current.fingerprint,
        )
        self._history.append(self._current)
        return self._current

    def cancel(self) -> PlanState | None:
        if self._current is None:
            return None
        self._current = PlanState(
            plan_id=self._current.plan_id,
            version=self._current.version,
            status=PlanStatus.CANCELLED,
            objective=self._current.objective,
            assumptions=self._current.assumptions,
            questions=self._current.questions,
            steps=self._current.steps,
            risks=self._current.risks,
            verification=self._current.verification,
            created_at=self._current.created_at,
            approved_at=self._current.approved_at,
            fingerprint=self._current.fingerprint,
        )
        return self._current

    @property
    def history(self) -> tuple[PlanState, ...]:
        return tuple(self._history)


# ── PlanStore — 磁盘持久化 ─────────────────────────────────────────────


# 计划状态的推进序（同版本覆盖仅允许前向）
_STATUS_RANK = {
    PlanStatus.DRAFT: 0,
    PlanStatus.READY: 1,
    PlanStatus.APPROVED: 2,
    PlanStatus.EXECUTING: 3,
    PlanStatus.COMPLETED: 4,
    PlanStatus.REVISING: 1,
    PlanStatus.CANCELLED: 5,
}


def _is_forward_status(old: PlanStatus, new: PlanStatus) -> bool:
    """同版本状态覆盖是否允许（前向推进）。"""
    return _STATUS_RANK.get(new, 0) >= _STATUS_RANK.get(old, 0)


class PlanStore:
    """按 ``plan_id@version`` 持久化 Plan 到 ``<root>/plans/``。

    原子写（临时文件 + replace）；已写版本不可覆盖（Approved Plan 不可
    原地修改）；旧版本全部保留，可完整重建历史。
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root) / "plans"
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _path_for(root: Path, plan_id: str, version: int) -> Path:
        safe_id = plan_id.replace("/", "_").replace("\\", "_")
        return root / f"{safe_id}@{version}.json"

    def save(self, plan: PlanState) -> Path:
        """原子写；同 plan_id+version 已存在且指纹不同 → 拒绝（防篡改）。"""
        if not plan.fingerprint:
            plan = plan.freeze()
        path = self._path_for(self.root, plan.plan_id, plan.version)
        if path.exists():
            existing = self.load(plan.plan_id, plan.version)
            if existing is not None and existing.fingerprint != plan.fingerprint:
                raise ValueError(
                    f"plan {plan.plan_id}@{plan.version} 已存在且内容不同，"
                    "禁止覆盖（必须创建新版本）"
                )
            # P0-1: 同指纹不同状态仅允许前向推进（READY→APPROVED→EXECUTING→
            # COMPLETED）；已批准版本不可被降级（DRAFT/READY 篡改）覆盖。
            if existing is not None and not _is_forward_status(
                existing.status, plan.status
            ):
                raise ValueError(
                    f"plan {plan.plan_id}@{plan.version} 已存在且状态为 "
                    f"{existing.status}，禁止以 {plan.status} 覆盖（仅允许前向推进）"
                )
        atomic_write_text(
            path,
            json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
            backup=True,
        )
        return path

    def load(self, plan_id: str, version: int) -> PlanState | None:
        path = self._path_for(self.root, plan_id, version)
        if not path.exists():
            return None
        # P1.3: 主文件损坏 → 尝试 .bak 恢复。
        d = load_json_recover(path)
        if not isinstance(d, dict):
            return None
        return PlanState.from_dict(d)

    def load_all(self, plan_id: str) -> list[PlanState]:
        """按版本升序返回该 plan_id 的全部历史版本。"""
        plans: list[PlanState] = []
        for path in sorted(self.root.glob(f"{plan_id.replace('/', '_')}@*.json")):
            d = load_json_recover(path)
            if not isinstance(d, dict):
                continue  # 单个版本损坏不阻塞整组恢复
            plans.append(PlanState.from_dict(d))
        return sorted(plans, key=lambda p: p.version)

    def latest(self, plan_id: str) -> PlanState | None:
        versions = self.load_all(plan_id)
        return versions[-1] if versions else None

    def has(self, plan_id: str, version: int) -> bool:
        return self._path_for(self.root, plan_id, version).exists()

    def delete(self, plan_id: str, version: int) -> bool:
        """删除版本。P0-1: 已批准（APPROVED/EXECUTING/COMPLETED）版本不可删除。"""
        plan = self.load(plan_id, version)
        if plan is None:
            return False
        if plan.status in (
            PlanStatus.APPROVED,
            PlanStatus.EXECUTING,
            PlanStatus.COMPLETED,
        ):
            raise ValueError(f"plan {plan_id}@{version} 已批准/执行/完成，禁止删除")
        self._path_for(self.root, plan_id, version).unlink()
        return True

    def list_ids(self) -> list[str]:
        ids: set[str] = set()
        for path in self.root.glob("*@*.json"):
            ids.add(path.name.split("@")[0])
        return sorted(ids)
