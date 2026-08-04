import pytest

from electromind import (
    JsonlConversationStore,
    Messages,
    Runner,
    SqliteConversationStore,
    default_conversations_root,
)


class FakeStreamChunk:
    def __init__(self, *, content=None, reasoning=None, tool_calls=None):
        delta = type(
            "Delta",
            (),
            {
                "content": content,
                "reasoning_content": reasoning,
                "tool_calls": tool_calls,
            },
        )()
        self.choices = [type("Choice", (), {"delta": delta})()]


class FakeProvider:
    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = []

    async def complete(self, messages, tools=None, **run_kwargs):
        self.calls.append({"messages": messages, "tools": tools, **run_kwargs})
        chunks = self.steps.pop(0)

        async def stream():
            for chunk in chunks:
                yield chunk

        return stream()


def test_default_conversations_root_is_user_home(tmp_path, monkeypatch):
    monkeypatch.delenv("ELECTROMIND_HOME", raising=False)
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(cwd)
    assert default_conversations_root() == str(home / ".electromind" / "conversations")


def test_jsonl_store_roundtrip(tmp_path):
    store = JsonlConversationStore(root=tmp_path)
    messages = Messages()
    from electromind import Message

    messages += Message.system("sys")
    messages += Message.user("hi", turn_id=1)
    messages += Message.assistant({"type": "text", "text": "hello"}, turn_id=1)
    store.save("alpha", messages)

    reloaded = store.load("alpha")
    assert [m.role for m in reloaded.data] == ["system", "user", "assistant"]
    assert reloaded.data[-1].content.text == "hello"
    assert "alpha" in store.list()


@pytest.mark.asyncio
async def test_runner_loads_prior_conversation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    provider_first = FakeProvider([[FakeStreamChunk(content="first")]])
    runner = await Runner.create(
        "beta",
        provider_first,
        overrides={"backend": "local"},
        extra_system="sys",
    )
    try:
        async for _ in runner.run("hi"):
            pass
    finally:
        await runner.close()

    provider_second = FakeProvider([[FakeStreamChunk(content="second")]])
    runner = await Runner.create(
        "beta",
        provider_second,
        overrides={"backend": "local"},
        extra_system="sys",
    )
    try:
        async for _ in runner.run("again"):
            pass

        roles = [message.role for message in runner.messages.data]
        assert roles == ["system", "user", "assistant", "user", "assistant"]
        assert runner.messages.data[-1].content.text == "second"
    finally:
        await runner.close()

    store = JsonlConversationStore(
        root=tmp_path / ".electromind" / "threads" / "beta" / "messages"
    )
    reloaded = store.load("messages")
    assert reloaded.data[-1].content.text == "second"


@pytest.mark.asyncio
async def test_runner_flushes_each_turn(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = JsonlConversationStore(root=tmp_path / "gamma")

    class RecordingStore:
        def __init__(self):
            self.saves = 0

        def save(self, conversation_id, messages):
            self.saves += 1
            store.save(conversation_id, messages)

        def load(self, conversation_id):
            return store.load(conversation_id)

        def list(self):
            return store.list()

        def delete(self, conversation_id):
            store.delete(conversation_id)

    def make_tool_call(name, arguments):
        return type(
            "FakeCall",
            (),
            {
                "index": 0,
                "id": "call-1",
                "type": "function",
                "function": type("Fn", (), {"name": name, "arguments": arguments})(),
            },
        )()

    provider = FakeProvider(
        [
            [FakeStreamChunk(tool_calls=[make_tool_call("noop", "{}")])],
            [FakeStreamChunk(content="done")],
        ]
    )

    from electromind import tool

    @tool()
    def noop() -> str:
        """no op"""
        return "ok"

    runner = await Runner.create(
        "gamma",
        provider,
        overrides={"backend": "local"},
        extra_system="sys",
        tools=[noop],
    )
    original_store = runner.store
    recorder = RecordingStore()
    runner.store = recorder  # type: ignore[assignment]
    try:
        async for _ in runner.run("hi"):
            pass
        assert recorder.saves >= 2
    finally:
        runner.store = original_store
        await runner.close()


def test_jsonl_store_rejects_bad_id(tmp_path):
    store = JsonlConversationStore(root=tmp_path)
    with pytest.raises(ValueError):
        store.load("../escape")


def test_jsonl_store_delete(tmp_path):
    store = JsonlConversationStore(root=tmp_path)
    messages = Messages()
    from electromind import Message

    messages += Message.system("sys")
    store.save("delta", messages)
    assert "delta" in store.list()
    store.delete("delta")
    assert "delta" not in store.list()


def test_sqlite_store_roundtrip(tmp_path):
    store = SqliteConversationStore(db_path=tmp_path / "conv.sqlite")
    try:
        messages = Messages()
        from electromind import Message

        messages += Message.system("sys")
        messages += Message.user("hello", turn_id=1)
        store.save("epsilon", messages)

        reloaded = store.load("epsilon")
        assert [m.role for m in reloaded.data] == ["system", "user"]
        assert "epsilon" in store.list()

        store.delete("epsilon")
        assert "epsilon" not in store.list()
    finally:
        store.close()


@pytest.mark.asyncio
async def test_runner_persists_conversation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    provider = FakeProvider([[FakeStreamChunk(content="done")]])
    runner = await Runner.create(
        "zeta",
        provider,
        overrides={"backend": "local"},
        extra_system="sys",
    )
    try:
        async for _ in runner.run("hi"):
            pass
    finally:
        await runner.close()

    store = JsonlConversationStore(
        root=tmp_path / ".electromind" / "threads" / "zeta" / "messages"
    )
    reloaded = store.load("messages")
    assert reloaded.data[-1].content.text == "done"
