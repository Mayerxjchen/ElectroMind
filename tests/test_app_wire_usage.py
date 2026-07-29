import json

from app import wire
from electromind.ithread import METAINFO_FILENAME
from electromind.runtime.thread import Thread


def test_build_usage_snapshot_flattens_turn_result_usage():
    snapshot = wire.build_usage_snapshot(
        {
            "prompt_tokens": 1200,
            "completion_tokens": 80,
            "total_tokens": 1280,
            "prompt_tokens_details": {
                "cached_tokens": 900,
                "cache_write_tokens": 12,
            },
            "completion_tokens_details": {"reasoning_tokens": 32},
        }
    )

    assert snapshot is not None
    assert snapshot["prompt_tokens"] == 1200
    assert snapshot["cached_tokens"] == 900
    assert snapshot["cache_write_tokens"] == 12
    assert snapshot["completion_tokens"] == 80
    assert snapshot["reasoning_tokens"] == 32
    assert snapshot["context_limit"] == wire.DEFAULT_CONTEXT_LIMIT
    assert snapshot["updated_at"]


def test_touch_thread_usage_writes_metainfo(tmp_path, monkeypatch):
    monkeypatch.setattr(wire, "default_threads_root", lambda: tmp_path)
    thread = Thread.open("thread-usage-test")
    wire.touch_thread_usage(
        thread,
        {
            "prompt_tokens": 500,
            "completion_tokens": 20,
            "prompt_tokens_details": {"cached_tokens": 400},
        },
        context_limit=64_000,
    )

    metainfo = json.loads((thread.root / METAINFO_FILENAME).read_text(encoding="utf-8"))
    assert metainfo["usage"]["prompt_tokens"] == 500
    assert metainfo["usage"]["cached_tokens"] == 400
    assert metainfo["usage"]["context_limit"] == 64_000


def test_emit_thread_history_replay_includes_usage(monkeypatch):
    captured: dict = {}

    def fake_emit(line: str):
        captured.update(json.loads(line.rstrip()))

    monkeypatch.setattr(wire, "emit_line", fake_emit)

    class FakeThread:
        id = "thread-2"

        class spec:
            model = "deepseek-chat"

        def load_metainfo(self):
            return {
                "title": "hi",
                "usage": {"prompt_tokens": 99, "cached_tokens": 50},
            }

        def load_messages(self):
            from electromind.core.message import Messages

            return Messages()

    wire.emit_thread_history_replay(FakeThread())

    assert captured["params"]["usage"]["prompt_tokens"] == 99
    assert captured["params"]["context_limit"] == 64_000


def test_emit_history_replay_includes_usage(monkeypatch):
    captured: dict = {}

    def fake_emit(line: str):
        captured.update(json.loads(line.rstrip()))

    monkeypatch.setattr(wire, "emit_line", fake_emit)

    class FakeThread:
        id = "thread-1"
        project_path = None

        class spec:
            model = "deepseek-v4-flash"
            project_path = ""

        def load_metainfo(self):
            return {
                "title": "hello",
                "usage": {"prompt_tokens": 42, "cached_tokens": 10},
            }

    class FakeRunner:
        thread = FakeThread()
        messages = type("M", (), {"data": []})()

    wire.emit_history_replay(FakeRunner())

    assert captured["method"] == "HistoryReplay"
    assert captured["params"]["usage"]["prompt_tokens"] == 42
    assert captured["params"]["context_limit"] == 128_000
