"""ChatRunner 单测：conversation 持久化必须挂在 Thread 上。"""

import types

import pytest

from pagentv4 import Agent, ChatAgent, ChatRunner, RunEnd, TextDelta, tool


class FakeStreamChunk:
    def __init__(self, *, content=None, reasoning=None, tool_calls=None):
        delta = types.SimpleNamespace(
            content=content,
            reasoning_content=reasoning,
            tool_calls=tool_calls,
        )
        self.choices = [types.SimpleNamespace(delta=delta)]


class FakeProvider:
    def __init__(self, steps):
        self.steps = list(steps)

    async def complete(self, messages, tools=None, **run_kwargs):
        chunks = self.steps.pop(0)

        async def stream():
            for chunk in chunks:
                yield chunk

        return stream()


def test_chat_agent_alias_points_to_chat_runner():
    assert ChatAgent is ChatRunner


@pytest.mark.asyncio
async def test_chat_runner_opens_thread(tmp_path):
    """ChatRunner(agent, thread_id=...) 创建 thread 并写 thread.toml。"""
    provider = FakeProvider([[FakeStreamChunk(content="hi")]])
    agent = Agent(provider, system="test")
    runner = ChatRunner(agent, thread_id="test-1", root=str(tmp_path))

    assert runner.thread.id == "test-1"
    assert runner.conversation_id == "messages"
    assert runner.spec.backend == "none"
    assert (tmp_path / "test-1" / "thread.toml").is_file()

    texts = [t async for t in runner.run("hello", return_type="text")]
    assert texts == ["hi"]
    assert (tmp_path / "test-1" / "messages.jsonl").is_file()
    await runner.close()


@pytest.mark.asyncio
async def test_chat_runner_conversation_id_is_compat_thread_alias(tmp_path):
    """旧 conversation_id 参数作为 thread_id 兼容别名。"""
    provider = FakeProvider([[FakeStreamChunk(content="ok")]])
    agent = Agent(provider, system="test")
    runner = ChatRunner(agent, conversation_id="compat-id", root=str(tmp_path))

    assert runner.thread.id == "compat-id"
    assert runner.conversation_id == "messages"
    assert (tmp_path / "compat-id" / "thread.toml").is_file()
    await runner.close()


@pytest.mark.asyncio
async def test_chat_runner_auto_thread_id(tmp_path):
    """不传 thread_id 时自动生成 thread- 时间戳。"""
    provider = FakeProvider([[FakeStreamChunk(content="ok")]])
    agent = Agent(provider, system="test")
    runner = ChatRunner(agent, root=str(tmp_path))

    assert runner.thread.id.startswith("thread-")
    await runner.close()


@pytest.mark.asyncio
async def test_chat_runner_sqlite_backend(tmp_path):
    """backend="sqlite" 时 SQLite db 也在 thread 目录里。"""
    from pagentv4.conversation import SqliteConversationStore

    provider = FakeProvider([[FakeStreamChunk(content="sqlite")]])
    agent = Agent(provider, system="test")
    runner = ChatRunner(
        agent,
        thread_id="sql-test",
        root=str(tmp_path),
        backend="sqlite",
    )

    assert isinstance(runner.store, SqliteConversationStore)
    texts = [t async for t in runner.run("go", return_type="text")]
    assert texts == ["sqlite"]
    assert (tmp_path / "sql-test" / "conversations.sqlite").is_file()
    await runner.close()


@pytest.mark.asyncio
async def test_chat_runner_from_toml(tmp_path):
    """从 TOML 配置文件创建 ChatRunner。"""
    toml_content = (
        "[conversation]\n"
        'backend = "jsonl"\n'
        'root = "conversation"\n'
        'messages_id = "main"\n'
    )
    toml_path = tmp_path / "chat.toml"
    toml_path.write_text(toml_content)

    provider = FakeProvider([[FakeStreamChunk(content="from-toml")]])
    agent = Agent(provider, system="test")
    runner = ChatRunner.from_toml(
        toml_path, agent, thread_id="toml-thread", root=tmp_path
    )

    assert runner.thread.id == "toml-thread"
    assert runner.conversation_id == "main"
    assert runner.spec.conversation_backend == "jsonl"

    texts = [t async for t in runner.run("hi", return_type="text")]
    assert texts == ["from-toml"]
    assert (tmp_path / "toml-thread" / "conversation" / "main.jsonl").is_file()
    await runner.close()


