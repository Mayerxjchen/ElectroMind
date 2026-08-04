"""H1: Identity and state contract tests.

Verify that every ID type validates its input, every factory produces
valid IDs, RunSnapshot is truly frozen, and state transitions are correct.
"""

from __future__ import annotations

import pytest

from electromind.harness.identity import (
    RunSnapshot,
    WorkspaceKey,
    new_approval_id,
    new_event_id,
    new_item_id,
    new_message_id,
    new_request_id,
    new_run_id,
    validate_approval_id,
    validate_event_id,
    validate_item_id,
    validate_message_id,
    validate_request_id,
    validate_run_id,
    validate_thread_id,
)
from electromind.harness.state import (
    ExecutionTargetSnapshot,
    InputDeliveryState,
    PermissionPolicySnapshot,
    RunPhase,
    SessionMode,
    allowed_input_transitions,
    allowed_run_transitions,
    is_terminal_run_phase,
)

# ============================================================================
# ID validation — non-empty
# ============================================================================


@pytest.mark.parametrize(
    "validate_fn,label",
    [
        (validate_thread_id, "thread_id"),
        (validate_run_id, "run_id"),
        (validate_message_id, "message_id"),
        (validate_item_id, "item_id"),
        (validate_event_id, "event_id"),
        (validate_approval_id, "approval_id"),
        (validate_request_id, "request_id"),
    ],
)
def test_validate_empty_raises(validate_fn, label):
    with pytest.raises(ValueError, match="must not be empty"):
        validate_fn("")
    with pytest.raises(ValueError, match="must not be empty"):
        validate_fn("   ")


# ============================================================================
# ID validation — prefix
# ============================================================================


@pytest.mark.parametrize(
    "validate_fn,label,prefix",
    [
        (validate_run_id, "run_id", "run-"),
        (validate_message_id, "message_id", "msg-"),
        (validate_item_id, "item_id", "item-"),
        (validate_event_id, "event_id", "evt-"),
        (validate_approval_id, "approval_id", "apr-"),
        (validate_request_id, "request_id", "req-"),
    ],
)
def test_validate_wrong_prefix_raises(validate_fn, label, prefix):
    with pytest.raises(ValueError, match=f"must start with {prefix!r}"):
        validate_fn("wrong-prefix-123")


def test_thread_id_has_no_prefix_requirement():
    """ThreadId only requires non-empty — no prefix check."""
    tid = validate_thread_id("my-thread-001")
    assert isinstance(tid, str)
    assert tid == "my-thread-001"


def test_run_id_accepts_valid():
    rid = validate_run_id("run-abc123")
    assert rid == "run-abc123"
    assert rid.startswith("run-")


def test_message_id_accepts_valid():
    mid = validate_message_id("msg-xyz789")
    assert mid == "msg-xyz789"


def test_item_id_accepts_valid():
    iid = validate_item_id("item-foo001")
    assert iid == "item-foo001"


def test_event_id_accepts_valid():
    eid = validate_event_id("evt-bar001")
    assert eid == "evt-bar001"


def test_approval_id_accepts_valid():
    aid = validate_approval_id("apr-baz001")
    assert aid == "apr-baz001"


def test_request_id_accepts_valid():
    rid = validate_request_id("req-qux001")
    assert rid == "req-qux001"


# ============================================================================
# Factory functions
# ============================================================================


def test_new_run_id_has_correct_prefix_and_length():
    rid = new_run_id()
    assert rid.startswith("run-")
    assert len(rid) == 4 + 12  # "run-" + 12 hex chars


def test_new_message_id_has_correct_prefix():
    assert new_message_id().startswith("msg-")


def test_new_item_id_has_correct_prefix():
    assert new_item_id().startswith("item-")


def test_new_event_id_has_correct_prefix():
    assert new_event_id().startswith("evt-")


def test_new_approval_id_has_correct_prefix():
    assert new_approval_id().startswith("apr-")


def test_new_request_id_has_correct_prefix():
    assert new_request_id().startswith("req-")


def test_factory_ids_are_unique():
    """Successive calls must produce distinct IDs."""
    ids = {new_run_id() for _ in range(100)}
    assert len(ids) == 100, "factory must produce unique IDs"


def test_factory_ids_validate():
    """Every factory-produced ID must pass its own validator."""
    validate_run_id(new_run_id())
    validate_message_id(new_message_id())
    validate_item_id(new_item_id())
    validate_event_id(new_event_id())
    validate_approval_id(new_approval_id())
    validate_request_id(new_request_id())


# ============================================================================
# RunSnapshot — frozen and complete
# ============================================================================


def _make_target():
    return ExecutionTargetSnapshot(
        target_id="local-main",
        kind="local",
        workdir="/tmp/test",
    )


def _make_policy():
    return PermissionPolicySnapshot()


