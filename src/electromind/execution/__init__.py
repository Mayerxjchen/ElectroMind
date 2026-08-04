"""执行模式解析器：local / sandbox / ssh 的唯一能力决策入口。"""

from .context import (
    ExecutionContextDocument,
    build_ssh_context_prompt,
    fetch_execution_context,
)
from .models import ExecutionDiagnostic, ResolvedExecution
from .resolver import (
    ContainerRuntimeUnavailableError,
    ExecutionResolutionError,
    InvalidExecutionModeError,
    InvalidSandboxBackendError,
    resolve_execution,
)

__all__ = [
    "ContainerRuntimeUnavailableError",
    "ExecutionContextDocument",
    "ExecutionDiagnostic",
    "ExecutionResolutionError",
    "InvalidExecutionModeError",
    "InvalidSandboxBackendError",
    "ResolvedExecution",
    "build_ssh_context_prompt",
    "fetch_execution_context",
    "resolve_execution",
]
