"""执行模式数据模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ExecutionMode = Literal["local", "sandbox", "ssh"]
ResolvedBackend = Literal["local", "docker", "podman", "ssh"]


@dataclass(frozen=True)
class ExecutionDiagnostic:
    code: str
    severity: Literal["info", "warning", "error"]
    message: str


@dataclass(frozen=True)
class ResolvedExecution:
    mode: ExecutionMode
    resolved_backend: ResolvedBackend
    isolated: bool
    warning: str | None
    diagnostics: tuple[ExecutionDiagnostic, ...]

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "resolved_backend": self.resolved_backend,
            "isolated": self.isolated,
            "warning": self.warning,
            "diagnostics": [
                {"code": d.code, "severity": d.severity, "message": d.message}
                for d in self.diagnostics
            ],
        }
