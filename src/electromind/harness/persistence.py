"""Harness state persistence — durable recovery for queues, approvals, and runs.

Every thread's harness state (queued inputs, pending immediate inputs,
pending approvals, active-run marker, external tasks) is stored as a
single JSON file next to the thread on disk (``harness_state.json``).
Writes are atomic (tmp file + rename) so a crash never leaves a corrupt
file.

Recovery contract (Gate 2):
- A present ``active_run_id`` means the process died while a Run was
  active → the Run must be marked ``interrupted``, never ``completed``.
- ``pending_immediate`` inputs are restored to the HEAD of the queue.
- ``pending_approvals`` are restored but immediately expired — their
  tool state cannot be re-verified after a restart (fail-closed).
- Restoring the same file twice yields the same state (idempotent).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .inbound import InputDelivery, InputMessage, InputReceipt
from .state import InputDeliveryState
from .workspace import ApprovalRequest

THREAD_STATE_FILENAME = "harness_state.json"
STATE_VERSION = 1


def thread_state_path(thread_root: Path) -> Path:
    """Return the harness state file path inside a thread directory."""
    return thread_root / THREAD_STATE_FILENAME


def save_thread_state(path: Path, state: dict) -> None:
    """Atomically write a thread state dict (tmp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_thread_state(path: Path) -> dict | None:
    """Load a thread state dict, or None if the file is absent/corrupt."""
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict):
            return None
        return state
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def state_dict_with(
    *,
    active_run_id: str | None = None,
    queued_inputs: list[InputMessage] | None = None,
    pending_immediate: list[InputMessage] | None = None,
    pending_approvals: list[ApprovalRequest] | None = None,
    external_tasks: list[dict] | None = None,
) -> dict:
    """Build a serializable thread state dict from harness objects."""
    return {
        "version": STATE_VERSION,
        "active_run_id": active_run_id,
        "queued_inputs": [input_message_to_dict(m) for m in (queued_inputs or [])],
        "pending_immediate": [
            input_message_to_dict(m) for m in (pending_immediate or [])
        ],
        "pending_approvals": [approval_to_dict(a) for a in (pending_approvals or [])],
        "external_tasks": list(external_tasks or []),
    }


# ---------------------------------------------------------------------------
# InputMessage (de)serialization
# ---------------------------------------------------------------------------


def input_message_to_dict(m: InputMessage) -> dict:
    return {
        "message_id": m.message_id,
        "thread_id": m.thread_id,
        "target_run_id": m.target_run_id,
        "text": m.text,
        "delivery": str(m.delivery),
        "created_at": m.created_at,
        "requested_mode": str(m.requested_mode) if m.requested_mode else None,
        "requested_model": m.requested_model,
        "requested_max_iterations": m.requested_max_iterations,
    }


def input_message_from_dict(d: dict) -> InputMessage:
    return InputMessage(
        message_id=str(d.get("message_id", "")),
        thread_id=str(d.get("thread_id", "")),
        target_run_id=d.get("target_run_id") or None,
        text=str(d.get("text", "")),
        delivery=InputDelivery(str(d.get("delivery", "auto"))),
        created_at=str(d.get("created_at", "")),
        requested_mode=str(d.get("requested_mode"))
        if d.get("requested_mode")
        else None,
        requested_model=d.get("requested_model") or None,
        requested_max_iterations=d.get("requested_max_iterations"),
    )


# ---------------------------------------------------------------------------
# InputReceipt (de)serialization
# ---------------------------------------------------------------------------


def receipt_to_dict(r: InputReceipt) -> dict:
    return {
        "message_id": r.message_id,
        "thread_id": r.thread_id,
        "state": str(r.state),
        "target_run_id": r.target_run_id,
        "detail": r.detail,
    }


def receipt_from_dict(d: dict) -> InputReceipt:
    return InputReceipt(
        message_id=str(d.get("message_id", "")),
        thread_id=str(d.get("thread_id", "")),
        state=InputDeliveryState(str(d.get("state", "queued"))),
        target_run_id=d.get("target_run_id") or None,
        detail=str(d.get("detail", "")),
    )


# ---------------------------------------------------------------------------
# ApprovalRequest (de)serialization
# ---------------------------------------------------------------------------


def approval_to_dict(a: ApprovalRequest) -> dict:
    return {
        "approval_id": a.approval_id,
        "thread_id": a.thread_id,
        "run_id": a.run_id,
        "tool_call_id": a.tool_call_id,
        "action_id": a.action_id,
        "target": a.target,
        "workdir": a.workdir,
        "risk": a.risk,
        "summary": a.summary,
        "expires_at": a.expires_at,
        "status": str(a.status),
    }


def approval_from_dict(d: dict) -> ApprovalRequest:
    return ApprovalRequest(
        approval_id=str(d.get("approval_id", "")),
        thread_id=str(d.get("thread_id", "")),
        run_id=str(d.get("run_id", "")),
        tool_call_id=str(d.get("tool_call_id", "")),
        action_id=str(d.get("action_id", "")),
        target=str(d.get("target", "")),
        workdir=str(d.get("workdir", "")),
        risk=str(d.get("risk", "low")),
        summary=str(d.get("summary", "")),
        expires_at=str(d.get("expires_at", "")),
    )
