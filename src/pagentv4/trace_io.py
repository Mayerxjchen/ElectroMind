"""Load pagent message trajectories from jsonl, thread id, or stdin."""

from __future__ import annotations

import sys
from pathlib import Path

from .core.message import Message, Messages
from .runtime.thread import Thread, default_threads_root


def resolve_messages_path(source: str) -> Path:
    path = Path(source)
    if path.is_file():
        return path
    thread = Thread.open(source, root=default_threads_root())
    return thread.messages_storage_path


def load_messages(source: str) -> Messages:
    if source == "-":
        messages = Messages()
        for line in sys.stdin:
            raw = line.strip()
            if raw:
                messages += Message.model_validate_json(raw)
        return messages
    path = resolve_messages_path(source)
    if not path.is_file():
        raise SystemExit(f"messages file not found: {path}")
    return Messages.load_from_jsonl(path)
