"""Harness Spine — lifecycle, routing, concurrency, recovery, and permissions.

The harness manages HOW tasks run, not WHAT they compute.
It contains no CP2K, LAMMPS, DeepMD, Slurm, or computational chemistry logic.
"""

from __future__ import annotations

from .checkpoints import (
    CHECKPOINT_RULES,
    CheckpointDrain,
    CheckpointKind,
    CheckpointRule,
    InboundCheckpoint,
    cancel_allowed_at,
    immediate_allowed_at,
)
from .identity import (
    ApprovalId,
    EventId,
    ItemId,
    MessageId,
    RequestId,
    RunId,
    RunSnapshot,
    ThreadId,
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
from .inbound import (
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
from .session_manager import (
    ThreadSession,
    ThreadSessionManager,
)
from .state import (
    ExecutionTargetSnapshot,
    InputDeliveryState,
    PermissionPolicySnapshot,
    RunPhase,
    SessionMode,
    allowed_input_transitions,
    allowed_run_transitions,
)

__all__ = [
    # IDs
    "ApprovalId",
    "EventId",
    "ItemId",
    "MessageId",
    "RequestId",
    "RunId",
    "ThreadId",
    "WorkspaceKey",
    # ID factories
    "new_approval_id",
    "new_event_id",
    "new_item_id",
    "new_message_id",
    "new_request_id",
    "new_run_id",
    # ID validators
    "validate_approval_id",
    "validate_event_id",
    "validate_item_id",
    "validate_message_id",
    "validate_request_id",
    "validate_run_id",
    "validate_thread_id",
    # Snapshot
    "RunSnapshot",
    "ExecutionTargetSnapshot",
    "PermissionPolicySnapshot",
    # Checkpoints
    "CHECKPOINT_RULES",
    "CheckpointDrain",
    "CheckpointKind",
    "CheckpointRule",
    "InboundCheckpoint",
    "cancel_allowed_at",
    "immediate_allowed_at",
    # Inbound
    "InputDelivery",
    "InputMessage",
    "InputQueue",
    "InputReceipt",
    "accepted_receipt",
    "applied_receipt",
    "deferred_receipt",
    "immediate_pending_receipt",
    "queued_receipt",
    "rejected_receipt",
    # State
    # Session Manager
    "ThreadSession",
    "ThreadSessionManager",
    # State
    "SessionMode",
    "RunPhase",
    "InputDeliveryState",
    "allowed_run_transitions",
    "allowed_input_transitions",
]
