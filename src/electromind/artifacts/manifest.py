"""Artifact Manifest — 科学产物的 Provenance 契约（M6，非 HPC 部分）。

状态语义（严格分离，Agent 不能自行 ACCEPTED 自己的产物）：

    CREATED → COMPLETED → VALIDATED → ACCEPTED
                    ↘ REJECTED / SUPERSEDED

- 程序正常结束只能进入 COMPLETED。
- 确定性 Parser/Checker 通过后才能 VALIDATED。
- 用户或独立 Reviewer 确认后才能 ACCEPTED。
- 报告中的每个数值必须能追溯到 Artifact、解析器和单位。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ArtifactStatus(StrEnum):
    CREATED = "created"  # 文件已生成
    COMPLETED = "completed"  # 程序正常结束（≠ 科学有效）
    VALIDATED = "validated"  # 确定性检查通过
    ACCEPTED = "accepted"  # 用户/独立 Reviewer 确认
    REJECTED = "rejected"  # 检查失败
    SUPERSEDED = "superseded"  # 被新版本替代


# 合法状态转换（P0-7 双状态分离）：
# - validation_status：CREATED → VALIDATED（确定性检查）→ REJECTED（解析失败）→
#   修复后重新 VALIDATED；VALIDATED 的前提是 acceptance 已达 COMPLETED。
# - acceptance_status：CREATED → COMPLETED → ACCEPTED / REJECTED → COMPLETED（修复恢复）/ SUPERSEDED
# 两个字段互不覆盖：程序结束只动 acceptance；解析器只动 validation。
# 门控键是 acceptance_status（validate 必须以程序完成为前提）。
_VALIDATION_TRANSITIONS: dict[ArtifactStatus, frozenset[ArtifactStatus]] = {
    ArtifactStatus.CREATED: frozenset({ArtifactStatus.REJECTED}),
    ArtifactStatus.COMPLETED: frozenset(
        {ArtifactStatus.VALIDATED, ArtifactStatus.REJECTED}
    ),
    ArtifactStatus.REJECTED: frozenset({ArtifactStatus.VALIDATED}),  # 修复后重新解析
    ArtifactStatus.VALIDATED: frozenset(
        {ArtifactStatus.REJECTED, ArtifactStatus.SUPERSEDED}
    ),
    ArtifactStatus.ACCEPTED: frozenset({ArtifactStatus.SUPERSEDED}),
    ArtifactStatus.SUPERSEDED: frozenset(),
}

_ACCEPTANCE_TRANSITIONS: dict[ArtifactStatus, frozenset[ArtifactStatus]] = {
    ArtifactStatus.CREATED: frozenset(
        {ArtifactStatus.COMPLETED, ArtifactStatus.REJECTED, ArtifactStatus.SUPERSEDED}
    ),
    ArtifactStatus.COMPLETED: frozenset(
        {ArtifactStatus.ACCEPTED, ArtifactStatus.REJECTED, ArtifactStatus.SUPERSEDED}
    ),
    ArtifactStatus.ACCEPTED: frozenset({ArtifactStatus.SUPERSEDED}),
    ArtifactStatus.REJECTED: frozenset(
        {ArtifactStatus.COMPLETED, ArtifactStatus.SUPERSEDED}
    ),  # 修复后重新完成
    ArtifactStatus.VALIDATED: frozenset(
        {ArtifactStatus.ACCEPTED, ArtifactStatus.REJECTED, ArtifactStatus.SUPERSEDED}
    ),
    ArtifactStatus.SUPERSEDED: frozenset(),
}


def allowed_artifact_transitions(status: ArtifactStatus) -> frozenset[ArtifactStatus]:
    """acceptance 语义的转换表（向后兼容查询）。"""
    return _ACCEPTANCE_TRANSITIONS.get(status, frozenset())


class ArtifactTransitionError(ValueError):
    """非法 Artifact 状态转换（如直接 CREATED→ACCEPTED）。"""


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    """正式 Artifact 的 Provenance 记录。HPC 字段（scheduler/job）预留。"""

    artifact_id: str
    type: str  # 类型：data / log / parsed_result / model / report ...
    path: str  # 相对工作目录或绝对路径
    sha256: str  # 文件内容摘要
    run_id: str = ""
    step_id: str = ""
    created_by: str = ""  # tool_call_id / parser 名 / user
    created_by_role: str = "agent"  # P0-6: 创建者角色（agent/reviewer/...）
    input_artifacts: tuple[str, ...] = ()  # 输入 artifact_id 依赖图
    command: str = ""  # 产生该产物的命令
    software: str = ""  # 软件名
    software_version: str = ""
    environment_digest: str = ""
    units: str = ""  # 数值单位（Hartree / eV / Å ...）
    validation_status: ArtifactStatus = ArtifactStatus.CREATED
    acceptance_status: ArtifactStatus = ArtifactStatus.CREATED
    parser: str = ""  # 解析器名（VALIDATED 时的依据）
    accepted_by: str = ""  # P0-7: ACCEPTED 的确认者（身份持久化）
    created_at: float = field(default_factory=time.time)
    # HPC 预留字段（本阶段不实现，schema 预留）
    scheduler: str = ""
    job_id: str = ""

    # ── 状态推进（确定性转换） ──────────────────────────────────────

    def _transition(
        self,
        target: ArtifactStatus,
        *,
        who: str,
        acceptance: bool = True,
    ) -> "ArtifactManifest":
        """P0-7: 双状态分离转换——acceptance 或 validation 各自独立推进。"""
        table = _ACCEPTANCE_TRANSITIONS if acceptance else _VALIDATION_TRANSITIONS
        # validation 转换以 acceptance_status 为门控键（VALIDATED 必须以
        # COMPLETED 为前提）；acceptance 转换以自身为键。
        current = self.acceptance_status
        if target not in table.get(current, frozenset()):
            raise ArtifactTransitionError(
                f"artifact {self.artifact_id} 非法转换 {current} → {target}"
            )
        return ArtifactManifest(
            artifact_id=self.artifact_id,
            type=self.type,
            path=self.path,
            sha256=self.sha256,
            run_id=self.run_id,
            step_id=self.step_id,
            created_by=self.created_by,
            created_by_role=self.created_by_role,
            input_artifacts=self.input_artifacts,
            command=self.command,
            software=self.software,
            software_version=self.software_version,
            environment_digest=self.environment_digest,
            units=self.units,
            validation_status=(target if not acceptance else self.validation_status),
            acceptance_status=(target if acceptance else self.acceptance_status),
            parser=self.parser,
            accepted_by=(
                who
                if acceptance and target == ArtifactStatus.ACCEPTED
                else self.accepted_by
            ),
            created_at=self.created_at,
            scheduler=self.scheduler,
            job_id=self.job_id,
        )

    def complete(self, *, who: str = "runner") -> "ArtifactManifest":
        """程序正常结束 → acceptance=COMPLETED（绝不自动 VALIDATED）。"""
        return self._transition(ArtifactStatus.COMPLETED, who=who, acceptance=True)

    def validate(self, *, parser: str, who: str = "") -> "ArtifactManifest":
        """确定性 Parser/Checker 通过 → validation=VALIDATED（记录解析器名）。"""
        if not parser:
            raise ArtifactTransitionError("VALIDATED 必须记录解析器名")
        validated = self._transition(
            ArtifactStatus.VALIDATED, who=who, acceptance=False
        )
        return ArtifactManifest(
            artifact_id=validated.artifact_id,
            type=validated.type,
            path=validated.path,
            sha256=validated.sha256,
            run_id=validated.run_id,
            step_id=validated.step_id,
            created_by=validated.created_by,
            created_by_role=validated.created_by_role,
            input_artifacts=validated.input_artifacts,
            command=validated.command,
            software=validated.software,
            software_version=validated.software_version,
            environment_digest=validated.environment_digest,
            units=validated.units,
            validation_status=ArtifactStatus.VALIDATED,
            acceptance_status=validated.acceptance_status,
            parser=parser,
            accepted_by=validated.accepted_by,
            created_at=validated.created_at,
            scheduler=validated.scheduler,
            job_id=validated.job_id,
        )

    def accept(self, *, who: str, role: str = "user") -> "ArtifactManifest":
        """用户或独立 Reviewer 确认 → ACCEPTED。

        P0-6 角色隔离：
        - ``who`` 必须非空。
        - 只有 ``user`` / ``reviewer`` 角色可以接受。
        - 创建者（同一角色）不能自行 ACCEPTED（Reviewer 不能批准自己产物）。
        """
        if not who:
            raise ArtifactTransitionError("ACCEPTED 必须记录确认者")
        if role not in ("user", "reviewer"):
            raise ArtifactTransitionError(
                f"ACCEPTED 只接受 user/reviewer 角色确认，收到 {role!r}"
            )
        # 双保险：字符串身份（防御）+ 角色隔离（可信边界）
        if who == self.created_by and self.created_by:
            raise ArtifactTransitionError(
                f"artifact {self.artifact_id} 不能由创建者 {who!r} 自行 ACCEPTED"
            )
        if role == self.created_by_role:
            raise ArtifactTransitionError(
                f"artifact {self.artifact_id} 不能由创建者角色 "
                f"{self.created_by_role!r} 自行 ACCEPTED"
            )
        return self._transition(ArtifactStatus.ACCEPTED, who=who, acceptance=True)

    def reject(self, *, reason: str) -> "ArtifactManifest":
        """检查失败 → acceptance=REJECTED（必须记录原因）。"""
        if not reason:
            raise ArtifactTransitionError("REJECTED 必须记录原因")
        return self._transition(
            ArtifactStatus.REJECTED, who=f"checker:{reason[:80]}", acceptance=True
        )

    def supersede(self, *, by: str) -> "ArtifactManifest":
        """被新版本替代 → SUPERSEDED（记录替代者）。"""
        if not by:
            raise ArtifactTransitionError("SUPERSEDED 必须记录替代者")
        return self._transition(ArtifactStatus.SUPERSEDED, who=by, acceptance=True)

    # ── 序列化 ──────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "type": self.type,
            "path": self.path,
            "sha256": self.sha256,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "created_by": self.created_by,
            "created_by_role": self.created_by_role,
            "input_artifacts": list(self.input_artifacts),
            "command": self.command,
            "software": self.software,
            "software_version": self.software_version,
            "environment_digest": self.environment_digest,
            "units": self.units,
            "validation_status": str(self.validation_status),
            "acceptance_status": str(self.acceptance_status),
            "parser": self.parser,
            "accepted_by": self.accepted_by,
            "created_at": self.created_at,
            "scheduler": self.scheduler,
            "job_id": self.job_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ArtifactManifest":
        return cls(
            artifact_id=d["artifact_id"],
            type=d.get("type", ""),
            path=d.get("path", ""),
            sha256=d.get("sha256", ""),
            run_id=d.get("run_id", ""),
            step_id=d.get("step_id", ""),
            created_by=d.get("created_by", ""),
            created_by_role=d.get("created_by_role", "agent"),
            input_artifacts=tuple(d.get("input_artifacts", [])),
            command=d.get("command", ""),
            software=d.get("software", ""),
            software_version=d.get("software_version", ""),
            environment_digest=d.get("environment_digest", ""),
            units=d.get("units", ""),
            validation_status=ArtifactStatus(d.get("validation_status", "created")),
            acceptance_status=ArtifactStatus(d.get("acceptance_status", "created")),
            parser=d.get("parser", ""),
            accepted_by=d.get("accepted_by", ""),
            created_at=d.get("created_at", time.time()),
            scheduler=d.get("scheduler", ""),
            job_id=d.get("job_id", ""),
        )
