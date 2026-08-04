"""Security audit trail for sandbox operations.

Every auto-approved operation is logged with:
- timestamp
- thread_id
- operation (command_exec, file_write, file_delete)
- target (path or command)
- autonomy level at time of operation
- sandbox backend and isolation state

This creates an immutable (append-only) audit log that can be reviewed
to verify Auto-safe never silently escalates privileges.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AuditEntry:
    timestamp: float
    thread_id: str
    operation: str  # "command_exec" | "file_write" | "file_delete" | "file_export"
    target: str  # command string or file path
    autonomy: str  # "prompt" | "auto-safe" | "full-access"
    session_mode: str  # "ask" | "plan" | "agent"
    backend: str  # "local" | "docker" | "podman" | "ssh"
    isolated: bool
    outcome: str  # "allowed" | "blocked" | "error"
    detail: str = ""


class AuditLog:
    """Append-only audit log stored in the sandbox workdir.

    Thread-safe writes via append-only JSON lines (one entry per line).
    """

    _FILENAME = ".electromind_audit.jsonl"

    def __init__(self, log_dir: str | Path) -> None:
        self._path = Path(log_dir) / self._FILENAME

    def record(self, entry: AuditEntry) -> None:
        line = json.dumps(asdict(entry), ensure_ascii=False) + "\n"
        try:
            os.makedirs(self._path.parent, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass  # Audit failure must never block operations

    def read(self, *, limit: int = 200) -> list[dict]:
        """Read the most recent *limit* entries."""
        if not self._path.exists():
            return []
        entries: list[dict] = []
        try:
            with open(self._path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return []
        return entries[-limit:]

    def count_since(self, since: float) -> int:
        """Count entries recorded since *since* (unix timestamp)."""
        if not self._path.exists():
            return 0
        count = 0
        try:
            with open(self._path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("timestamp", 0) >= since:
                            count += 1
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return 0
        return count


# ── Backend transition guard ──────────────────────────────────────────


class BackendTransitionGuard:
    """Prevents Auto-safe from silently changing the execution backend.

    Once a backend type is locked for a thread, any transition must be
    explicit (user action), not an Auto-safe side effect.
    """

    def __init__(self) -> None:
        self._locked_backend: str | None = None
        self._locked_by: str = ""  # "user" | "auto"

    def lock(self, backend: str, by: str = "user") -> None:
        self._locked_backend = backend
        self._locked_by = by

    def check_transition(self, new_backend: str, requested_by: str = "auto") -> bool:
        """Return True if the transition is allowed."""
        if self._locked_backend is None:
            return True
        if new_backend == self._locked_backend:
            return True
        # Auto-safe can never change the backend
        if requested_by == "auto" and self._locked_by == "user":
            return False
        return True

    def is_locked(self) -> bool:
        return self._locked_backend is not None

    @property
    def current_backend(self) -> str | None:
        return self._locked_backend
