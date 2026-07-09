"""Conversation 持久化门面。

`ConversationStore` 负责 `conversation_id <-> Messages` 的读写。
持久化 Runner 通过 Thread 使用 conversation；Thread 目录结构在
`pagentv4.ithread` 和 `pagentv4.runtime.thread` 中描述。

具体实现放在 `pagentv4.conversation.store`。
"""

from .store import (
    CONVERSATION_ID_PATTERN,
    ConversationStore,
    JsonlConversationStore,
    SqliteConversationStore,
    default_conversations_root,
    validate_conversation_id,
)

__all__ = [
    "CONVERSATION_ID_PATTERN",
    "ConversationStore",
    "JsonlConversationStore",
    "SqliteConversationStore",
    "default_conversations_root",
    "validate_conversation_id",
]
