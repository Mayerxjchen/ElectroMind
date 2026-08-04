"""H2: Reliable Inbound tests.

Verify InputMessage identity, InputQueue FIFO/deferred semantics,
receipt generation, empty rejection, and the 20-message no-loss stress test.
"""

from __future__ import annotations

import pytest

from electromind.harness.inbound import (
    InputDelivery,
    InputMessage,
    InputQueue,
    InputReceipt,
    accepted_receipt,
    applied_receipt,
    deferred_receipt,
    immediate_pending_receipt,
    queued_receipt,
    rejected_receipt,
)
from electromind.harness.state import InputDeliveryState, SessionMode

# ============================================================================
# InputMessage — creation and identity
# ============================================================================


def test_input_message_create_generates_unique_id():
    m1 = InputMessage.create("thread-a", "hello")
    m2 = InputMessage.create("thread-a", "world")
    assert m1.message_id != m2.message_id
    assert m1.message_id.startswith("msg-")
    assert len(m1.message_id) == 4 + 12


def test_input_message_fields():
    msg = InputMessage.create(
        "thread-1",
        "compute the energy",
        delivery=InputDelivery.IMMEDIATE,
        target_run_id="run-abc",
    )
    assert msg.thread_id == "thread-1"
    assert msg.text == "compute the energy"
    assert msg.delivery == InputDelivery.IMMEDIATE
    assert msg.target_run_id == "run-abc"
    assert msg.created_at  # non-empty ISO timestamp
    assert not msg.is_empty


def test_input_message_is_frozen():
    msg = InputMessage.create("thread-x", "test")
    with pytest.raises(Exception):
        msg.text = "modified"  # type: ignore[misc]


def test_input_message_is_empty():
    assert InputMessage.create("t", "").is_empty
    assert InputMessage.create("t", "   ").is_empty
    assert InputMessage.create("t", "\n\t").is_empty


def test_input_message_with_requested_options():
    msg = InputMessage.create(
        "thread-1",
        "run simulation",
        delivery=InputDelivery.ENQUEUE,
        requested_mode=SessionMode.RUN,
        requested_model="gpt-5",
        requested_max_iterations=50,
    )
    assert msg.requested_mode == SessionMode.RUN
    assert msg.requested_model == "gpt-5"
    assert msg.requested_max_iterations == 50


# ============================================================================
# InputDelivery modes
# ============================================================================


def test_input_delivery_values():
    assert InputDelivery.AUTO == "auto"
    assert InputDelivery.IMMEDIATE == "immediate"
    assert InputDelivery.ENQUEUE == "enqueue"


def test_input_delivery_all_modes():
    """Every delivery mode must be creatable."""
    for mode in InputDelivery:
        msg = InputMessage.create("t", "test", delivery=mode)
        assert msg.delivery == mode


# ============================================================================
# InputReceipt — ACK
# ============================================================================


def test_accepted_receipt():
    msg = InputMessage.create("thread-x", "test")
    receipt = accepted_receipt(msg)
    assert receipt.message_id == msg.message_id
    assert receipt.thread_id == "thread-x"
    assert receipt.state == InputDeliveryState.ACCEPTED


def test_immediate_pending_receipt():
    msg = InputMessage.create("t", "test", target_run_id="run-1")
    receipt = immediate_pending_receipt(msg)
    assert receipt.state == InputDeliveryState.IMMEDIATE_PENDING
    assert receipt.target_run_id == "run-1"


def test_applied_receipt():
    msg = InputMessage.create("t", "test")
    receipt = applied_receipt(msg)
    assert receipt.state == InputDeliveryState.APPLIED


def test_deferred_receipt():
    msg = InputMessage.create("t", "test")
    receipt = deferred_receipt(msg, "Run completed before checkpoint")
    assert receipt.state == InputDeliveryState.DEFERRED
    assert "checkpoint" in receipt.detail


def test_queued_receipt():
    msg = InputMessage.create("t", "test")
    receipt = queued_receipt(msg)
    assert receipt.state == InputDeliveryState.QUEUED


def test_rejected_receipt():
    msg = InputMessage.create("t", "")
    receipt = rejected_receipt(msg, "Empty input")
    assert receipt.state == InputDeliveryState.REJECTED
    assert receipt.detail == "Empty input"


def test_receipt_is_frozen():
    receipt = InputReceipt("msg-1", "thread-1", InputDeliveryState.ACCEPTED)
    with pytest.raises(Exception):
        receipt.state = InputDeliveryState.APPLIED  # type: ignore[misc]


# ============================================================================
# InputQueue — FIFO ordering
# ============================================================================


def test_queue_empty_by_default():
    q = InputQueue()
    assert len(q) == 0
    assert not q
    assert q.dequeue() is None
    assert q.peek() is None


def test_queue_fifo_order():
    q = InputQueue()
    m1 = InputMessage.create("t", "first")
    m2 = InputMessage.create("t", "second")
    m3 = InputMessage.create("t", "third")

    q.enqueue(m1)
    q.enqueue(m2)
    q.enqueue(m3)

    assert len(q) == 3
    assert q.dequeue() is m1
    assert q.dequeue() is m2
    assert q.dequeue() is m3
    assert len(q) == 0