@pytest.mark.asyncio
async def test_flush_persists_messages_under_thread(tmp_path):
    """run 结束后 messages 写入 thread，下次打开同一个 thread 能恢复。"""
    provider_first = FakeProvider([[FakeStreamChunk(content="first")]])
    agent_first = Agent(provider_first, system="test")
    runner = ChatRunner(agent_first, thread_id="persist-test", root=str(tmp_path))
    async for _ in runner.run("hi", return_type="event"):
        pass
    await runner.close()

    provider_second = FakeProvider([[FakeStreamChunk(content="second")]])
    agent_second = Agent(provider_second, system="test")
    runner = ChatRunner(agent_second, thread_id="persist-test", root=str(tmp_path))
    assert len(runner.messages.data) >= 2
    assert any(
        m.content.text == "first" for m in runner.messages.data if m.role == "assistant"
    )

    async for _ in runner.run("again", return_type="event"):
        pass
    assert any(
        m.content.text == "second"
        for m in runner.messages.data
        if m.role == "assistant"
    )
    await runner.close()


@pytest.mark.asyncio
async def test_flush_on_each_continuing(tmp_path):
    """多 turn run 中，每 turn 都 flush。"""

    tc = types.SimpleNamespace(
        index=0,
        id="c1",
        type="function",
        function=types.SimpleNamespace(name="echo", arguments='{"msg":"ping"}'),
    )

    @tool()
    def echo(msg: str) -> str:
        """Echo back."""
        return msg

    provider = FakeProvider(
        [
            [FakeStreamChunk(tool_calls=[tc])],
            [FakeStreamChunk(content="done")],
        ]
    )
    agent = Agent(provider, system="test", tools=[echo])
    runner = ChatRunner(agent, thread_id="flush-test", root=str(tmp_path))

    saves = 0
    original_save = runner.store.save

    def counting_save(cid, msgs):
        nonlocal saves
        saves += 1
        original_save(cid, msgs)

    runner.store.save = counting_save  # type: ignore[assignment]

    async for _ in runner.run("go", return_type="event"):
        pass

    assert saves >= 2
    await runner.close()


@pytest.mark.asyncio
async def test_event_stream_with_tools(tmp_path):
    """带工具的事件流：ToolCallBegin + ToolResult + TextDelta。"""
    from pagentv4 import ToolCallBegin, ToolResult

    tc = types.SimpleNamespace(
        index=0,
        id="c1",
        type="function",
        function=types.SimpleNamespace(name="echo", arguments='{"msg":"hi"}'),
    )

    @tool()
    def echo(msg: str) -> str:
        """Echo back."""
        return msg

    provider = FakeProvider(
        [
            [FakeStreamChunk(content="checking", tool_calls=[tc])],
            [FakeStreamChunk(content="done")],
        ]
    )
    agent = Agent(provider, system="test", tools=[echo], max_turns=4)
    runner = ChatRunner(agent, thread_id="event-test", root=str(tmp_path))

    events = [e async for e in runner.run("go", return_type="event")]
    assert any(isinstance(e, TextDelta) and e.text == "checking" for e in events)
    assert any(isinstance(e, ToolCallBegin) and e.tool_call_id == "c1" for e in events)
    assert any(isinstance(e, ToolResult) and e.tool_call_id == "c1" for e in events)
    assert any(isinstance(e, TextDelta) and e.text == "done" for e in events)
    assert isinstance(events[-1], RunEnd)
    await runner.close()