def _make_snapshot(**overrides) -> RunSnapshot:
    kwargs = dict(
        run_id="run-test001",
        thread_id="thread-test",
        input_message_id="msg-input01",
        session_mode=SessionMode.ASK,
        model="test-model",
        max_iterations=10,
        execution_target=_make_target(),
        permission_policy=_make_policy(),
        project_path="/tmp/test-project",
        system_prompt_digest="sha256:abc123",
        skill_set_digest="sha256:def456",
        tool_set_digest="sha256:ghi789",
        created_at="2026-07-31T00:00:00Z",
    )
    kwargs.update(overrides)
    return RunSnapshot(**kwargs)


def test_run_snapshot_is_frozen():
    snap = _make_snapshot()
    with pytest.raises(Exception):  # FrozenInstanceError or similar
        snap.model = "other"  # type: ignore[misc]


def test_run_snapshot_fields_match_spec():
    """Every field listed in the design spec must exist."""
    snap = _make_snapshot()
    assert snap.session_mode in SessionMode
    assert isinstance(snap.max_iterations, int) and snap.max_iterations > 0
    assert isinstance(snap.execution_target, ExecutionTargetSnapshot)
    assert isinstance(snap.permission_policy, PermissionPolicySnapshot)
    assert snap.project_path != ""
    assert snap.system_prompt_digest != ""
    assert snap.skill_set_digest != ""
    assert snap.tool_set_digest != ""
    assert snap.created_at != ""


def test_run_snapshot_session_mode_must_be_valid():
    """All three session modes must be acceptable."""
    for mode in SessionMode:
        snap = _make_snapshot(session_mode=mode)
        assert snap.session_mode == mode


# ============================================================================
# ExecutionTargetSnapshot
# ============================================================================


def test_execution_target_workspace_key():
    target = ExecutionTargetSnapshot(
        target_id="docker-abc",
        kind="docker",
        workdir="/workspace",
        profile_id="default",
    )
    key = target.workspace_key()
    assert "docker" in key
    assert "docker-abc" in key
    assert "/workspace" in key


def test_execution_target_local():
    target = ExecutionTargetSnapshot(
        target_id="local-1", kind="local", workdir="/home/user/project"
    )
    assert target.kind == "local"
    assert target.workspace_key() == "local:local-1:/home/user/project"


def test_execution_target_ssh():
    target = ExecutionTargetSnapshot(
        target_id="myhost",
        kind="ssh",
        workdir="/remote/work",
        profile_id="myhost-profile",
    )
    assert target.kind == "ssh"
    assert target.profile_id == "myhost-profile"


# ============================================================================
# WorkspaceKey
# ============================================================================


def test_workspace_key_uniqueness():
    """Different targets produce different keys."""
    k1 = WorkspaceKey("local:/tmp/a", "/tmp/a")
    k2 = WorkspaceKey("local:/tmp/b", "/tmp/b")
    assert k1 != k2
    assert str(k1) != str(k2)


def test_workspace_key_same_target_same_workdir_are_equal():
    k1 = WorkspaceKey("docker:abc:/ws", "/ws")
    k2 = WorkspaceKey("docker:abc:/ws", "/ws")
    assert k1 == k2


# ============================================================================
# PermissionPolicySnapshot
# ============================================================================


def test_permission_policy_defaults_restrictive():
    policy = PermissionPolicySnapshot()
    assert not policy.auto_approve
    assert not policy.allow_network
    assert not policy.allow_file_write
    assert not policy.allow_execute


def test_permission_policy_can_be_permissive():
    policy = PermissionPolicySnapshot(
        auto_approve=True, allow_network=True, allow_file_write=True, allow_execute=True
    )
    assert policy.auto_approve
    assert policy.allow_network
    assert policy.allow_file_write
    assert policy.allow_execute


# ============================================================================
# RunPhase — transitions
# ============================================================================


def test_run_phase_legal_transitions():
    """Every transition listed in the spec must be legal."""
    # DORMANT → PREPARING
    assert RunPhase.PREPARING in allowed_run_transitions(RunPhase.DORMANT)
    assert RunPhase.CANCELLED in allowed_run_transitions(RunPhase.DORMANT)

    # PREPARING → RUNNING | FAILED | CANCELLED
    assert RunPhase.RUNNING in allowed_run_transitions(RunPhase.PREPARING)
    assert RunPhase.FAILED in allowed_run_transitions(RunPhase.PREPARING)
    assert RunPhase.CANCELLED in allowed_run_transitions(RunPhase.PREPARING)

    # RUNNING → FINALIZING | CANCELLED | FAILED | INTERRUPTED
    assert RunPhase.FINALIZING in allowed_run_transitions(RunPhase.RUNNING)
    assert RunPhase.CANCELLED in allowed_run_transitions(RunPhase.RUNNING)
    assert RunPhase.FAILED in allowed_run_transitions(RunPhase.RUNNING)
    assert RunPhase.INTERRUPTED in allowed_run_transitions(RunPhase.RUNNING)

    # FINALIZING → COMPLETED | FAILED | INTERRUPTED
    assert RunPhase.COMPLETED in allowed_run_transitions(RunPhase.FINALIZING)
    assert RunPhase.FAILED in allowed_run_transitions(RunPhase.FINALIZING)
    assert RunPhase.INTERRUPTED in allowed_run_transitions(RunPhase.FINALIZING)


