"""WorkspaceLease — prevent concurrent writes to the same workspace.

And ApprovalRequest — scoped approval that expires with its Run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .identity import WorkspaceKey
from .state import SessionMode

# ============================================================================
# WorkspaceLease
# ============================================================================


class LeaseState(StrEnum):
    FREE = "free"
    READ_SHARED = "read_shared"
    WRITE_EXCLUSIVE = "write_exclusive"


@dataclass(slots=True)
class WorkspaceLease:
    """Tracks who holds the write lease for a workspace.

    Ask/Plan Runs are read-only and do not acquire the write lease.
    Run mode with write-capable tools must acquire the exclusive lease
    before starting.
    """

    key: WorkspaceKey
    holder_run_id: str | None = None
    holder_thread_id: str | None = None
    state: LeaseState = LeaseState.FREE

    def acquire_write(self, run_id: str, thread_id: str) -> bool:
        """Attempt to acquire the exclusive write lease.  Returns True on success."""
        if self.state != LeaseState.FREE:
            return False
        self.holder_run_id = run_id
        self.holder_thread_id = thread_id
        self.state = LeaseState.WRITE_EXCLUSIVE
        return True

    def release(self) -> None:
        """Release the lease back to FREE."""
        self.holder_run_id = None
        self.holder_thread_id = None
        self.state = LeaseState.FREE


@dataclass(slots=True)
class WorkspaceLeaseRegistry:
    """Registry of all workspace leases.

    Before starting a Run with write access, the harness must acquire
    the lease.  Conflict → the Run stays in ``waiting_for_workspace``.
    """

    _leases: dict[str, WorkspaceLease] = field(default_factory=dict)

    def _key_str(self, key: WorkspaceKey) -> str:
        return str(key)

    def acquire(
        self, key: WorkspaceKey, run_id: str, thread_id: str, mode: SessionMode
    ) -> bool:
        """Try to acquire the lease for a Run.

        Read-only modes (ask, plan) always succeed without acquiring
        the write lease.

        Returns True if the Run can proceed; False if it must wait.
        """
        if mode in (SessionMode.ASK, SessionMode.PLAN):
            # Read-only — always allowed
            return True

        k = self._key_str(key)
        if k not in self._leases:
            self._leases[k] = WorkspaceLease(key=key)
        return self._leases[k].acquire_write(run_id, thread_id)

    def release(self, key: WorkspaceKey, run_id: str) -> bool:
        """Release a write lease.  Only the holder may release it."""
        k = self._key_str(key)
        lease = self._leases.get(k)
        if lease is None:
            return False
        if lease.holder_run_id != run_id:
            return False
        lease.release()
        return True

    def get_holder(self, key: WorkspaceKey) -> tuple[str, str] | None:
        """Return (run_id, thread_id) of the current lease holder, or None."""
        k = self._key_str(key)
        lease = self._leases.get(k)
        if lease is None or lease.state != LeaseState.WRITE_EXCLUSIVE:
            return None
        return (lease.holder_run_id, lease.holder_thread_id)  # type: ignore[return-value]

    def is_free(self, key: WorkspaceKey) -> bool:
        """True if the workspace has no write lease."""
        k = self._key_str(key)
        lease = self._leases.get(k)
        return lease is None or lease.state == LeaseState.FREE


# ============================================================================
# ApprovalRequest — scoped to Run
# ============================================================================


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class ApprovalRequest:
    """A tool-call approval request scoped to a specific Run.

    Cross-Run or cross-Thread approval is impossible: resolution validates
    thread_id, run_id, and tool_call_id.
    """

    approval_id: str
    thread_id: str
    run_id: str
    tool_call_id: str
    action_id: str = ""

    target: str = ""  # Execution target identifier
    workdir: str = ""
    risk: str = "low"  # "low" | "medium" | "high"
    summary: str = ""
    expires_at: str = ""  # ISO 8601

    status: ApprovalStatus = ApprovalStatus.PENDING

    def is_resolvable(self) -> bool:
        """True if the approval can still be resolved."""
        return self.status == ApprovalStatus.PENDING

    def approve(self) -> bool:
        if not self.is_resolvable():
            return False
        self.status = ApprovalStatus.APPROVED
        return True

    def deny(self, reason: str = "") -> bool:
        if not self.is_resolvable():
            return False
        self.status = ApprovalStatus.DENIED
        return True

    def expire(self) -> bool:
        if not self.is_resolvable():
            return False
        self.status = ApprovalStatus.EXPIRED
        return True

    def cancel(self) -> bool:
        if not self.is_resolvable():
            return False
        self.status = ApprovalStatus.CANCELLED
        return True

    def validate_context(
        self,
        thread_id: str,
        run_id: str,
        tool_call_id: str | None = None,
    ) -> bool:
        """Verify that a resolution request matches this approval's context.

        All provided fields must match.  Mismatch → stale/hijack attempt.
        """
        if self.thread_id != thread_id:
            return False
        if self.run_id != run_id:
            return False
        if tool_call_id is not None and self.tool_call_id != tool_call_id:
            return False
        return True
