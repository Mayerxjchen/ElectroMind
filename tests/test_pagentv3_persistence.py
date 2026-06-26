from pagentv3 import JsonlBackend, Message, Messages, Persistence, SqliteBackend


def test_create_conversation_creates_empty_messages_file(tmp_path):
    persistence = Persistence(JsonlBackend(tmp_path))

    conversation_id = persistence.create_conversation()

    assert conversation_id
    assert persistence.load_messages(conversation_id) == Messages()
    assert (tmp_path / f"{conversation_id}.jsonl").exists()


def test_jsonl_backend_round_trip(tmp_path):
    persistence = Persistence(JsonlBackend(tmp_path))
    messages = Messages()
    messages += Message.system("You are helpful.")
    messages += Message.user("hello")
    messages += Message.assistant({"type": "text", "text": "done"})

    persistence.save_messages("conversation-1", messages)
    restored = persistence.load_messages("conversation-1")

    assert restored == messages
    assert (tmp_path / "conversation-1.jsonl").exists()


def test_jsonl_backend_returns_empty_messages_for_missing_conversation(tmp_path):
    persistence = Persistence(JsonlBackend(tmp_path))

    restored = persistence.load_messages("missing")

    assert restored == Messages()


def test_list_conversations_returns_newest_first(tmp_path):
    persistence = Persistence(JsonlBackend(tmp_path))

    persistence.save_messages("conversation-1", Messages())
    persistence.save_messages("conversation-2", Messages())

    assert persistence.list_conversations() == ["conversation-2", "conversation-1"]


def test_create_conversation_creates_empty_sqlite_row(tmp_path):
    persistence = Persistence(SqliteBackend(tmp_path / "pagentv3.db"))

    conversation_id = persistence.create_conversation()

    assert conversation_id
    assert persistence.load_messages(conversation_id) == Messages()


def test_sqlite_backend_round_trip(tmp_path):
    persistence = Persistence(SqliteBackend(tmp_path / "pagentv3.db"))
    messages = Messages()
    messages += Message.system("You are helpful.")
    messages += Message.user("hello")
    messages += Message.assistant({"type": "text", "text": "done"})

    persistence.save_messages("conversation-1", messages)
    restored = persistence.load_messages("conversation-1")

    assert restored == messages


def test_sqlite_backend_returns_empty_messages_for_missing_conversation(tmp_path):
    persistence = Persistence(SqliteBackend(tmp_path / "pagentv3.db"))

    restored = persistence.load_messages("missing")

    assert restored == Messages()


def test_sqlite_list_conversations_returns_newest_first(tmp_path):
    persistence = Persistence(SqliteBackend(tmp_path / "pagentv3.db"))

    persistence.save_messages("conversation-1", Messages())
    persistence.save_messages("conversation-2", Messages())

    assert persistence.list_conversations() == ["conversation-2", "conversation-1"]
