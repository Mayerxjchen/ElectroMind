"""pagentv4.runtime —— 调度 + 持久化门面。

Runner 把 Agent 跑起来，处理事件流、工具调用、会话存储；
ConversationStore 抽象把 Messages 落地到 JSONL / SQLite / 你自己的后端。

这一层允许拿 core、sandbox、adapters；反之 core 不认这里。
"""

from .conversation import (
    ConversationStore,
    JsonlConversationStore,
    SqliteConversationStore,
    default_conversations_root,
)
from .runner import ArunReturnType, EventHandler, Runner, run_agent
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
    "run_agent",
    "validate_thread_id",
]
