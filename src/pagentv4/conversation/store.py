"""Conversation 持久化原语。"""

from __future__ import annotations

import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, unquote

from ..core.message import Message, Messages

CONVERSATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")


def default_conversations_root() -> str:
    override = os.environ.get("PAGENT_CONVERSATIONS_DIR")
    if override:
        return os.path.abspath(override)
    return os.path.join(os.getcwd(), ".pagent", "conversations")


def validate_conversation_id(conversation_id: str) -> None:
    if CONVERSATION_ID_PATTERN.match(conversation_id):
        return
    raise ValueError(
        f"invalid conversation_id: {conversation_id!r}; "
        "must match [A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
    )


class ConversationStore(Protocol):
    def save(self, conversation_id: str, messages: Messages) -> None: ...
    def load(self, conversation_id: str) -> Messages: ...
    def list(self) -> list[str]: ...
    def delete(self, conversation_id: str) -> None: ...


class JsonlConversationStore:
    """一 conversation 一个 jsonl 文件。"""

    def __init__(self, root: str | Path | None = None):
        self.root = (
            Path(root) if root is not None else Path(default_conversations_root())
        )
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, conversation_id: str) -> Path:
        validate_conversation_id(conversation_id)
        return self.root / f"{quote(conversation_id, safe='')}.jsonl"

    def save(self, conversation_id: str, messages: Messages) -> None:
        messages.save_to_jsonl(self.path_for(conversation_id))

    def load(self, conversation_id: str) -> Messages:
        path = self.path_for(conversation_id)
        if not path.exists():
            return Messages()
        return Messages.load_from_jsonl(path)

    def list(self) -> list[str]:
        paths = sorted(
            self.root.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return [unquote(p.stem) for p in paths]

    def delete(self, conversation_id: str) -> None:
        path = self.path_for(conversation_id)
        if path.exists():
            path.unlink()


class SqliteConversationStore:
    """所有对话塞进一张表，一行一 conversation；适合量大 / 需索引。"""

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = Path(default_conversations_root()) / "conversations.sqlite"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.init_schema()

    def init_schema(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                payload_jsonl TEXT NOT NULL,
                updated_at_ns INTEGER NOT NULL
            )
            """
        )
        self.connection.commit()

    def dump_jsonl(self, messages: Messages) -> str:
        return "\n".join(message.model_dump_json() for message in messages.data)

    def load_jsonl(self, payload: str) -> Messages:
        messages = Messages()
        for line in payload.splitlines():
            raw = line.strip()
            if not raw:
                continue
            messages += Message.model_validate_json(raw)
        return messages

    def save(self, conversation_id: str, messages: Messages) -> None:
        validate_conversation_id(conversation_id)
        self.connection.execute(
            """
            INSERT INTO conversations (conversation_id, payload_jsonl, updated_at_ns)
            VALUES (?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                payload_jsonl = excluded.payload_jsonl,
                updated_at_ns = excluded.updated_at_ns
            """,
            (conversation_id, self.dump_jsonl(messages), time.time_ns()),
        )
        self.connection.commit()

    def load(self, conversation_id: str) -> Messages:
        validate_conversation_id(conversation_id)
        row = self.connection.execute(
            "SELECT payload_jsonl FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            return Messages()
        return self.load_jsonl(row[0])

    def list(self) -> list[str]:
        rows = self.connection.execute(
            """
            SELECT conversation_id FROM conversations
            ORDER BY updated_at_ns DESC, conversation_id ASC
            """
        ).fetchall()
        return [row[0] for row in rows]

    def delete(self, conversation_id: str) -> None:
        validate_conversation_id(conversation_id)
        self.connection.execute(
            "DELETE FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
