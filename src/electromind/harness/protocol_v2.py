"""Protocol v2 — EventEnvelope, EventBroker, idempotency, and snapshot recovery.

Every event carries thread_id + seq.  Run events carry run_id.  Item events
carry item_id.  Mutation commands carry request_id for idempotent replay.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .identity import new_event_id

# ---------------------------------------------------------------------------
# EventEnvelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """Every event in the harness is wrapped in this envelope.

    ``protocol_version`` is always 2.
    ``seq`` is per-thread and monotonically increasing.
    ``run_id`` is present for Run-scoped events.
    ``item_id`` is present for Item-scoped events.
    """

    protocol_version: int = 2

    event_id: str = ""
    thread_id: str = ""
    run_id: str | None = None
    item_id: str | None = None
    seq: int = 0
    timestamp: str = ""

    method: str = ""
    payload: dict = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        thread_id: str,
        method: str,
        payload: dict | None = None,
        *,
        seq: int = 0,
        run_id: str | None = None,
        item_id: str | None = None,
    ) -> EventEnvelope:
        """Factory: auto-generates event_id and ISO timestamp."""
        from datetime import datetime, timezone

        return cls(
            event_id=new_event_id(),
            thread_id=thread_id,
            run_id=run_id,
            item_id=item_id,
            seq=seq,
            timestamp=datetime.now(timezone.utc).isoformat(),
            method=method,
            payload=payload or {},
        )


# ============================================================================
# Client commands (what the client sends)
# ============================================================================

VALID_COMMANDS = frozenset(
    {
        "initialize",
        "thread/snapshot",
        "input/send",
        "run/cancel",
        "approval/resolve",
        "thread/archive",
        # G1: Plan / Artifact 领域状态命令（CLI 与 Desktop 共用）
        "plan/state",
        "plan/propose",
        "plan/approve",
        "plan/revise",
        "plan/cancel",
        "plan/update-step",
        "artifact/state",
        "artifact/register",
        "artifact/accept",
        "artifact/reject",
        "artifact/complete",
        "artifact/validate",
    }
)


# ============================================================================
# Server events (what the server emits)
# ============================================================================

SERVER_EVENTS = frozenset(
    {
        "thread/state",
        "run/started",
        "run/state",
        "run/completed",
        "input/state",
        "item/started",
        "item/delta",
        "item/completed",
        "item/failed",
        "approval/requested",
        "approval/resolved",
        "external_task/state",
        # G1: Plan / Artifact 领域状态事件（全量状态，CLI 与 Desktop 共用）
        "plan/state",
        "artifact/state",
    }
)


# ============================================================================
# Idempotency
# ============================================================================


@dataclass(slots=True)
class IdempotencyStore:
    """Tracks which request_ids have been processed, preventing duplicate
    side effects when clients retry the same command."""

    _completed: dict[str, object] = field(default_factory=dict)
    _max_entries: int = 1000

    def is_duplicate(self, request_id: str) -> bool:
        """True if this request_id has already been processed."""
        return request_id in self._completed

    def record(self, request_id: str, result: object) -> None:
        """Record the result of processing a request_id.

        Returns the previously-stored result if this is a duplicate.
        """
        if len(self._completed) >= self._max_entries:
            # Evict oldest entries (simple FIFO via dict ordering)
            excess = len(self._completed) - self._max_entries + 1
            for key in list(self._completed.keys())[:excess]:
                del self._completed[key]
        self._completed[request_id] = result

    def get_result(self, request_id: str) -> object | None:
        """Return the stored result for a completed request_id."""
        return self._completed.get(request_id)


# ============================================================================
# Snapshot / recovery
# ============================================================================


@dataclass(slots=True)
class ThreadSnapshot:
    """A point-in-time snapshot of a Thread's state for client recovery.

    Returned by ``thread/snapshot`` commands.  The client can use
    ``after_seq`` to request only events since a given sequence number.
    """

    thread_id: str
    exists: bool = False
    active_run_id: str | None = None
    active_run_phase: str = ""
    status: str = "dormant"
    queued_input_count: int = 0
    pending_approval_count: int = 0
    last_seq: int = 0
    events_since: list[EventEnvelope] = field(default_factory=list)
    is_full_snapshot: bool = True


# ============================================================================
# EventBroker
# ============================================================================


@dataclass(slots=True)
class EventBroker:
    """Routes events with per-thread sequencing and snapshot support.

    Events are buffered per-thread for snapshot recovery.  The broker
    does NOT understand event payload semantics — it only routes by
    thread_id and maintains seq ordering.
    """

    _events: dict[str, list[EventEnvelope]] = field(default_factory=dict)
    _seq: dict[str, int] = field(default_factory=dict)
    _max_buffer: int = 500

    def next_seq(self, thread_id: str) -> int:
        """Return and increment the per-thread event seq."""
        seq = self._seq.get(thread_id, 0)
        self._seq[thread_id] = seq + 1
        return seq

    def emit(self, envelope: EventEnvelope) -> EventEnvelope:
        """Emit an event with the next sequence number.

        Returns the envelope with seq filled in (for the caller to forward).
        """
        # Fill in seq if not already set
        if envelope.seq == 0:
            seq = self.next_seq(envelope.thread_id)
            # Frozen dataclass — create new with seq
            envelope = EventEnvelope(
                protocol_version=envelope.protocol_version,
                event_id=envelope.event_id,
                thread_id=envelope.thread_id,
                run_id=envelope.run_id,
                item_id=envelope.item_id,
                seq=seq,
                timestamp=envelope.timestamp,
                method=envelope.method,
                payload=envelope.payload,
            )
        else:
            # Explicit seq: advance the counter so subsequent AUTO events
            # stay strictly monotonic (a client replaying an explicit seq
            # must not see later auto events as stale/out-of-order).
            current = self._seq.get(envelope.thread_id, 0)
            if envelope.seq + 1 > current:
                self._seq[envelope.thread_id] = envelope.seq + 1
            else:
                # Stale/replayed explicit seq (<= current): renumber so a
                # duplicate seq NEVER enters the normal event stream.
                seq = self.next_seq(envelope.thread_id)
                envelope = EventEnvelope(
                    protocol_version=envelope.protocol_version,
                    event_id=envelope.event_id,
                    thread_id=envelope.thread_id,
                    run_id=envelope.run_id,
                    item_id=envelope.item_id,
                    seq=seq,
                    timestamp=envelope.timestamp,
                    method=envelope.method,
                    payload=envelope.payload,
                )

        # Buffer for snapshot recovery
        if envelope.thread_id not in self._events:
            self._events[envelope.thread_id] = []
        buf = self._events[envelope.thread_id]
        buf.append(envelope)
        if len(buf) > self._max_buffer:
            buf.pop(0)  # Drop oldest

        return envelope

    def get_events_since(self, thread_id: str, after_seq: int) -> list[EventEnvelope]:
        """Return events with seq > after_seq, or empty list if buffer
        was evicted."""
        buf = self._events.get(thread_id, [])
        if not buf:
            return []
        # Check if after_seq is still in buffer
        if after_seq >= 0 and buf and after_seq < buf[0].seq:
            # Buffer was evicted — return empty (caller must do full snapshot)
            return []
        return [e for e in buf if e.seq > after_seq]

    def get_last_seq(self, thread_id: str) -> int:
        """Return the last emitted seq for a thread, or -1 if no events."""
        return self._seq.get(thread_id, 0) - 1
