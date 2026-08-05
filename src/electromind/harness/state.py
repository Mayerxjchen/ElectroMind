"""Harness state enums and snapshots — phases, delivery states, and targets."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# ---------------------------------------------------------------------------
# SessionMode — the user-visible operating mode for a Run
# ---------------------------------------------------------------------------


class SessionMode(StrEnum):
    """Operating mode for a Run.

    These are part of the frozen ``RunSnapshot`` and cannot be changed
    mid-Run.  The Permission Engine uses the mode to gate tool execution:
    ``ask`` is read-only, ``plan`` may propose file edits but not apply
    them, ``run`` has full write access.
    """

    ASK = "ask"
    PLAN = "plan"
    RUN = "run"


# ---------------------------------------------------------------------------
# RunPhase — lifecycle phases of a single Run
# ---------------------------------------------------------------------------


class RunPhase(StrEnum):
    """Lifecycle phases of a Run.

    Transitions are governed by ``allowed_run_transitions()`` and must be
    enforced by ``ThreadSessionManager`` / ``RunEngine`` — never by the
    Agent Loop or the App layer itself.

    ``RUNNING`` 是旧版伞形相位（保留兼容）；``RUNNING_MODEL /
    RUNNING_TOOL / WAITING_APPROVAL`` 是 RunEngine 声明的精细相位，
    全部走同一张集中转换表。
    """

    DORMANT = "dormant"  # Run created but not yet started
    QUEUED = "queued"  # 等待可写 Run 槽位
    PREPARING = "preparing"  # Acquiring resources (sandbox, SSH, workspace lease)
    INITIALIZING = "initializing"  # 循环初始化（用户消息入栈）
    RUNNING = "running"  # Agent loop active（旧版伞形相位，兼容）
    RUNNING_MODEL = "running_model"  # 模型调用中
    RUNNING_TOOL = "running_tool"  # 工具执行中
    WAITING_APPROVAL = "waiting_approval"  # 等待审批
    FINALIZING = "finalizing"  # Loop ended, flushing state
    COMPLETED = "completed"  # Normal completion
    CANCELLED = "cancelled"  # User cancelled
    FAILED = "failed"  # Fatal error
    INTERRUPTED = "interrupted"  # External interruption (restart, disconnect)


# Legal phase transition map
_PHASE_TRANSITIONS: dict[RunPhase, frozenset[RunPhase]] = {
    RunPhase.DORMANT: frozenset(
        {RunPhase.QUEUED, RunPhase.PREPARING, RunPhase.CANCELLED}
    ),
    RunPhase.QUEUED: frozenset(
        {RunPhase.INITIALIZING, RunPhase.CANCELLED, RunPhase.FAILED}
    ),
    RunPhase.PREPARING: frozenset(
        {RunPhase.RUNNING, RunPhase.INITIALIZING, RunPhase.FAILED, RunPhase.CANCELLED}
    ),
    RunPhase.INITIALIZING: frozenset(
        {
            RunPhase.RUNNING,
            RunPhase.RUNNING_MODEL,
            RunPhase.FAILED,
            RunPhase.CANCELLED,
        }
    ),
    RunPhase.RUNNING: frozenset(
        {
            RunPhase.RUNNING_MODEL,
            RunPhase.RUNNING_TOOL,
            RunPhase.WAITING_APPROVAL,
            RunPhase.FINALIZING,
            RunPhase.CANCELLED,
            RunPhase.FAILED,
            RunPhase.INTERRUPTED,
        }
    ),
    RunPhase.RUNNING_MODEL: frozenset(
        {
            RunPhase.RUNNING_TOOL,
            RunPhase.WAITING_APPROVAL,
            RunPhase.RUNNING,
            RunPhase.FINALIZING,
            RunPhase.CANCELLED,
            RunPhase.FAILED,
            RunPhase.INTERRUPTED,
        }
    ),
    RunPhase.RUNNING_TOOL: frozenset(
        {
            RunPhase.RUNNING_MODEL,
            RunPhase.WAITING_APPROVAL,
            RunPhase.RUNNING,
            RunPhase.FINALIZING,
            RunPhase.CANCELLED,
            RunPhase.FAILED,
            RunPhase.INTERRUPTED,
        }
    ),
    RunPhase.WAITING_APPROVAL: frozenset(
        {
            RunPhase.RUNNING_TOOL,
            RunPhase.RUNNING_MODEL,
            RunPhase.RUNNING,
            RunPhase.CANCELLED,
            RunPhase.FAILED,
            RunPhase.INTERRUPTED,
        }
    ),
    RunPhase.FINALIZING: frozenset(
        {RunPhase.COMPLETED, RunPhase.FAILED, RunPhase.INTERRUPTED}
    ),
    # Terminal states — no outgoing transitions
    RunPhase.COMPLETED: frozenset(),
    RunPhase.CANCELLED: frozenset(),
    RunPhase.FAILED: frozenset(),
    RunPhase.INTERRUPTED: frozenset(),
}


def allowed_run_transitions(phase: RunPhase) -> frozenset[RunPhase]:
    """Return the set of legal next phases from *phase*.

    An empty frozenset means *phase* is terminal.
    """
    return _PHASE_TRANSITIONS.get(phase, frozenset())


def is_terminal_run_phase(phase: RunPhase) -> bool:
    """True if *phase* is a terminal state (no further transitions)."""
    return not bool(_PHASE_TRANSITIONS.get(phase))


# ---------------------------------------------------------------------------
# InputDeliveryState — lifecycle of a single user input
# ---------------------------------------------------------------------------


class InputDeliveryState(StrEnum):
    """States an ``InputMessage`` can be in.

    These form a state machine where every input must eventually reach a
    terminal state — no silent loss.
    """

    ACCEPTED = "accepted"  # Received by harness, not yet processed
    IMMEDIATE_PENDING = "immediate_pending"  # Waiting for next safe checkpoint
    APPLIED = "applied"  # Inserted into the active Run's conversation
    QUEUED = "queued"  # Waiting for the current Run to end
    DEFERRED = "deferred"  # Was immediate but Run ended before application
    REJECTED = "rejected"  # Invalid (empty text, unknown thread, etc.)


# Input state transitions
_INPUT_TRANSITIONS: dict[InputDeliveryState, frozenset[InputDeliveryState]] = {
    InputDeliveryState.ACCEPTED: frozenset(
        {
            InputDeliveryState.IMMEDIATE_PENDING,
            InputDeliveryState.QUEUED,
            InputDeliveryState.REJECTED,
        }
    ),
    InputDeliveryState.IMMEDIATE_PENDING: frozenset(
        {
            InputDeliveryState.APPLIED,
            InputDeliveryState.DEFERRED,
        }
    ),
    InputDeliveryState.QUEUED: frozenset(
        {
            InputDeliveryState.APPLIED,
            InputDeliveryState.REJECTED,
        }
    ),
    InputDeliveryState.DEFERRED: frozenset(
        {
            InputDeliveryState.QUEUED,  # Re-enter queue at head for next Run
            InputDeliveryState.REJECTED,
        }
    ),
    InputDeliveryState.APPLIED: frozenset(),
    InputDeliveryState.REJECTED: frozenset(),
}


def allowed_input_transitions(
    state: InputDeliveryState,
) -> frozenset[InputDeliveryState]:
    """Return the set of legal next states from *state*."""
    return _INPUT_TRANSITIONS.get(state, frozenset())


# ---------------------------------------------------------------------------
# ExecutionTargetSnapshot — where the Run executes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExecutionTargetSnapshot:
    """Immutable description of the execution environment.

    Exactly one of the optional fields conveys the target type.
    """

    target_id: str  # Opaque identifier for the target
    kind: str  # "local", "docker", "podman", "ssh"
    workdir: str  # Canonical working directory
    profile_id: str = ""  # SSH profile or container config name

    def workspace_key(self) -> str:
        """Return a string that uniquely identifies this target + workdir.

        Used as input to ``WorkspaceKey`` for write-lease acquisition.
        """
        return f"{self.kind}:{self.target_id}:{self.workdir}"


# ---------------------------------------------------------------------------
# PermissionPolicySnapshot — what the Run is allowed to do
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PermissionPolicySnapshot:
    """Immutable permission policy for a Run.

    Captures the tool-call approval policy in effect at Run creation time.
    """

    auto_approve: bool = False
    allow_network: bool = False
    allow_file_write: bool = False
    allow_execute: bool = False
    max_approval_wait_seconds: int = 300
