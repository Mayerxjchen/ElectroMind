"""H5 + H6: Protocol v2, EventBroker, WorkspaceLease, and Approval tests."""

from __future__ import annotations

import pytest

from electromind.harness.identity import WorkspaceKey
from electromind.harness.protocol_v2 import (
    VALID_COMMANDS,
    EventBroker,
    EventEnvelope,
    IdempotencyStore,
    ThreadSnapshot,
)
from electromind.harness.state import SessionMode
from electromind.harness.workspace import (
    ApprovalRequest,
    ApprovalStatus,
    LeaseState,
    WorkspaceLease,
    WorkspaceLeaseRegistry,
)

# ============================================================================
# EventEnvelope
# ============================================================================


def test_envelope_factory_auto_generates_id():
    env = EventEnvelope.create("thread-a", "run/started", {"run_id": "run-1"})
    assert env.event_id.startswith("evt-")
    assert env.thread_id == "thread-a"
    assert env.method == "run/started"
    assert env.payload == {"run_id": "run-1"}
    assert env.protocol_version == 2


def test_envelope_is_frozen():
    env = EventEnvelope.create("t", "thread/state")
    with pytest.raises(Exception):
        env.thread_id = "other"  # type: ignore[misc]


def test_envelope_carries_run_id():
    env = EventEnvelope.create("t", "run/started", run_id="run-abc")
    assert env.run_id == "run-abc"


def test_envelope_carries_item_id():
    env = EventEnvelope.create("t", "item/started", item_id="item-001")
    assert env.item_id == "item-001"


# ============================================================================
# Command and event registration
# ============================================================================


def test_valid_commands():
    assert "input/send" in VALID_COMMANDS
    assert "run/cancel" in VALID_COMMANDS
    assert "approval/resolve" in VALID_COMMANDS
    assert "thread/snapshot" in VALID_COMMANDS
    assert "initialize" in VALID_COMMANDS


def test_p3_hpc_submissions_command_and_event_declared():
    """P3: hpc/submissions 查询命令 + 响应事件进入 v2 协议。"""
    from electromind.harness.protocol_v2 import SERVER_EVENTS

    assert "hpc/submissions" in VALID_COMMANDS
    assert "hpc/submissions" in SERVER_EVENTS


# ============================================================================
# Idempotency
# ============================================================================


def test_idempotency_detects_duplicate():
    store = IdempotencyStore()
    assert not store.is_duplicate("req-1")
    store.record("req-1", {"status": "ok"})
    assert store.is_duplicate("req-1")


def test_idempotency_returns_stored_result():
    store = IdempotencyStore()
    store.record("req-2", {"result": 42})
    assert store.get_result("req-2") == {"result": 42}
    assert store.get_result("nonexistent") is None


def test_idempotency_evicts_oldest():
    store = IdempotencyStore()
    store._max_entries = 3
    store.record("a", 1)
    store.record("b", 2)
    store.record("c", 3)
    store.record("d", 4)  # Evicts "a"
    assert not store.is_duplicate("a")  # Evicted
    assert store.is_duplicate("d")


# ============================================================================
# EventBroker — seq and routing
# ============================================================================


def test_broker_next_seq_monotonic_per_thread():
    broker = EventBroker()
    for i in range(5):
        assert broker.next_seq("thread-a") == i

    # Thread B has independent sequence
    assert broker.next_seq("thread-b") == 0
    assert broker.next_seq("thread-a") == 5


def test_broker_emit_fills_seq():
    broker = EventBroker()
    env = EventEnvelope.create("t", "run/started")
    result = broker.emit(env)
    assert result.seq == 0

    env2 = EventEnvelope.create("t", "run/completed")
    result2 = broker.emit(env2)
    assert result2.seq == 1


def test_broker_emit_preserves_existing_seq():
    broker = EventBroker()
    env = EventEnvelope.create("t", "run/started", seq=42)
    result = broker.emit(env)
    assert result.seq == 42  # Unchanged
    # An explicit seq advances the counter: the next AUTO event must be
    # strictly greater, never a stale 0 (monotonic sequence).
    assert broker.get_last_seq("t") == 42
    env2 = EventEnvelope.create("t", "run/completed")
    result2 = broker.emit(env2)
    assert result2.seq == 43


