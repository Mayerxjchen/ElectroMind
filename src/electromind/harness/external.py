"""ExternalTask — long-running external work that outlives a model Run.

The Harness does NOT understand domain semantics (Slurm jobs, HPC
queues, etc.).  It only tracks the generic lifecycle:

    submitted → waiting → running → completed | failed | cancelled | unknown

Domain adapters (out of scope) interpret the concrete external system;
the Harness stores a stable ``ExternalTaskRef`` per task so the client
can re-attach after a service restart, or the task is explicitly marked
``unknown`` when re-attachment is impossible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .identity import new_event_id


class ExternalTaskStatus(StrEnum):
    SUBMITTED = "submitted"
    WAITING = "waiting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class ExternalTaskRef:
    """Stable reference to an external task.

    ``external_task_id`` is the Harness-owned identity; ``remote_id`` is
    the concrete id inside the external system; ``resume_token`` lets a
    domain adapter re-attach after restart.  ``thread_id`` scopes the task
    to its owning thread — tasks never leak across threads.
    """

    external_task_id: str
    thread_id: str  # Owning thread — task refs are thread-scoped
    adapter: str  # Domain adapter name (e.g. "slurm", "ssh-cmd")
    target: str  # Execution target identifier
    remote_id: str
    workdir: str
    created_by_run_id: str
    resume_token: str

    status: ExternalTaskStatus = ExternalTaskStatus.SUBMITTED
    created_at: str = ""  # ISO 8601

    def update_status(self, status: ExternalTaskStatus) -> None:
        """Transition to a new generic status."""
        self.status = status

    def to_dict(self) -> dict:
        return {
            "external_task_id": self.external_task_id,
            "thread_id": self.thread_id,
            "adapter": self.adapter,
            "target": self.target,
            "remote_id": self.remote_id,
            "workdir": self.workdir,
            "created_by_run_id": self.created_by_run_id,
            "resume_token": self.resume_token,
            "status": str(self.status),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ExternalTaskRef":
        return cls(
            external_task_id=str(d.get("external_task_id", "")),
            thread_id=str(d.get("thread_id", "")),
            adapter=str(d.get("adapter", "")),
            target=str(d.get("target", "")),
            remote_id=str(d.get("remote_id", "")),
            workdir=str(d.get("workdir", "")),
            created_by_run_id=str(d.get("created_by_run_id", "")),
            resume_token=str(d.get("resume_token", "")),
            status=ExternalTaskStatus(str(d.get("status", "unknown"))),
            created_at=str(d.get("created_at", "")),
        )


@dataclass(slots=True)
class ExternalTaskRegistry:
    """Harness-owned registry of external tasks.

    Transport-agnostic: lives in the harness, not in the wire/HTTP layer.
    """

    _tasks: dict[str, ExternalTaskRef] = field(default_factory=dict)

    def register(self, task: ExternalTaskRef) -> ExternalTaskRef:
        """Register a new task (idempotent by external_task_id)."""
        self._tasks[task.external_task_id] = task
        return task

    def get(self, external_task_id: str) -> ExternalTaskRef | None:
        return self._tasks.get(external_task_id)

    def all(self) -> list[ExternalTaskRef]:
        return list(self._tasks.values())

    def for_thread(self, thread_id: str) -> list[ExternalTaskRef]:
        """Return the task refs owned by *thread_id* (thread-scoped)."""
        return [t for t in self._tasks.values() if t.thread_id == thread_id]

    def update_status(self, external_task_id: str, status: ExternalTaskStatus) -> bool:
        task = self._tasks.get(external_task_id)
        if task is None:
            return False
        task.update_status(status)
        return True

    def restore(self, tasks: list[ExternalTaskRef]) -> None:
        """Restore persisted tasks (idempotent)."""
        for task in tasks:
            self._tasks[task.external_task_id] = task

    def mark_unverifiable_unknown(self) -> None:
        """After a restart, tasks that were in-flight cannot be re-attached
        without a domain adapter confirmation → mark UNKNOWN (fail-closed,
        never guess success)."""
        for task in self._tasks.values():
            if task.status in (
                ExternalTaskStatus.SUBMITTED,
                ExternalTaskStatus.WAITING,
                ExternalTaskStatus.RUNNING,
            ):
                task.status = ExternalTaskStatus.UNKNOWN


def new_external_task_id() -> str:
    """Generate a stable external task id (prefix ``xtask-``)."""
    return f"xtask-{new_event_id()}"  # reuse the random-id machinery
