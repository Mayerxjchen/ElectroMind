"""Reliable inbound — InputMessage, delivery modes, and InputQueue.

Every user input gets a ``message_id``, is placed into a precisely-defined
delivery state, and is tracked until it reaches a terminal state
(``applied`` or ``rejected``).  No silent loss.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum

from .identity import new_message_id
from .state import InputDeliveryState, SessionMode

# ---------------------------------------------------------------------------
# Delivery mode
# ---------------------------------------------------------------------------


class InputDelivery(StrEnum):
    """How the harness should deliver this input to the Run.

    ``auto``
        Thread is idle → start a new Run.  Thread is running → treat as
        ``immediate``.  This is the Desktop default.
    ``immediate``
        Insert into the active Run at the next safe checkpoint.  If the
        Run ends before the checkpoint, the input is ``deferred`` and
        placed at the head of the queue for the next Run.
    ``enqueue``
        Wait for the current Run to end, then start a new Run FIFO.
    """

    AUTO = "auto"
    IMMEDIATE = "immediate"
    ENQUEUE = "enqueue"


# ---------------------------------------------------------------------------
# InputMessage
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InputMessage:
    """A user input with full identity and delivery semantics.

    Every field is immutable.  The ``message_id`` is generated at creation
    time and is guaranteed unique.
    """

    message_id: str
    thread_id: str
    target_run_id: str | None
    text: str
    delivery: InputDelivery
    created_at: str  # ISO 8601

    # Optional: requested settings for the NEXT run (only meaningful for
    # enqueue inputs; ignored for immediate).
    requested_mode: SessionMode | None = None
    requested_model: str | None = None
    requested_max_iterations: int | None = None

    @classmethod
    def create(
        cls,
        thread_id: str,
        text: str,
        *,
        target_run_id: str | None = None,
        delivery: InputDelivery = InputDelivery.AUTO,
        created_at: str = "",
        requested_mode: SessionMode | None = None,
        requested_model: str | None = None,
        requested_max_iterations: int | None = None,
    ) -> InputMessage:
        """Factory: generates a unique message_id automatically."""
        from datetime import datetime, timezone

        return cls(
            message_id=new_message_id(),
            thread_id=thread_id,
            target_run_id=target_run_id,
            text=text,
            delivery=delivery,
            created_at=created_at or datetime.now(timezone.utc).isoformat(),
            requested_mode=requested_mode,
            requested_model=requested_model,
            requested_max_iterations=requested_max_iterations,
        )

    @property
    def is_empty(self) -> bool:
        return not self.text or not self.text.strip()


# ---------------------------------------------------------------------------
# InputReceipt — ACK returned to the client
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InputReceipt:
    """Acknowledgement sent to the client when an input is accepted."""

    message_id: str
    thread_id: str
    state: InputDeliveryState
    target_run_id: str | None = None
    detail: str = ""


# ---------------------------------------------------------------------------
# InputQueue — FIFO with deferred-at-head semantics
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class InputQueue:
    """Per-Thread input queue.

    Maintains FIFO ordering for enqueued inputs.  When an immediate input
    is deferred (the Run ended before it could be applied), it is placed
    at the HEAD of the queue for the next Run — ensuring the user's
    mid-run message becomes the first thing the next Run sees.

    Thread-safe: all mutations are synchronous (no asyncio locks needed
    for this pure-data structure).
    """

    _items: deque[InputMessage] = field(default_factory=deque)

    def enqueue(self, message: InputMessage) -> None:
        """Append to the tail (normal FIFO enqueue)."""
        self._items.append(message)

    def enqueue_head(self, message: InputMessage) -> None:
        """Insert at the head (used for deferred immediate inputs)."""
        self._items.appendleft(message)

    def dequeue(self) -> InputMessage | None:
        """Remove and return the head item, or None if empty."""
        try:
            return self._items.popleft()
        except IndexError:
            return None

    def peek(self) -> InputMessage | None:
        """Return the head item without removing it."""
        try:
            return self._items[0]
        except IndexError:
            return None

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return bool(self._items)

    def clear(self) -> None:
        self._items.clear()

    def all(self) -> list[InputMessage]:
        """Return all queued items in FIFO order (without consuming)."""
        return list(self._items)


# ---------------------------------------------------------------------------
# Input lifecycle helpers
# ---------------------------------------------------------------------------


def accepted_receipt(message: InputMessage) -> InputReceipt:
    """Return the initial receipt after accepting an input."""
    return InputReceipt(
        message_id=message.message_id,
        thread_id=message.thread_id,
        state=InputDeliveryState.ACCEPTED,
        target_run_id=message.target_run_id,
    )


def immediate_pending_receipt(message: InputMessage) -> InputReceipt:
    """Return the receipt when an immediate input is waiting for a checkpoint."""
    return InputReceipt(
        message_id=message.message_id,
        thread_id=message.thread_id,
        state=InputDeliveryState.IMMEDIATE_PENDING,
        target_run_id=message.target_run_id,
    )


def applied_receipt(message: InputMessage) -> InputReceipt:
    """Return the receipt when an input has been inserted into the Run."""
    return InputReceipt(
        message_id=message.message_id,
        thread_id=message.thread_id,
        state=InputDeliveryState.APPLIED,
    )


def deferred_receipt(message: InputMessage, reason: str = "") -> InputReceipt:
    """Return the receipt when an immediate input was deferred."""
    return InputReceipt(
        message_id=message.message_id,
        thread_id=message.thread_id,
        state=InputDeliveryState.DEFERRED,
        detail=reason or "Run ended before input could be applied",
    )


def queued_receipt(message: InputMessage) -> InputReceipt:
    """Return the receipt when an input is queued for the next Run."""
    return InputReceipt(
        message_id=message.message_id,
        thread_id=message.thread_id,
        state=InputDeliveryState.QUEUED,
    )


def rejected_receipt(message: InputMessage, reason: str) -> InputReceipt:
    """Return the receipt when an input is rejected."""
    return InputReceipt(
        message_id=message.message_id,
        thread_id=message.thread_id,
        state=InputDeliveryState.REJECTED,
        detail=reason,
    )