def test_broker_renumbers_stale_explicit_seq():
    """A replay/late explicit seq <= current is RENUMBERED, never injected
    into the event stream as a duplicate (regression: duplicate seqs were
    appended as-is, breaking monotonicity)."""
    broker = EventBroker()
    broker.emit(EventEnvelope.create("t", "a"))  # auto → seq 0
    broker.emit(EventEnvelope.create("t", "b"))  # auto → seq 1
    # Stale explicit seq=1 (<= current=1) → renumbered to 2
    stale = broker.emit(EventEnvelope.create("t", "replay", seq=1))
    assert stale.seq == 2
    # Sequence stays strictly monotonic afterwards
    nxt = broker.emit(EventEnvelope.create("t", "c"))
    assert nxt.seq == 3
    seqs = [e.seq for e in broker.get_events_since("t", after_seq=-1)]
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs))  # strictly inc


def test_broker_get_events_since():
    broker = EventBroker()
    broker.emit(EventEnvelope.create("t", "a"))
    broker.emit(EventEnvelope.create("t", "b"))
    broker.emit(EventEnvelope.create("t", "c"))

    since = broker.get_events_since("t", after_seq=0)
    assert len(since) == 2  # seq 1 and 2
    assert since[0].method == "b"
    assert since[1].method == "c"


def test_broker_buffer_eviction_detected():
    broker = EventBroker()
    broker._max_buffer = 3
    for i in range(5):
        broker.emit(EventEnvelope.create("t", str(i)))
    # Buffer has last 3 events (seq 2, 3, 4)
    since = broker.get_events_since("t", after_seq=0)
    assert len(since) == 0  # Buffer evicted → empty


def test_broker_thread_isolation():
    broker = EventBroker()
    broker.emit(EventEnvelope.create("a", "event-a"))
    broker.emit(EventEnvelope.create("b", "event-b"))

    a_events = broker.get_events_since("a", after_seq=-1)
    b_events = broker.get_events_since("b", after_seq=-1)
    assert len(a_events) == 1
    assert len(b_events) == 1
    assert a_events[0].thread_id == "a"
    assert b_events[0].thread_id == "b"


# ============================================================================
# WorkspaceLease
# ============================================================================


def test_lease_acquire_write_when_free():
    key = WorkspaceKey("local:/tmp/a", "/tmp/a")
    lease = WorkspaceLease(key=key)
    assert lease.acquire_write("run-1", "thread-1")
    assert lease.state == LeaseState.WRITE_EXCLUSIVE
    assert lease.holder_run_id == "run-1"


def test_lease_acquire_write_when_held_fails():
    key = WorkspaceKey("local:/tmp/a", "/tmp/a")
    lease = WorkspaceLease(key=key)
    assert lease.acquire_write("run-1", "thread-1")
    assert not lease.acquire_write("run-2", "thread-2")


def test_lease_release():
    key = WorkspaceKey("local:/tmp/a", "/tmp/a")
    lease = WorkspaceLease(key=key)
    lease.acquire_write("run-1", "thread-1")
    lease.release()
    assert lease.state == LeaseState.FREE
    assert lease.acquire_write("run-2", "thread-2")


# ============================================================================
# WorkspaceLeaseRegistry
# ============================================================================


def test_registry_ask_mode_always_allowed():
    reg = WorkspaceLeaseRegistry()
    key = WorkspaceKey("local:/tmp/p", "/tmp/p")
    # Ask mode — no write lease needed
    assert reg.acquire(key, "run-1", "t-1", SessionMode.ASK)
    # Can have multiple ask Runs on same workspace
    assert reg.acquire(key, "run-2", "t-2", SessionMode.ASK)
    assert reg.acquire(key, "run-3", "t-1", SessionMode.PLAN)


def test_registry_run_mode_exclusive():
    reg = WorkspaceLeaseRegistry()
    key = WorkspaceKey("local:/tmp/p", "/tmp/p")
    assert reg.acquire(key, "run-w", "t-1", SessionMode.RUN)
    # Second write run on same workspace → conflict
    assert not reg.acquire(key, "run-w2", "t-2", SessionMode.RUN)


def test_registry_release_allows_next():
    reg = WorkspaceLeaseRegistry()
    key = WorkspaceKey("local:/tmp/p", "/tmp/p")
    reg.acquire(key, "run-w", "t-1", SessionMode.RUN)
    reg.release(key, "run-w")
    # Now free
    assert reg.acquire(key, "run-w2", "t-2", SessionMode.RUN)


