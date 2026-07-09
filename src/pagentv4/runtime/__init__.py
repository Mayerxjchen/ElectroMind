"""pagentv4.runtime —— 调度 + 持久化门面。

Runner 与 thread 同生共死：`await Runner.create(...)` → `runner.run(...)` → `runner.close()`。
"""

from ..conversation import (
    ConversationStore,
    JsonlConversationStore,
    SqliteConversationStore,
    default_conversations_root,
)
from ..ithread import IThread, ThreadSpec, validate_thread_id
from .base_runner import BaseRunner
from .chat_runner import ChatRunner
from .code_runner import CodeRunner
from .helper import ArunReturnType, EventHandler
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
from .protocol import AgentRunner
from .runner import Runner
from .thread import Thread, default_threads_root
from .vanilla import VanillaRunner

ChatAgent = ChatRunner
CodeAgent = CodeRunner
ThreadAgent = Runner
VanillaAgent = VanillaRunner

__all__ = [
    "ArunReturnType",
    "AgentRunner",
    "BaseRunner",
    "ChatAgent",
    "ChatRunner",
    "CodeAgent",
    "CodeRunner",
    "CancelRun",
    "CheckpointPolicy",
    "ConversationStore",
    "DenyTool",
    "DrainResult",
    "EventHandler",
    "IThread",
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
    "ThreadAgent",
    "ThreadSpec",
    "VanillaAgent",
    "VanillaRunner",
    "default_conversations_root",
    "default_threads_root",
    "fold_inbound",
    "validate_thread_id",
]