def test_queue_enqueue_head():
    """Deferred immediate inputs go at the head."""
    q = InputQueue()
    m1 = InputMessage.create("t", "regular-1")
    m2 = InputMessage.create("t", "regular-2")
    deferred = InputMessage.create("t", "deferred-immediate")

    q.enqueue(m1)
    q.enqueue(m2)
    q.enqueue_head(deferred)  # Deferred goes to front

    assert q.dequeue() is deferred  # Head first
    assert q.dequeue() is m1
    assert q.dequeue() is m2


def test_queue_peek_does_not_remove():
    q = InputQueue()
    m = InputMessage.create("t", "test")
    q.enqueue(m)
    assert q.peek() is m
    assert q.peek() is m  # Still there
    assert len(q) == 1


def test_queue_all_returns_ordered_copy():
    q = InputQueue()
    m1 = InputMessage.create("t", "a")
    m2 = InputMessage.create("t", "b")
    q.enqueue(m1)
    q.enqueue(m2)
    assert q.all() == [m1, m2]
    assert len(q) == 2  # Not consumed


def test_queue_clear():
    q = InputQueue()
    q.enqueue(InputMessage.create("t", "a"))
    q.enqueue(InputMessage.create("t", "b"))
    q.clear()
    assert len(q) == 0


# ============================================================================
# Input lifecycle scenario: immediate → deferred → enqueue_head
# ============================================================================


def test_immediate_deferred_becomes_head_of_queue():
    """Simulate: user sends immediate input, Run ends before checkpoint,
    input is deferred and placed at head of queue for next Run."""
    q = InputQueue()
    q.enqueue(InputMessage.create("t", "queued-msg-1"))
    q.enqueue(InputMessage.create("t", "queued-msg-2"))

    # User sends immediate input mid-run
    immediate = InputMessage.create(
        "t",
        "stop and check this",
        delivery=InputDelivery.IMMEDIATE,
    )

    # Run ends before checkpoint → deferred
    receipt = deferred_receipt(immediate)
    assert receipt.state == InputDeliveryState.DEFERRED

    # Deferred input goes to head of queue
    q.enqueue_head(immediate)

    # Next Run: deferred is processed first
    assert q.dequeue() is immediate
    assert q.dequeue().text == "queued-msg-1"  # type: ignore[union-attr]
    assert q.dequeue().text == "queued-msg-2"  # type: ignore[union-attr]


# ============================================================================
# 20-message no-loss stress test
# ============================================================================


def test_twenty_inputs_zero_loss():
    """Send 20 inputs through the queue; every one must be accounted for."""
    q = InputQueue()
    messages = [InputMessage.create("t", f"msg-{i}") for i in range(20)]

    # Simulate mix: 15 enqueued normally, 5 deferred to head
    for i, msg in enumerate(messages):
        if i < 15:
            q.enqueue(msg)
        else:
            q.enqueue_head(msg)

    assert len(q) == 20

    received: list[str] = []
    while msg := q.dequeue():
        received.append(msg.text)

    assert len(received) == 20, f"lost {20 - len(received)} messages"
    # Deferred (indices 15-19) should be at the front, reversed
    for i in range(19, 14, -1):
        assert received[19 - i] == f"msg-{i}"
    # Then the FIFO messages (0-14)
    for i in range(15):
        assert received[5 + i] == f"msg-{i}"


# ============================================================================
# Empty input → rejected
# ============================================================================


def test_empty_input_is_rejected_not_queued():
    """Empty inputs must be explicitly rejected, not silently dropped."""
    msg = InputMessage.create("t", "")
    assert msg.is_empty

    receipt = rejected_receipt(msg, "Empty input text")
    assert receipt.state == InputDeliveryState.REJECTED

    # Should NOT be enqueued
    q = InputQueue()
    if not msg.is_empty:
        q.enqueue(msg)
    assert len(q) == 0


def test_whitespace_input_is_rejected():
    msg = InputMessage.create("t", "   \n  ")
    assert msg.is_empty
    receipt = rejected_receipt(msg, "Whitespace-only input")
    assert receipt.state == InputDeliveryState.REJECTED


# ============================================================================
# InputDeliveryState observable at every stage
# ============================================================================


def test_input_state_is_observable_at_every_stage():
    """Every input must produce an observable receipt at each state transition."""
    msg = InputMessage.create("thread-1", "do something")

    # Stage 1: Accepted
    r1 = accepted_receipt(msg)
    assert r1.state == InputDeliveryState.ACCEPTED

    # Stage 2a: Immediate → pending
    r2 = immediate_pending_receipt(msg)
    assert r2.state == InputDeliveryState.IMMEDIATE_PENDING

    # Stage 2b: Enqueue → queued
    r3 = queued_receipt(msg)
    assert r3.state == InputDeliveryState.QUEUED

    # Stage 3: Applied
    r4 = applied_receipt(msg)
    assert r4.state == InputDeliveryState.APPLIED

    # All receipts carry the same message_id
    for r in (r1, r2, r3, r4):
        assert r.message_id == msg.message_id
