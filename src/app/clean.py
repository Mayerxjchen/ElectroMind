from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from electromind import Thread
from electromind.conversation import (
    JsonlConversationStore,
    default_conversations_root,
)
from electromind.core.message import Messages
from electromind.ithread import (
    MESSAGES_CONVERSATION_ID,
    SPEC_FILENAME,
    WORKSPACES_DIRNAME,
)
from electromind.runtime.thread import default_threads_root


@dataclass(slots=True)
class CleanReport:
    removed_threads: list[str] = field(default_factory=list)
    removed_conversations: list[str] = field(default_factory=list)


def user_message_count(path: Path) -> int:
    if not path.is_file():
        return 0
    messages = Messages.load_from_jsonl(path)
    return sum(1 for message in messages.data if message.role == "user")


def workspace_is_empty(workspaces_root: Path) -> bool:
    """``workspaces/`` 下所有命名 workspace（main / 各 sub）都没内容才算空。"""
    if not workspaces_root.is_dir():
        return True
    for workspace in workspaces_root.iterdir():
        if workspace.is_dir() and any(workspace.iterdir()):
            return False
    return True


def thread_is_useless(thread_dir: Path) -> bool:
    if not (thread_dir / SPEC_FILENAME).is_file():
        return False
    thread = Thread.open(thread_dir.name, root=thread_dir.parent)
    user_count = sum(
        1 for message in thread.load_messages().data if message.role == "user"
    )
    if user_count > 0:
        return False
    return workspace_is_empty(thread_dir / WORKSPACES_DIRNAME)


def conversation_is_useless(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.stat().st_size == 0:
        return True
    return user_message_count(path) == 0


def iter_thread_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [
        child
        for child in root.iterdir()
        if child.is_dir() and (child / SPEC_FILENAME).is_file()
    ]


def clean_electromind(
    *,
    threads_root: Path | str | None = None,
    conversations_root: Path | str | None = None,
    keep_thread_ids: set[str] | frozenset[str] = frozenset(),
    remove: bool = True,
) -> CleanReport:
    """Remove empty threads and orphan conversations under `.electromind/`.

    A thread is useless when it has no user messages and an empty workspace.
    A standalone conversation file is useless when empty or has no user messages.
    """
    report = CleanReport()
    threads_base = (
        Path(threads_root) if threads_root is not None else default_threads_root()
    )
    conversations_base = (
        Path(conversations_root)
        if conversations_root is not None
        else Path(default_conversations_root())
    )

    for thread_dir in iter_thread_dirs(threads_base):
        thread_id = thread_dir.name
        if thread_id in keep_thread_ids:
            continue
        if not thread_is_useless(thread_dir):
            continue
        report.removed_threads.append(thread_id)
        if remove:
            shutil.rmtree(thread_dir)

    if conversations_base.is_dir():
        store = JsonlConversationStore(root=conversations_base)
        for conversation_id in store.list():
            path = store.path_for(conversation_id)
            if conversation_id == MESSAGES_CONVERSATION_ID:
                continue
            if not conversation_is_useless(path):
                continue
            report.removed_conversations.append(conversation_id)
            if remove:
                path.unlink()

    return report


def format_clean_report(report: CleanReport) -> str | None:
    parts: list[str] = []
    if report.removed_threads:
        names = ", ".join(report.removed_threads)
        parts.append(f"清理 {len(report.removed_threads)} 条空 thread: {names}")
    if report.removed_conversations:
        names = ", ".join(report.removed_conversations)
        parts.append(
            f"清理 {len(report.removed_conversations)} 个空 conversation: {names}"
        )
    if not parts:
        return None
    return " · ".join(parts)
