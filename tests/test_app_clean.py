from app.clean import (
    clean_pagent,
    format_clean_report,
    thread_is_useless,
    user_message_count,
)
from electromind.core.message import Message, Messages


def write_thread(
    tmp_path,
    thread_id: str,
    *,
    user_text: str | None = None,
    workspace_file: str | None = None,
):
    root = tmp_path / thread_id
    root.mkdir(parents=True)
    (root / "thread.toml").write_text(
        '[sandbox]\nbackend = "local"\n', encoding="utf-8"
    )
    workspace = root / "workspaces" / "main"
    workspace.mkdir(parents=True)
    if user_text is not None:
        messages = Messages()
        messages += Message.user(user_text)
        messages_dir = root / "messages"
        messages_dir.mkdir(exist_ok=True)
        messages.save_to_jsonl(messages_dir / "messages.jsonl")
    if workspace_file is not None:
        (workspace / workspace_file).write_text("data", encoding="utf-8")
    return root


def test_user_message_count(tmp_path):
    path = tmp_path / "messages.jsonl"
    messages = Messages()
    messages += Message.system("hi")
    messages += Message.user("question")
    messages.save_to_jsonl(path)
    assert user_message_count(path) == 1


def test_thread_is_useless_when_empty(tmp_path):
    root = write_thread(tmp_path, "empty")
    assert thread_is_useless(root) is True


def test_thread_is_not_useless_with_user_message(tmp_path):
    root = write_thread(tmp_path, "talked", user_text="hello")
    assert thread_is_useless(root) is False


def test_thread_is_not_useless_with_workspace_files(tmp_path):
    root = write_thread(tmp_path, "files", workspace_file="note.txt")
    assert thread_is_useless(root) is False


def test_clean_pagent_removes_empty_threads(tmp_path):
    write_thread(tmp_path, "empty-a")
    write_thread(tmp_path, "kept", user_text="hi")
    write_thread(tmp_path, "empty-b")

    report = clean_pagent(
        threads_root=tmp_path, conversations_root=tmp_path / "conversations"
    )

    assert set(report.removed_threads) == {"empty-a", "empty-b"}
    assert (tmp_path / "kept").exists()
    assert not (tmp_path / "empty-a").exists()
    assert not (tmp_path / "empty-b").exists()


def test_clean_pagent_keeps_active_thread_without_turn(tmp_path):
    write_thread(tmp_path, "current")

    report = clean_pagent(
        threads_root=tmp_path,
        conversations_root=tmp_path / "conversations",
        keep_thread_ids={"current"},
    )

    assert report.removed_threads == []
    assert (tmp_path / "current").exists()


def test_clean_pagent_removes_empty_conversations(tmp_path):
    conversations = tmp_path / "conversations"
    conversations.mkdir()
    empty = conversations / "demo.jsonl"
    empty.write_text("", encoding="utf-8")
    only_system = conversations / "sys.jsonl"
    system_messages = Messages()
    system_messages += Message.system("x")
    system_messages.save_to_jsonl(only_system)
    kept = conversations / "kept.jsonl"
    kept_messages = Messages()
    kept_messages += Message.user("hi")
    kept_messages.save_to_jsonl(kept)

    report = clean_pagent(
        threads_root=tmp_path / "threads", conversations_root=conversations
    )

    assert set(report.removed_conversations) == {"demo", "sys"}
    assert not empty.exists()
    assert not only_system.exists()
    assert kept.exists()


def test_format_clean_report():
    text = format_clean_report(
        type(
            "Report",
            (),
            {"removed_threads": ["a"], "removed_conversations": ["b"]},
        )()
    )
    assert "空 thread" in text
    assert "空 conversation" in text
