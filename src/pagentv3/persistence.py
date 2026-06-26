import sqlite3
import time
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, unquote
from uuid import uuid4

from .message import Messages


class PersistenceBackend(Protocol):
    def save_messages(self, conversation_id: str, messages: Messages) -> None: ...

    def load_messages(self, conversation_id: str) -> Messages: ...

    def list_conversations(self) -> list[str]: ...


class Persistence:
    def __init__(self, backend: PersistenceBackend):
        self.backend = backend

    def create_conversation(self) -> str:
        conversation_id = uuid4().hex
        self.save_messages(conversation_id, Messages())
        return conversation_id

    def save_messages(self, conversation_id: str, messages: Messages) -> None:
        self.backend.save_messages(conversation_id, messages)

    def load_messages(self, conversation_id: str) -> Messages:
        return self.backend.load_messages(conversation_id)

    def list_conversations(self) -> list[str]:
        return self.backend.list_conversations()


class JsonlBackend:
    def __init__(self, root_dir: str | Path):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def conversation_path(self, conversation_id: str) -> Path:
        name = quote(conversation_id, safe="")
        return self.root_dir / f"{name}.jsonl"

    def save_messages(self, conversation_id: str, messages: Messages) -> None:
        path = self.conversation_path(conversation_id)
        messages.save_to_jsonl(path)

    def load_messages(self, conversation_id: str) -> Messages:
        path = self.conversation_path(conversation_id)
        if not path.exists():
            return Messages()
        return Messages.load_from_jsonl(path)

    def list_conversations(self) -> list[str]:
        paths = sorted(
            self.root_dir.glob("*.jsonl"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return [unquote(path.stem) for path in paths]


class SqliteBackend:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.init_schema()

    def init_schema(self) -> None:
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                messages_json TEXT NOT NULL,
                updated_at_ns INTEGER NOT NULL
            )
            """
        )
        self.connection.commit()

    def save_messages(self, conversation_id: str, messages: Messages) -> None:
        updated_at_ns = time.time_ns()
        messages_json = messages.model_dump_json()
        self.connection.execute(
            """
            INSERT INTO conversations (conversation_id, messages_json, updated_at_ns)
            VALUES (?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                messages_json = excluded.messages_json,
                updated_at_ns = excluded.updated_at_ns
            """,
            (conversation_id, messages_json, updated_at_ns),
        )
        self.connection.commit()

    def load_messages(self, conversation_id: str) -> Messages:
        row = self.connection.execute(
            """
            SELECT messages_json
            FROM conversations
            WHERE conversation_id = ?
            """,
            (conversation_id,),
        ).fetchone()
        if row is None:
            return Messages()
        return Messages.model_validate_json(row[0])

    def list_conversations(self) -> list[str]:
        rows = self.connection.execute(
            """
            SELECT conversation_id
            FROM conversations
            ORDER BY updated_at_ns DESC, conversation_id DESC
            """
        ).fetchall()
        return [row[0] for row in rows]

    def close(self) -> None:
        self.connection.close()
