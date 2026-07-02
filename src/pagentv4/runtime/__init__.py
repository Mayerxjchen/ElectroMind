"""pagentv4.runtime —— 调度 + 持久化门面。

Runner 与 thread 同生共死：`await Runner.open(...)` → `runner.run(...)` → `runner.close()`。
"""

from .conversation import (
    ConversationStore,
    JsonlConversationStore,
    SqliteConversationStore,
    default_conversations_root,
)
from .runner import ArunReturnType, EventHandler, Runner
from .thread import Thread, ThreadSpec, default_threads_root, validate_thread_id

__all__ = [
    "ArunReturnType",
    "ConversationStore",
    "EventHandler",
    "JsonlConversationStore",
    "Runner",
    "SqliteConversationStore",
    "Thread",
    "ThreadSpec",
    "default_conversations_root",
    "default_threads_root",
    "validate_thread_id",
]
