"""ThreadSessionManager — per-thread run lifecycle, input routing, and concurrency.

The manager owns all ThreadSessions.  It ensures:
- One active Run per Thread (sequential execution).
- Multiple Threads can run in parallel without blocking each other.
- Locks protect only state transitions; model/tool/SSH calls happen unlocked.
- Runners are lazily created; idle runners are closed after a configurable TTL.
- Switching the UI's selected thread does NOT close the previous runner.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from .external import ExternalTaskRegistry
from .identity import WorkspaceKey, new_run_id
from .inbound import (
    InputDelivery,
    InputMessage,
    InputQueue,
    InputReceipt,
    immediate_pending_receipt,
    queued_receipt,
    rejected_receipt,
)
from .state import RunPhase, SessionMode, allowed_run_transitions, is_terminal_run_phase
from .workspace import WorkspaceLeaseRegistry

# ---------------------------------------------------------------------------
# ThreadSession
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ThreadSession:
    """Per-thread state managed by ThreadSessionManager.

    ``runner`` is the opaque Runner reference (None when dormant).
    ``active_run`` is the current Run's identity and phase.
    ``queued_inputs`` holds enqueued inputs waiting for the next Run.
    ``pending_approvals`` maps approval_id → ApprovalRequest (H6).
    ``event_seq`` is a per-thread monotonic event counter.
    """

    thread_id: str

    # Runner lifecycle
    runner: object | None = None  # Opaque Runner reference
    active_run_id: str | None = None
    active_run_phase: RunPhase = RunPhase.DORMANT

    # Input management
    queued_inputs: InputQueue = field(default_factory=InputQueue)
    pending_immediate: list[InputMessage] = field(default_factory=list)
    # message_id → original InputReceipt for EVERY accounted input (queued,
    # immediate, or already consumed by a Run).  Bounded — oldest entries
    # are evicted.  This is what makes retries idempotent even AFTER a Run
    # consumed the message (a duplicate must never append again or start a
    # second Run).
    receipt_history: dict[str, InputReceipt] = field(default_factory=dict)

    # Approval management (H6)
    pending_approvals: dict[str, object] = field(default_factory=dict)
    # Approvals expired by a terminal Run transition (awaiting event emission)
    _expired_approvals: list[object] = field(default_factory=list)

    # Immutable RunSnapshot frozen at Run creation (identity.RunSnapshot)
    run_snapshot: object | None = None

    # Event sequencing
    event_seq: int = 0
    last_activity: float = 0.0  # monotonic time of last interaction

    # Concurrency
    lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # Status
    status: str = "dormant"  # "dormant" | "running" | "idle"

    def next_seq(self) -> int:
        """Return and increment the per-thread event sequence number."""
        seq = self.event_seq
        self.event_seq += 1
        return seq

    def touch(self) -> None:
        """Mark activity for idle TTL tracking."""
        self.last_activity = time.monotonic()


# ---------------------------------------------------------------------------
# ThreadSessionManager
# ---------------------------------------------------------------------------


def _run_snapshot_to_dict(snapshot: object | None) -> dict | None:
    """Serialize a frozen RunSnapshot for the wire snapshot response."""
    if snapshot is None:
        return None
    d: dict = {}
    for attr in (
        "run_id",
        "thread_id",
        "input_message_id",
        "session_mode",
        "model",
        "max_iterations",
        "project_path",
        "system_prompt_digest",
        "skill_set_digest",
        "tool_set_digest",
        "created_at",
    ):
        value = getattr(snapshot, attr, None)
        if value is not None:
            d[attr] = value if isinstance(value, (int, bool)) else str(value)
    execution_target = getattr(snapshot, "execution_target", None)
    if execution_target is not None:
        # Accept both ExecutionTargetSnapshot (kind/workdir) and
        # WorkspaceKey (execution_target_id/canonical_workdir).
        target_id = getattr(execution_target, "target_id", "") or getattr(
            execution_target, "execution_target_id", ""
        )
        kind = getattr(execution_target, "kind", "") or str(target_id)
        workdir = getattr(execution_target, "workdir", "") or getattr(
            execution_target, "canonical_workdir", ""
        )
        d["execution_target"] = {
            "target_id": target_id,
            "kind": kind,
            "workdir": workdir,
            "profile_id": getattr(execution_target, "profile_id", ""),
        }
    policy = getattr(snapshot, "permission_policy", None)
    if policy is not None:
        d["permission_policy"] = {
            "auto_approve": bool(getattr(policy, "auto_approve", False)),
            "allow_network": bool(getattr(policy, "allow_network", False)),
            "allow_file_write": bool(getattr(policy, "allow_file_write", False)),
            "allow_execute": bool(getattr(policy, "allow_execute", False)),
            "max_approval_wait_seconds": getattr(
                policy, "max_approval_wait_seconds", 300
            ),
        }
    return d


@dataclass(slots=True)
class ThreadSessionManager:
    """Central coordinator for all Thread sessions.

    Thread-safe: each ThreadSession has its own ``lifecycle_lock``.
    Operations on different threads do not block each other.
    """

    _sessions: dict[str, ThreadSession] = field(default_factory=dict)
    _idle_ttl_seconds: float = 900.0  # 15 minutes

    # Threads waiting to acquire a workspace lease (key str → thread_ids).
    # Woken by the wire layer when the holder releases (Gate 1, 八).
    _workspace_waiters: dict[str, list[str]] = field(default_factory=dict)

    # Workspace write leases — one write Run per WorkspaceKey (Gate 1, 八).
    workspace_leases: WorkspaceLeaseRegistry = field(
        default_factory=WorkspaceLeaseRegistry
    )
    # External tasks registry (Gate 2, 十) — transport-agnostic.
    external_tasks: ExternalTaskRegistry = field(default_factory=ExternalTaskRegistry)

    # ── Session access ──────────────────────────────────────────────

    def _get_or_create(self, thread_id: str) -> ThreadSession:
        """Return the session for *thread_id*, creating it if needed."""
        if thread_id not in self._sessions:
            self._sessions[thread_id] = ThreadSession(thread_id=thread_id)
        return self._sessions[thread_id]

    def get_session(self, thread_id: str) -> ThreadSession | None:
        """Return the session for *thread_id*, or None."""
        return self._sessions.get(thread_id)

    def has_active_run(self, thread_id: str) -> bool:
        """True if the thread has an active (non-terminal) Run."""
        session = self._sessions.get(thread_id)
        if session is None:
            return False
        return session.active_run_id is not None and session.active_run_phase not in (
            RunPhase.COMPLETED,
            RunPhase.CANCELLED,
            RunPhase.FAILED,
            RunPhase.INTERRUPTED,
        )

    # ── Input handling ──────────────────────────────────────────────

    async def send_input(self, message: InputMessage) -> InputReceipt:
        """Accept a user input and route it according to its delivery mode.

        Returns an ``InputReceipt`` that must be sent back to the client
        as an ACK.  The input is always accounted for — no silent loss.

        Idempotent retry: a message_id already present in the queue or
        pending-immediate list replays the ORIGINAL receipt instead of
        being appended again (a duplicate client retry must not add a
        second copy of the message or start a second Run).
        """
        # 1. Reject empty input
        if message.is_empty:
            return rejected_receipt(message, "Empty input text")

        session = self._get_or_create(message.thread_id)

        async with session.lifecycle_lock:
            # 1b. Same message_id already accounted for → replay the receipt
            existing = self._find_existing_receipt(session, message.message_id)
            if existing is not None:
                return existing
            return self._route_input(session, message)

    @staticmethod
    def _find_existing_receipt(
        session: ThreadSession, message_id: str
    ) -> InputReceipt | None:
        """Return the original receipt for an already-accounted message_id.

        Covers messages still queued/pending AND messages already consumed
        by a Run (the receipt history records every routed input).  Must
        only be called while holding ``session.lifecycle_lock``.
        """
        if not message_id:
            return None
        cached = session.receipt_history.get(message_id)
        if cached is not None:
            return cached
        for q in session.queued_inputs.all():
            if q.message_id == message_id:
                return queued_receipt(q)
        for m in session.pending_immediate:
            if m.message_id == message_id:
                return immediate_pending_receipt(m)
        return None

    RECEIPT_HISTORY_LIMIT = 1024

    @staticmethod
    def _trim_receipt_history(session: ThreadSession) -> None:
        """Bound the receipt history to its cap (oldest entries evicted).

        Must only be called while holding ``session.lifecycle_lock``.
        """
        while len(session.receipt_history) > ThreadSessionManager.RECEIPT_HISTORY_LIMIT:
            session.receipt_history.pop(next(iter(session.receipt_history)))

    @staticmethod
    def _record_receipt(
        session: ThreadSession, message: InputMessage, receipt: InputReceipt
    ) -> None:
        """Remember the original receipt for an accounted message_id.

        Kept for the lifetime of the session (bounded — oldest evicted) so
        a client retry replays the ORIGINAL receipt even after a Run has
        consumed the message.  Must only be called while holding
        ``session.lifecycle_lock``.
        """
        if not message.message_id:
            return
        session.receipt_history[message.message_id] = receipt
        ThreadSessionManager._trim_receipt_history(session)

    def _route_input(
        self, session: ThreadSession, message: InputMessage
    ) -> InputReceipt:
        """Route a validated input within the session lock.

        Must only be called while holding ``session.lifecycle_lock``.

        IMPORTANT: this only manages input delivery state.  It does NOT
        create a Run — that happens when the caller calls ``start_run()``
        and actually opens a Runner.
        """
        # 2. Thread idle → queue the input (caller decides when to start Run)
        if not self.has_active_run(session.thread_id):
            session.queued_inputs.enqueue(message)
            session.status = "running"
            session.touch()
            receipt = queued_receipt(message)
            self._record_receipt(session, message, receipt)
            return receipt

        # 3. Thread has an active Run
        if message.delivery == InputDelivery.ENQUEUE:
            session.queued_inputs.enqueue(message)
            session.touch()
            receipt = queued_receipt(message)
            self._record_receipt(session, message, receipt)
            return receipt

        # 4. AUTO delivery when running → treat as IMMEDIATE
        # 5. IMMEDIATE delivery
        session.pending_immediate.append(message)
        session.touch()
        receipt = immediate_pending_receipt(message)
        self._record_receipt(session, message, receipt)
        return receipt

    # ── Run lifecycle ───────────────────────────────────────────────

    @staticmethod
    def _can_transition(session: ThreadSession, target: RunPhase) -> bool:
        """True if ``target`` is a legal next phase from the current phase.

        All phase changes go through ``allowed_run_transitions()`` — the
        single centralized transition map (state.py).  No ad-hoc phase
        assignment.
        """
        return target in allowed_run_transitions(session.active_run_phase)

    async def start_run(
        self, thread_id: str, runner: object, *, run_id: str | None = None
    ) -> tuple[str, object] | None:
        """Start a Run for *thread_id* — the single atomic entry point.

        In one lock-held operation: consumes the next queued input, creates
        a fresh run_id (or reuses ``run_id`` when the caller pre-created it,
        e.g. for workspace-lease acquisition), and transitions the session
        to RUNNING.

        Returns ``(run_id, input_message)``, or None if a Run is already
        active or no input is queued.
        """
        session = self._get_or_create(thread_id)
        async with session.lifecycle_lock:
            # Phase legality:
            # - No Run yet → fresh start.
            # - Terminal phase → the OLD run is over; a NEW Run is born
            #   (fresh run_id) — this is not a transition of the old run.
            # - Any other active phase → reject (one Run per Thread).
            if session.active_run_id is not None:
                if is_terminal_run_phase(session.active_run_phase):
                    pass  # Birth a new Run below
                elif not self._can_transition(session, RunPhase.RUNNING):
                    return None
            if not session.queued_inputs:
                return None
            queued = session.queued_inputs.dequeue()
            if queued is None:
                return None
            if run_id is None:
                run_id = new_run_id()
            session.active_run_id = run_id
            session.runner = runner
            session.active_run_phase = RunPhase.RUNNING
            session.status = "running"
            session.touch()
            return (run_id, queued)

    async def update_run_phase(
        self, thread_id: str, run_id: str, phase: RunPhase
    ) -> bool:
        """精细相位推进（RUNNING_MODEL/RUNNING_TOOL/WAITING_APPROVAL）。

        走同一张集中转换表（``allowed_run_transitions``）；非法转换返回
        False 且不修改状态。这是 RunEngine 声明循环内相位的唯一入口。
        """
        session = self._sessions.get(thread_id)
        if session is None:
            return False
        async with session.lifecycle_lock:
            if session.active_run_id != run_id:
                return False
            if not self._can_transition(session, phase):
                return False
            session.active_run_phase = phase
            return True

    async def complete_run(self, thread_id: str, run_id: str) -> bool:
        """Mark a Run as completed.  Expires all pending approvals for the
        Run (old approvals must be invalid after Run end).  Returns True."""
        session = self._sessions.get(thread_id)
        if session is None:
            return False
        async with session.lifecycle_lock:
            if session.active_run_id != run_id:
                return False
            if session.active_run_phase == RunPhase.RUNNING:
                # Legal path is RUNNING → FINALIZING → COMPLETED; walk the
                # intermediate phase instead of skipping it.
                session.active_run_phase = RunPhase.FINALIZING
            if not self._can_transition(session, RunPhase.COMPLETED):
                return False
            session.active_run_phase = RunPhase.COMPLETED
            session.status = "idle"
            session.touch()
            self._defer_pending_immediate(session)
            self._expire_all_approvals(session)
            return True

    async def cancel_run(self, thread_id: str, run_id: str) -> bool:
        """Cancel an active Run.  Expires all pending approvals for the Run.
        Returns True if successful."""
        session = self._sessions.get(thread_id)
        if session is None:
            return False
        async with session.lifecycle_lock:
            if session.active_run_id != run_id:
                return False
            if not self._can_transition(session, RunPhase.CANCELLED):
                return False
            session.active_run_phase = RunPhase.CANCELLED
            session.status = "idle"
            session.touch()
            self._defer_pending_immediate(session)
            self._expire_all_approvals(session)
            return True

    async def fail_run(self, thread_id: str, run_id: str) -> bool:
        """Mark a Run as failed.  Expires all pending approvals for the Run.
        Returns True if successful."""
        session = self._sessions.get(thread_id)
        if session is None:
            return False
        async with session.lifecycle_lock:
            if session.active_run_id != run_id:
                return False
            if not self._can_transition(session, RunPhase.FAILED):
                return False
            session.active_run_phase = RunPhase.FAILED
            session.status = "idle"
            session.touch()
            self._defer_pending_immediate(session)
            self._expire_all_approvals(session)
            return True

    def _expire_all_approvals(self, session: ThreadSession) -> None:
        """Atomically expire and remove every pending approval of the session.

        Must only be called while holding ``session.lifecycle_lock``.
        Expired approvals are recorded on the session so the caller can
        emit ``approval/resolved(expired)`` events via ``take_expired_approvals``.
        """
        for approval in session.pending_approvals.values():
            expire = getattr(approval, "expire", None)
            if callable(expire):
                expire()
            session._expired_approvals.append(approval)
        session.pending_approvals.clear()

    # ── Workspace write leases (Gate 1, 八) ─────────────────────────

    async def try_acquire_workspace(
        self,
        thread_id: str,
        key: WorkspaceKey,
        run_id: str,
        mode: SessionMode,
    ) -> bool:
        """Try to acquire the write lease for a Run.

        Read-only modes (ask/plan) never block.  Write modes conflict →
        False (the caller must wait or fail the Run; input stays queued).
        """
        async with self._get_or_create(thread_id).lifecycle_lock:
            return self.workspace_leases.acquire(key, run_id, thread_id, mode)

    async def release_workspace(self, thread_id: str, run_id: str) -> bool:
        """Release the write lease held by *run_id* (no-op when not held)."""
        session = self._sessions.get(thread_id)
        if session is None:
            return False
        async with session.lifecycle_lock:
            for lease in list(self.workspace_leases._leases.values()):
                if self.workspace_leases.release(lease.key, run_id):
                    return True
            return False

    # ── Workspace waiters (Gate 1, 八: 释放后唤醒等待者) ──────────────

    def register_workspace_waiter(self, thread_id: str, key: WorkspaceKey) -> None:
        """Record a thread waiting to acquire the lease for *key*.

        The wire layer calls this when a Run cannot start due to a lease
        conflict, then wakes the waiters after the holder releases.
        """
        key_str = str(key)
        waiters = self._workspace_waiters.setdefault(key_str, [])
        if thread_id not in waiters:
            waiters.append(thread_id)

    def take_workspace_waiters(self, key: WorkspaceKey) -> list[str]:
        """Return and clear the threads waiting on *key* (after release)."""
        return self._workspace_waiters.pop(str(key), [])

    def workspace_holder(self, key: WorkspaceKey) -> tuple[str, str] | None:
        """Return (run_id, thread_id) holding *key*, or None."""
        return self.workspace_leases.get_holder(key)

    # ── Recovery (Gate 2, 九) ───────────────────────────────────────

    async def mark_interrupted(self, thread_id: str, run_id: str) -> bool:
        """Mark a Run interrupted after a restart.

        Only called during recovery, from a persisted active-run marker.
        ``interrupted`` is a legal terminal for RUNNING/FINALIZING; for
        PREPARING/DORMANT it is the recovery-marked terminal (the process
        died mid-flight — never report ``completed``).
        """
        session = self._get_or_create(thread_id)
        async with session.lifecycle_lock:
            if session.active_run_id != run_id:
                return False
            session.active_run_phase = RunPhase.INTERRUPTED
            session.status = "idle"
            session.touch()
            self._defer_pending_immediate(session)
            self._expire_all_approvals(session)
            return True

    def peek_queued_input(self, thread_id: str) -> InputMessage | None:
        """Return the next queued input WITHOUT consuming it (or None)."""
        session = self._sessions.get(thread_id)
        if session is None:
            return None
        return session.queued_inputs.peek()

    def restore_queued_inputs(
        self, thread_id: str, messages: list[InputMessage]
    ) -> None:
        """Restore persisted plain queued inputs at the TAIL, preserving
        FIFO order (deferred immediates then re-insert ahead of them)."""
        session = self._get_or_create(thread_id)
        for msg in messages:
            session.queued_inputs.enqueue(msg)

    def restore_queued_at_head(
        self, thread_id: str, messages: list[InputMessage]
    ) -> None:
        """Requeue persisted inputs at the HEAD (deferred-immediate order)."""
        session = self._get_or_create(thread_id)
        for msg in reversed(messages):
            session.queued_inputs.enqueue_head(msg)

    def restore_approvals(self, thread_id: str, approvals: list) -> None:
        """Restore persisted approvals, then expire them (fail-closed:
        their tool state cannot be re-verified after a restart)."""
        session = self._get_or_create(thread_id)
        for approval in approvals:
            session.pending_approvals[approval.approval_id] = approval
        self._expire_all_approvals(session)

    def restore_receipt_history(
        self, thread_id: str, receipts: list[InputReceipt]
    ) -> None:
        """Restore persisted input receipts so message_id retries stay
        idempotent across a restart (a consumed message must not be
        re-appended after recovery).  The cap is enforced the same way as
        live recording: oversized restores are trimmed to the newest
        1024 entries."""
        session = self._get_or_create(thread_id)
        for receipt in receipts:
            if receipt.message_id:
                session.receipt_history[receipt.message_id] = receipt
        ThreadSessionManager._trim_receipt_history(session)

    def restore_session_marker(self, thread_id: str, run_id: str) -> None:
        """Register a persisted active-run marker without starting a Run.

        The recovery caller then calls ``mark_interrupted`` to terminalise
        the marker run.
        """
        session = self._get_or_create(thread_id)
        session.active_run_id = run_id
        session.active_run_phase = RunPhase.RUNNING  # Best-effort pre-crash state
        session.status = "running"

    async def take_expired_approvals(self, thread_id: str) -> list[object]:
        """Return and clear approvals expired by a terminal Run transition.

        The caller (wire layer) emits ``approval/resolved(expired)`` events
        for each returned approval.
        """
        session = self._sessions.get(thread_id)
        if session is None:
            return []
        async with session.lifecycle_lock:
            expired = list(session._expired_approvals)
            session._expired_approvals.clear()
            return expired

    def _defer_pending_immediate(self, session: ThreadSession) -> None:
        """Move pending immediate inputs to the queue head as deferred."""
        for msg in reversed(session.pending_immediate):
            session.queued_inputs.enqueue_head(msg)
        session.pending_immediate.clear()

    async def take_pending_immediate(self, thread_id: str) -> list[InputMessage]:
        """Drain pending immediate inputs for live steering at a checkpoint.

        The run loop calls this after each event: IMMEDIATE inputs become
        ``applied`` (steered into the current run) instead of waiting for
        the run to end.  Inputs that arrive after the last checkpoint are
        deferred to the queue head by the terminal transition instead.
        """
        session = self._sessions.get(thread_id)
        if session is None or not session.pending_immediate:
            return []
        async with session.lifecycle_lock:
            drained = list(session.pending_immediate)
            session.pending_immediate.clear()
            session.touch()
            return drained

    async def settle_pending_immediate(
        self, thread_id: str, unread: list[tuple[str, str]]
    ) -> tuple[list[InputMessage], list[InputMessage]]:
        """Classify pending immediates after a Run ends.

        ``unread`` is the list of (message_id, text) pairs the runner's
        mailbox never consumed.  Classification is by EXACT message_id —
        never by text (two steers can share the same text; a text-count
        guess would swap their fate).  A text-count fallback applies ONLY
        to entries without a message_id (legacy runners).

        - ``deferred``: never read → the ORIGINAL InputMessage is returned
          so the caller re-queues it with its identity intact.
        - ``applied``: consumed by the loop (applied as user messages).
        Both leave ``pending_immediate`` (now empty); the caller enqueues
        the deferred ones and ACKs both sides.  Messages stay in
        ``pending_immediate`` until THIS settle point, so a crash between
        steer and checkpoint never loses them (they are persisted).
        """
        session = self._sessions.get(thread_id)
        if session is None:
            return [], []
        async with session.lifecycle_lock:
            by_id: dict[str, int] = {}
            by_text: dict[str, int] = {}
            for mid, text in unread:
                if mid:
                    by_id[mid] = by_id.get(mid, 0) + 1
                else:
                    by_text[text] = by_text.get(text, 0) + 1
            deferred: list[InputMessage] = []
            applied: list[InputMessage] = []
            for msg in session.pending_immediate:
                if by_id.get(msg.message_id, 0) > 0:
                    deferred.append(msg)
                    by_id[msg.message_id] -= 1
                elif by_text.get(msg.text, 0) > 0:
                    deferred.append(msg)
                    by_text[msg.text] -= 1
                else:
                    applied.append(msg)
            session.pending_immediate = []
            return deferred, applied

    def _maybe_start_next(self, session: ThreadSession) -> None:
        """If there are queued inputs, transition to DORMANT to trigger
        the next Run.  The actual Runner creation is done by the caller
        (outside the lock)."""
        if session.queued_inputs:
            session.active_run_id = new_run_id()
            session.active_run_phase = RunPhase.DORMANT
            session.status = "running"

    # ── Approval routing (H6 pre-placement) ─────────────────────────

    async def add_approval(self, thread_id: str, approval: object) -> bool:
        """Register a pending approval.  Returns True if registered."""
        session = self._sessions.get(thread_id)
        if session is None:
            return False
        async with session.lifecycle_lock:
            # Stored with approval_id as key; caller provides the object
            session.pending_approvals[getattr(approval, "approval_id", "")] = approval
            return True

    async def resolve_approval(
        self,
        thread_id: str,
        run_id: str,
        approval_id: str,
        approved: bool,
        tool_call_id: str | None = None,
    ) -> object | None:
        """Resolve an approval.  Returns the approval object if found and
        valid, or None if the approval is stale (wrong Run, wrong tool call,
        already resolved, expired, or unknown).

        Validate-then-consume: the approval is looked up WITHOUT removing it;
        only when thread/run/status/tool_call_id all match is it atomically
        popped and transitioned.  A wrong tool_call_id therefore does NOT
        consume the legitimate approval.
        """
        session = self._sessions.get(thread_id)
        if session is None:
            return None
        async with session.lifecycle_lock:
            if session.active_run_id != run_id:
                # Stale: approval is for a different Run
                return None
            # Run must be in an active phase — completed/cancelled/failed/
            # interrupted runs cannot have approvals resolved.  M1: 精细相位
            # （RUNNING_MODEL/RUNNING_TOOL/WAITING_APPROVAL）同样视为活动。
            if is_terminal_run_phase(session.active_run_phase):
                return None
            approval = session.pending_approvals.get(approval_id)  # peek
            if approval is None:
                return None
            # The approval's own thread/run binding must match (defense in depth)
            apr_thread = getattr(approval, "thread_id", "")
            if apr_thread and apr_thread != thread_id:
                return None  # Do NOT consume on mismatch
            apr_run = getattr(approval, "run_id", "")
            if apr_run and apr_run != run_id:
                return None  # Do NOT consume on mismatch
            # Must still be pending — already resolved/expired/cancelled
            # approvals are not resolvable.
            status = getattr(approval, "status", None)
            if status is not None and str(status) != "pending":
                return None
            if tool_call_id is not None:
                bound = getattr(approval, "tool_call_id", "")
                if bound and bound != tool_call_id:
                    return None  # Do NOT consume on mismatch
            # All checks passed — atomically consume and transition
            session.pending_approvals.pop(approval_id, None)
            if approved:
                approve = getattr(approval, "approve", None)
                if callable(approve):
                    approve()
            else:
                deny = getattr(approval, "deny", None)
                if callable(deny):
                    deny()
            return approval

    # ── Snapshot ────────────────────────────────────────────────────

    async def get_snapshot(self, thread_id: str) -> dict:
        """Return a snapshot of the thread's current state.

        Suitable for client reconnection and state recovery.
        """
        session = self._sessions.get(thread_id)
        if session is None:
            return {
                "thread_id": thread_id,
                "exists": False,
            }

        async with session.lifecycle_lock:
            snapshot = {
                "thread_id": session.thread_id,
                "exists": True,
                "active_run_id": session.active_run_id,
                "active_run_phase": str(session.active_run_phase),
                "status": session.status,
                "queued_input_count": len(session.queued_inputs),
                "queued_inputs": [
                    {
                        "message_id": m.message_id,
                        "text": m.text,
                        "delivery": str(m.delivery),
                    }
                    for m in session.queued_inputs.all()
                ],
                "pending_immediate_count": len(session.pending_immediate),
                "pending_immediate": [
                    {
                        "message_id": m.message_id,
                        "text": m.text,
                    }
                    for m in session.pending_immediate
                ],
                "pending_approval_count": len(session.pending_approvals),
                "pending_approvals": [
                    {
                        "approval_id": aid,
                        "tool_call_id": getattr(a, "tool_call_id", ""),
                        "run_id": getattr(a, "run_id", ""),
                    }
                    for aid, a in session.pending_approvals.items()
                ],
                "event_seq": session.event_seq,
                # Immutable RunSnapshot frozen at Run creation (if any)
                "run_snapshot": _run_snapshot_to_dict(session.run_snapshot),
                # External task refs owned by THIS thread (Gate 2, 十) —
                # never leak another thread's tasks/remote ids/tokens.
                "external_tasks": [
                    t.to_dict() for t in self.external_tasks.for_thread(thread_id)
                ],
            }
            return snapshot

    async def set_run_snapshot(self, thread_id: str, snapshot: object) -> bool:
        """Freeze the immutable RunSnapshot for the ACTIVE Run.

        Only the current active Run may install its snapshot, and only
        once: a snapshot for a stale/foreign run_id is rejected, and a
        second ``set_run_snapshot`` for the same run_id is rejected (the
        frozen dataclass only blocks field mutation, not whole-snapshot
        replacement).
        """
        session = self._sessions.get(thread_id)
        if session is None:
            return False
        async with session.lifecycle_lock:
            if getattr(snapshot, "run_id", None) != session.active_run_id:
                return False  # Not the active Run — cannot install
            existing = session.run_snapshot
            if existing is not None and getattr(existing, "run_id", None) == getattr(
                snapshot, "run_id", None
            ):
                return False  # Already frozen for this Run
            session.run_snapshot = snapshot
            return True

    # ── Idle runner management ──────────────────────────────────────

    async def close_idle_runner(self, thread_id: str) -> bool:
        """Close a runner that has been idle past TTL.  Returns True if
        the runner was closed."""
        session = self._sessions.get(thread_id)
        if session is None or session.runner is None:
            return False

        async with session.lifecycle_lock:
            if session.active_run_phase not in (
                RunPhase.COMPLETED,
                RunPhase.CANCELLED,
                RunPhase.FAILED,
                RunPhase.DORMANT,
            ):
                return False  # Still active, don't close

            elapsed = time.monotonic() - session.last_activity
            if elapsed < self._idle_ttl_seconds:
                return False  # Not idle long enough

            session.runner = None
            session.status = "dormant"
            return True

    @property
    def thread_ids(self) -> list[str]:
        """Return all known thread IDs."""
        return list(self._sessions.keys())