def test_run_phase_illegal_transitions():
    """Transitions not in the spec must be rejected."""
    # Cannot jump from DORMANT directly to RUNNING
    assert RunPhase.RUNNING not in allowed_run_transitions(RunPhase.DORMANT)
    assert RunPhase.COMPLETED not in allowed_run_transitions(RunPhase.DORMANT)

    # Cannot jump from PREPARING directly to COMPLETED
    assert RunPhase.COMPLETED not in allowed_run_transitions(RunPhase.PREPARING)

    # RUNNING cannot go directly to COMPLETED (must go through FINALIZING)
    assert RunPhase.COMPLETED not in allowed_run_transitions(RunPhase.RUNNING)

    # Cannot go back to DORMANT from any active state
    assert RunPhase.DORMANT not in allowed_run_transitions(RunPhase.RUNNING)
    assert RunPhase.DORMANT not in allowed_run_transitions(RunPhase.PREPARING)


def test_terminal_run_phases_have_no_transitions():
    """Terminal phases must have empty transition sets."""
    for phase in (
        RunPhase.COMPLETED,
        RunPhase.CANCELLED,
        RunPhase.FAILED,
        RunPhase.INTERRUPTED,
    ):
        assert allowed_run_transitions(phase) == frozenset(), (
            f"{phase} should be terminal but has transitions"
        )
        assert is_terminal_run_phase(phase), f"{phase} should be recognised as terminal"


def test_non_terminal_phases_are_not_terminal():
    for phase in (
        RunPhase.DORMANT,
        RunPhase.PREPARING,
        RunPhase.RUNNING,
        RunPhase.FINALIZING,
    ):
        assert not is_terminal_run_phase(phase), f"{phase} should not be terminal"


# ============================================================================
# InputDeliveryState — transitions
# ============================================================================


def test_input_delivery_state_legal_transitions():
    """Every input state transition in the spec must be legal."""
    # ACCEPTED → IMMEDIATE_PENDING | QUEUED | REJECTED
    assert InputDeliveryState.IMMEDIATE_PENDING in allowed_input_transitions(
        InputDeliveryState.ACCEPTED
    )
    assert InputDeliveryState.QUEUED in allowed_input_transitions(
        InputDeliveryState.ACCEPTED
    )
    assert InputDeliveryState.REJECTED in allowed_input_transitions(
        InputDeliveryState.ACCEPTED
    )

    # IMMEDIATE_PENDING → APPLIED | DEFERRED
    assert InputDeliveryState.APPLIED in allowed_input_transitions(
        InputDeliveryState.IMMEDIATE_PENDING
    )
    assert InputDeliveryState.DEFERRED in allowed_input_transitions(
        InputDeliveryState.IMMEDIATE_PENDING
    )

    # QUEUED → APPLIED | REJECTED
    assert InputDeliveryState.APPLIED in allowed_input_transitions(
        InputDeliveryState.QUEUED
    )

    # DEFERRED → QUEUED | REJECTED
    assert InputDeliveryState.QUEUED in allowed_input_transitions(
        InputDeliveryState.DEFERRED
    )


def test_input_delivery_state_terminal():
    """APPLIED and REJECTED must be terminal."""
    assert allowed_input_transitions(InputDeliveryState.APPLIED) == frozenset()
    assert allowed_input_transitions(InputDeliveryState.REJECTED) == frozenset()


def test_input_delivery_state_no_backwards():
    """Once applied, an input cannot be un-applied."""
    assert InputDeliveryState.ACCEPTED not in allowed_input_transitions(
        InputDeliveryState.APPLIED
    )
    assert InputDeliveryState.ACCEPTED not in allowed_input_transitions(
        InputDeliveryState.QUEUED
    )


def test_input_delivery_immediate_cannot_go_to_accepted():
    """immediate_pending cannot go back to accepted."""
    assert InputDeliveryState.ACCEPTED not in allowed_input_transitions(
        InputDeliveryState.IMMEDIATE_PENDING
    )


# ============================================================================
# SessionMode
# ============================================================================


def test_session_mode_values():
    assert SessionMode.ASK == "ask"
    assert SessionMode.PLAN == "plan"
    assert SessionMode.RUN == "run"


def test_session_mode_is_str_enum():
    """SessionMode must be usable as a plain string for serialisation."""
    assert str(SessionMode.ASK) == "ask"
    assert isinstance(SessionMode.ASK, str)
