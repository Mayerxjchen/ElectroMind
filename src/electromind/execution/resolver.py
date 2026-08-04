"""执行模式解析：local / sandbox / ssh 的唯一决策入口。

sandbox 不可用时抛出 ContainerRuntimeUnavailableError，绝不回退 local。
"""

from __future__ import annotations

from typing import Literal

from .models import ExecutionDiagnostic, ResolvedExecution
from .probe import ContainerRuntimeProbe

_LOCAL_WARNING = (
    "Execution: Local\n"
    "Isolation: None\n"
    "Commands run with your current user permissions."
)


class ExecutionResolutionError(Exception):
    """解析失败基类。"""

    def __init__(self, message: str, diagnostics: tuple[ExecutionDiagnostic, ...] = ()):
        super().__init__(message)
        self.diagnostics = diagnostics


class InvalidExecutionModeError(ExecutionResolutionError):
    """无效的执行模式。"""


class ContainerRuntimeUnavailableError(ExecutionResolutionError):
    """sandbox 模式需要 Docker/Podman 但均不可用。"""


def resolve_execution(
    mode: str | None = None,
    *,
    sandbox_backend: str | None = None,
    ssh_config: dict | None = None,
    runtime_probe: ContainerRuntimeProbe | None = None,
    legacy_backend: str | None = None,
    legacy_command_policy: str | None = None,
) -> ResolvedExecution:
    """返回 ResolvedExecution——整个系统唯一的能力决策入口。"""

    diagnostics: list[ExecutionDiagnostic] = []
    effective = mode or "sandbox"

    # 校验模式
    if effective not in ("local", "sandbox", "ssh"):
        raise InvalidExecutionModeError(
            f"Invalid execution mode: {effective!r}. Valid modes: local, sandbox, ssh.",
            diagnostics=(
                ExecutionDiagnostic(
                    code="invalid_execution_mode",
                    severity="error",
                    message=f"Invalid execution mode: {effective!r}. Must be local, sandbox, or ssh.",
                ),
            ),
        )

    # 旧配置迁移提示（仅当未显式设置 mode 时）
    if not mode and (legacy_backend or legacy_command_policy):
        diagnostics.append(_legacy_warning(legacy_backend, legacy_command_policy))

    if effective == "local":
        return ResolvedExecution(
            mode="local",
            resolved_backend="local",
            isolated=False,
            warning=_LOCAL_WARNING,
            diagnostics=tuple(diagnostics),
        )

    if effective == "ssh":
        _validate_ssh(ssh_config, diagnostics)
        return ResolvedExecution(
            mode="ssh",
            resolved_backend="ssh",
            isolated=False,
            warning=None,
            diagnostics=tuple(diagnostics),
        )

    # sandbox: 解析容器后端
    probe = runtime_probe or ContainerRuntimeProbe()
    backend = _resolve_container(sandbox_backend, probe, diagnostics)

    if backend is None:
        raise ContainerRuntimeUnavailableError(
            "Sandbox mode requires Docker or Podman, but neither is usable. "
            "Install Docker/Podman, or use 'local' or 'ssh' mode.",
            diagnostics=tuple(diagnostics),
        )

    return ResolvedExecution(
        mode="sandbox",
        resolved_backend=backend,
        isolated=True,
        warning=None,
        diagnostics=tuple(diagnostics),
    )


class InvalidSandboxBackendError(ExecutionResolutionError):
    """非法的 sandbox backend 值。"""


def _resolve_container(
    requested: str | None,
    probe: ContainerRuntimeProbe,
    diags: list[ExecutionDiagnostic],
) -> Literal["docker", "podman"] | None:
    if requested in (None, "container"):
        return _check_one("docker", probe, diags) or _check_one("podman", probe, diags)
    if requested == "docker":
        return _check_one("docker", probe, diags)
    if requested == "podman":
        return _check_one("podman", probe, diags)
    raise InvalidSandboxBackendError(
        f"Invalid sandbox backend: {requested!r}. "
        "Valid values: docker, podman, container (or omit for auto-detection).",
    )


def _check_one(
    runtime: Literal["docker", "podman"],
    probe: ContainerRuntimeProbe,
    diags: list[ExecutionDiagnostic],
) -> Literal["docker", "podman"] | None:
    r = probe.probe(runtime)
    if r.usable:
        return runtime
    diags.append(
        ExecutionDiagnostic(
            code=f"{runtime}_{r.error_code}"
            if r.error_code
            else f"{runtime}_unavailable",
            severity="error",
            message=r.message,
        )
    )
    return None


def _validate_ssh(config: dict | None, diags: list[ExecutionDiagnostic]) -> None:
    if not config or not config.get("host"):
        raise ExecutionResolutionError(
            "SSH mode requires [ssh] host to be configured.",
            diagnostics=(
                ExecutionDiagnostic(
                    code="ssh_no_host",
                    severity="error",
                    message="SSH mode requires ssh.host to be configured.",
                ),
            ),
        )


def _legacy_warning(backend: str | None, policy: str | None) -> ExecutionDiagnostic:
    parts = []
    if backend:
        parts.append(f'backend = "{backend}"')
    if policy:
        parts.append(f'command_policy = "{policy}"')
    detail = f" ({' and '.join(parts)})" if parts else ""
    return ExecutionDiagnostic(
        code="legacy_execution_config",
        severity="warning",
        message=(
            f"Legacy execution settings were ignored{detail}.\n\n"
            "ElectroMind now defaults to sandbox execution.\n"
            "To run commands directly on the host, explicitly configure:\n\n"
            '[execution]\nmode = "local"'
        ),
    )
