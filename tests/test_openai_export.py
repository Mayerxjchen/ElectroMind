import json

from electromind import Message, Messages, Thread
from electromind.trace import load_messages, messages_to_openai_json, resolve_messages_path


def test_messages_to_openai_json_from_file(tmp_path):
    messages = Messages()
    messages += Message.system("sys")
    messages += Message.user("hi", turn_id=1)
    messages += Message.assistant({"type": "text", "text": "hello"}, turn_id=1)
    path = tmp_path / "messages.jsonl"
    messages.save_to_jsonl(path)

    payload = json.loads(messages_to_openai_json(str(path)))
    assert payload == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_messages_to_openai_json_from_thread_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    messages = Messages()
    messages += Message.user("ping", turn_id=1)
    messages += Message.assistant({"type": "text", "text": "pong"}, turn_id=1)
    thread = Thread.open("export-demo", overrides={"backend": "none"})
    messages.save_to_jsonl(thread.messages_storage_path)

    assert resolve_messages_path("export-demo") == thread.messages_storage_path
    payload = json.loads(messages_to_openai_json("export-demo"))
    assert payload[-1] == {"role": "assistant", "content": "pong"}


def test_load_messages_from_stdin(monkeypatch):
    raw = "\n".join(
        [
            Message.user("a", turn_id=1).model_dump_json(),
            Message.assistant(
                {"type": "text", "text": "b"}, turn_id=1
            ).model_dump_json(),
        ]
    )
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(raw + "\n"))
    payload = load_messages("-").to_openai()
    assert payload == [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
    ]
