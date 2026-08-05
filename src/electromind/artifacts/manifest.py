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


# 合法状态转换
_ARTIFACT_TRANSITIONS: dict[ArtifactStatus, frozenset[ArtifactStatus]] = {
    ArtifactStatus.CREATED: frozenset(
        {ArtifactStatus.COMPLETED, ArtifactStatus.REJECTED, ArtifactStatus.SUPERSEDED}
    ),
    ArtifactStatus.COMPLETED: frozenset(
        {ArtifactStatus.VALIDATED, ArtifactStatus.REJECTED, ArtifactStatus.SUPERSEDED}
    ),
    ArtifactStatus.VALIDATED: frozenset(
        {ArtifactStatus.ACCEPTED, ArtifactStatus.REJECTED, ArtifactStatus.SUPERSEDED}
    ),
    ArtifactStatus.ACCEPTED: frozenset({ArtifactStatus.SUPERSEDED}),
    ArtifactStatus.REJECTED: frozenset(
        {ArtifactStatus.COMPLETED, ArtifactStatus.VALIDATED, ArtifactStatus.SUPERSEDED}
    ),  # 修复后重新解析可恢复
    ArtifactStatus.SUPERSEDED: frozenset(),
}


def allowed_artifact_transitions(status: ArtifactStatus) -> frozenset[ArtifactStatus]:
    return _ARTIFACT_TRANSITIONS.get(status, frozenset())


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
    input_artifacts: tuple[str, ...] = ()  # 输入 artifact_id 依赖图
    command: str = ""  # 产生该产物的命令
    software: str = ""  # 软件名
    software_version: str = ""
    environment_digest: str = ""
    units: str = ""  # 数值单位（Hartree / eV / Å ...）
    validation_status: ArtifactStatus = ArtifactStatus.CREATED
    acceptance_status: ArtifactStatus = ArtifactStatus.CREATED
    parser: str = ""  # 解析器名（VALIDATED 时的依据）
    created_at: float = field(default_factory=time.time)
    # HPC 预留字段（本阶段不实现，schema 预留）
    scheduler: str = ""
    job_id: str = ""

    # ── 状态推进（确定性转换） ──────────────────────────────────────

    def _transition(self, target: ArtifactStatus, *, who: str) -> "ArtifactManifest":
        current = self.acceptance_status
        if target not in allowed_artifact_transitions(current):
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
            input_artifacts=self.input_artifacts,
            command=self.command,
            software=self.software,
            software_version=self.software_version,
            environment_digest=self.environment_digest,
            units=self.units,
            validation_status=target,
            acceptance_status=target,
            parser=self.parser,
            created_at=self.created_at,
            scheduler=self.scheduler,
            job_id=self.job_id,
        )

    def complete(self, *, who: str = "runner") -> "ArtifactManifest":
        """程序正常结束 → COMPLETED（绝不自动 VALIDATED）。"""
        return self._transition(ArtifactStatus.COMPLETED, who=who)

    def validate(self, *, parser: str, who: str = "") -> "ArtifactManifest":
        """确定性 Parser/Checker 通过 → VALIDATED（记录解析器名）。"""
        if not parser:
            raise ArtifactTransitionError("VALIDATED 必须记录解析器名")
        validated = self._transition(ArtifactStatus.VALIDATED, who=who)
        return ArtifactManifest(
            artifact_id=validated.artifact_id,
            type=validated.type,
            path=validated.path,
            sha256=validated.sha256,
            run_id=validated.run_id,
            step_id=validated.step_id,
            created_by=validated.created_by,
            input_artifacts=validated.input_artifacts,
            command=validated.command,
            software=validated.software,
            software_version=validated.software_version,
            environment_digest=validated.environment_digest,
            units=validated.units,
            validation_status=ArtifactStatus.VALIDATED,
            acceptance_status=ArtifactStatus.VALIDATED,
            parser=parser,
            created_at=validated.created_at,
            scheduler=validated.scheduler,
            job_id=validated.job_id,
        )

    def accept(self, *, who: str) -> "ArtifactManifest":
        """用户或独立 Reviewer 确认 → ACCEPTED（who 必须非空且非创建者工具）。"""
        if not who:
            raise ArtifactTransitionError("ACCEPTED 必须记录确认者")
        if who == self.created_by and self.created_by:
            raise ArtifactTransitionError(
                f"artifact {self.artifact_id} 不能由创建者 {who!r} 自行 ACCEPTED"
            )
        return self._transition(ArtifactStatus.ACCEPTED, who=who)

    def reject(self, *, reason: str) -> "ArtifactManifest":
        """检查失败 → REJECTED（必须记录原因）。"""
        if not reason:
            raise ArtifactTransitionError("REJECTED 必须记录原因")
        return self._transition(ArtifactStatus.REJECTED, who="checker")

    def supersede(self, *, by: str) -> "ArtifactManifest":
        """被新版本替代 → SUPERSEDED（记录替代者）。"""
        if not by:
            raise ArtifactTransitionError("SUPERSEDED 必须记录替代者")
        return self._transition(ArtifactStatus.SUPERSEDED, who=by)

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
            "input_artifacts": list(self.input_artifacts),
            "command": self.command,
            "software": self.software,
            "software_version": self.software_version,
            "environment_digest": self.environment_digest,
            "units": self.units,
            "validation_status": str(self.validation_status),
            "acceptance_status": str(self.acceptance_status),
            "parser": self.parser,
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
            input_artifacts=tuple(d.get("input_artifacts", [])),
            command=d.get("command", ""),
            software=d.get("software", ""),
            software_version=d.get("software_version", ""),
            environment_digest=d.get("environment_digest", ""),
            units=d.get("units", ""),
            validation_status=ArtifactStatus(d.get("validation_status", "created")),
            acceptance_status=ArtifactStatus(d.get("acceptance_status", "created")),
            parser=d.get("parser", ""),
            created_at=d.get("created_at", time.time()),
            scheduler=d.get("scheduler", ""),
            job_id=d.get("job_id", ""),
        )
