import pytest

from pagentv4 import (
    Agent,
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


def test_default_conversations_root_is_project_local(tmp_path, monkeypatch):
    monkeypatch.delenv("PAGENT_CONVERSATIONS_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert default_conversations_root() == str(tmp_path / ".pagent" / "conversations")


def test_jsonl_store_roundtrip(tmp_path):
    store = JsonlConversationStore(root=tmp_path)
    messages = Messages()

    async def scenario():
        provider = FakeProvider([[FakeStreamChunk(content="hello")]])
        agent = Agent(provider, system="sys")
        runner = Runner(store=store)
        async for _ in runner.arun(
            agent, "hi", messages, conversation_id="alpha"
        ):
            pass

    import asyncio

    asyncio.run(scenario())

    reloaded = store.load("alpha")
    assert [m.role for m in reloaded.data] == ["system", "user", "assistant"]
    assert reloaded.data[-1].content.text == "hello"
    assert "alpha" in store.list()


@pytest.mark.asyncio
async def test_arun_loads_prior_conversation(tmp_path):
    store = JsonlConversationStore(root=tmp_path)

    provider_first = FakeProvider([[FakeStreamChunk(content="first")]])
    runner = Runner(store=store)
    async for _ in runner.arun(
        Agent(provider_first, system="sys"),
        "hi",
        Messages(),
        conversation_id="beta",
    ):
        pass

    provider_second = FakeProvider([[FakeStreamChunk(content="second")]])
    fresh_messages = Messages()
    async for _ in runner.arun(
        Agent(provider_second, system="sys"),
        "again",
        fresh_messages,
        conversation_id="beta",
    ):
        pass

    roles = [message.role for message in fresh_messages.data]
    assert roles == ["system", "user", "assistant", "user", "assistant"]
    assert fresh_messages.data[-1].content.text == "second"

    reloaded = store.load("beta")
    assert reloaded.data[-1].content.text == "second"


@pytest.mark.asyncio
async def test_arun_flushes_each_turn(tmp_path):
    store = JsonlConversationStore(root=tmp_path)

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

    recorder = RecordingStore()

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

    from pagentv4 import tool

    @tool()
    def noop() -> str:
        """no op"""
        return "ok"

    runner = Runner(store=recorder)
    async for _ in runner.arun(
        Agent(provider, system="sys", tools=[noop]),
        "hi",
        Messages(),
        conversation_id="gamma",
    ):
        pass

    assert recorder.saves >= 2


@pytest.mark.asyncio
async def test_arun_rejects_conversation_id_without_store():
    runner = Runner()
    with pytest.raises(ValueError):
        async for _ in runner.arun(
            Agent(FakeProvider([[FakeStreamChunk(content="x")]]), system="s"),
            "hi",
            Messages(),
            conversation_id="foo",
        ):
            pass


def test_jsonl_store_rejects_bad_id(tmp_path):
    store = JsonlConversationStore(root=tmp_path)
    with pytest.raises(ValueError):
        store.load("../escape")


def test_jsonl_store_delete(tmp_path):
    store = JsonlConversationStore(root=tmp_path)
    messages = Messages()
    from pagentv4 import Message

    messages += Message.system("sys")
    store.save("delta", messages)
    assert "delta" in store.list()
    store.delete("delta")
    assert "delta" not in store.list()


def test_sqlite_store_roundtrip(tmp_path):
    store = SqliteConversationStore(db_path=tmp_path / "conv.sqlite")
    try:
        messages = Messages()
        from pagentv4 import Message

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
async def test_session_persists_conversation(tmp_path):
    store = JsonlConversationStore(root=tmp_path / "conv")

    provider = FakeProvider([[FakeStreamChunk(content="done")]])
    runner = Runner(store=store)
    async for _ in runner.session(
        provider,
        "hi",
        system="sys",
        workdir=str(tmp_path / "sandbox"),
        conversation_id="zeta",
    ):
        pass

    reloaded = store.load("zeta")
    assert reloaded.data[-1].content.text == "done"
