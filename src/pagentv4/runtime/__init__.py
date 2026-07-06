"""pagentv4.runtime —— 调度 + 持久化门面。

Runner 与 thread 同生共死：`await Runner.open(...)` → `runner.run(...)` → `runner.close()`。
"""

from .conversation import (
    ConversationStore,
    JsonlConversationStore,
    SqliteConversationStore,
    default_conversations_root,
)
from .hooks import (
    PostToolHookContext,
    ToolDecision,
    ToolHookContext,
    ToolHooks,
)
from .inbound import (
    CancelRun,
    CheckpointPolicy,
    DenyTool,
    DrainResult,
    InboundEvent,
    InboundMailbox,
    PermitTool,
    RunCancelled,
    Steer,
    ToolPermitResult,
    fold_inbound,
)
from .runner import ArunReturnType, EventHandler, Runner
from .thread import Thread, ThreadSpec, default_threads_root, validate_thread_id

__all__ = [
    "ArunReturnType",
    "CancelRun",
    "CheckpointPolicy",
    "ConversationStore",
    "DenyTool",
    "DrainResult",
    "EventHandler",
    "InboundEvent",
    "InboundMailbox",
    "JsonlConversationStore",
    "PermitTool",
    "RunCancelled",
    "Runner",
    "SqliteConversationStore",
    "Steer",
    "ToolPermitResult",
    "PostToolHookContext",
    "ToolDecision",
    "ToolHookContext",
    "ToolHooks",
    "Thread",
    "ThreadSpec",
    "default_conversations_root",
    "default_threads_root",
    "fold_inbound",
    "validate_thread_id",
]