def test_registry_release_wrong_run_fails():
    reg = WorkspaceLeaseRegistry()
    key = WorkspaceKey("local:/tmp/p", "/tmp/p")
    reg.acquire(key, "run-a", "t-1", SessionMode.RUN)
    assert not reg.release(key, "run-b")  # Wrong run
    assert not reg.is_free(key)


def test_registry_different_workspaces_independent():
    reg = WorkspaceLeaseRegistry()
    k1 = WorkspaceKey("local:/tmp/a", "/tmp/a")
    k2 = WorkspaceKey("local:/tmp/b", "/tmp/b")
    assert reg.acquire(k1, "run-a1", "t-1", SessionMode.RUN)
    assert reg.acquire(k2, "run-b1", "t-2", SessionMode.RUN)  # Different workspace


def test_registry_get_holder():
    reg = WorkspaceLeaseRegistry()
    key = WorkspaceKey("ssh:host1:/remote", "/remote")
    reg.acquire(key, "run-ssh", "t-3", SessionMode.RUN)
    holder = reg.get_holder(key)
    assert holder == ("run-ssh", "t-3")


# ============================================================================
# ApprovalRequest — scoping
# ============================================================================


def test_approval_default_pending():
    apr = ApprovalRequest(
        approval_id="apr-001",
        thread_id="t-1",
        run_id="run-1",
        tool_call_id="tc-1",
    )
    assert apr.status == ApprovalStatus.PENDING
    assert apr.is_resolvable()


def test_approval_approve():
    apr = ApprovalRequest("apr-1", "t", "r", "tc")
    assert apr.approve()
    assert apr.status == ApprovalStatus.APPROVED
    assert not apr.is_resolvable()
    assert not apr.approve()  # Already resolved


def test_approval_deny():
    apr = ApprovalRequest("apr-1", "t", "r", "tc")
    assert apr.deny("unsafe operation")
    assert apr.status == ApprovalStatus.DENIED


def test_approval_expire():
    apr = ApprovalRequest("apr-1", "t", "r", "tc")
    assert apr.expire()
    assert apr.status == ApprovalStatus.EXPIRED


def test_approval_cancel():
    apr = ApprovalRequest("apr-1", "t", "r", "tc")
    assert apr.cancel()
    assert apr.status == ApprovalStatus.CANCELLED


def test_approval_validate_context_exact_match():
    apr = ApprovalRequest("apr-1", "thread-a", "run-1", "tc-1")
    assert apr.validate_context("thread-a", "run-1", "tc-1")
    assert apr.validate_context("thread-a", "run-1")  # tool_call_id optional


def test_approval_validate_context_wrong_thread():
    apr = ApprovalRequest("apr-1", "thread-a", "run-1", "tc-1")
    assert not apr.validate_context("thread-b", "run-1", "tc-1")


def test_approval_validate_context_wrong_run():
    apr = ApprovalRequest("apr-1", "thread-a", "run-1", "tc-1")
    assert not apr.validate_context("thread-a", "run-2", "tc-1")


def test_approval_validate_context_wrong_tool_call():
    apr = ApprovalRequest("apr-1", "thread-a", "run-1", "tc-1")
    assert not apr.validate_context("thread-a", "run-1", "tc-2")


def test_approval_cannot_approve_twice():
    apr = ApprovalRequest("apr-1", "t", "r", "tc")
    apr.approve()
    assert not apr.approve()


def test_approval_cannot_deny_after_approve():
    apr = ApprovalRequest("apr-1", "t", "r", "tc")
    apr.approve()
    assert not apr.deny()


def test_approval_different_runs_independent():
    """Approval on run-1 does not affect run-2."""
    apr1 = ApprovalRequest("apr-1", "t", "run-1", "tc")
    apr2 = ApprovalRequest("apr-2", "t", "run-2", "tc")
    assert apr1.approve()
    assert apr2.is_resolvable()  # Still pending, different run
    assert not apr1.validate_context("t", "run-2")  # apr1 is for run-1
    assert apr2.validate_context("t", "run-2")


# ============================================================================
# ThreadSnapshot
# ============================================================================


def test_thread_snapshot_defaults():
    snap = ThreadSnapshot(thread_id="t")
    assert snap.thread_id == "t"
    assert not snap.exists
    assert snap.is_full_snapshot
    assert snap.last_seq == 0
