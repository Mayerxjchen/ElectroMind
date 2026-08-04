from types import SimpleNamespace

import pytest

from electromind import Agent, AgentCore, Runner, ThreadAgent
from electromind.core.tool import FunctionTool
from electromind.core.turn_result import TurnResult


class FakeStreamChunk:
    def __init__(self, *, content=None, reasoning=None, tool_calls=None, usage=None):
        delta = type(
            "Delta",
            (),
            {
                "content": content,
                "reasoning_content": reasoning,
                "tool_calls": tool_calls,
            },
        )()
        self.choices = (
            [type("Choice", (), {"delta": delta})()]
            if (content is not None or reasoning is not None or tool_calls is not None)
            else []
        )
        self.usage = usage


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


async def open_runner(
    tmp_path, monkeypatch, provider, *, system="test", tools=(), max_turns=24
):
    monkeypatch.chdir(tmp_path)
    return await Runner.create(
        "test",
        provider,
        overrides={"backend": "local"},
        extra_system=system,
        max_turns=max_turns,
        tools=tools,
    )


def test_thread_agent_alias_points_to_runner():
    assert ThreadAgent is Runner


def test_agent_alias_points_to_agent_core():
    assert Agent is AgentCore


@pytest.mark.asyncio
async def test_runner_populates_messages_with_system_prompt(tmp_path, monkeypatch):
    provider = FakeProvider(
        [[FakeStreamChunk(content="hel"), FakeStreamChunk(content="lo")]]
    )
    runner = await open_runner(tmp_path, monkeypatch, provider, system="test")
    try:
        async for _ in runner.run("hi"):
            pass
    finally:
        await runner.close()

    assert [message.role for message in runner.messages.data] == [
        "system",
        "user",
        "assistant",
    ]
    assert len({message.message_id for message in runner.messages.data}) == len(
        runner.messages.data
    )
    assert runner.messages.data[0].turn_id == 0
    assert runner.messages.data[1].turn_id == 1
    assert runner.messages.data[2].turn_id == 1
    assert runner.messages.data[-1].content.text == "hello"


@pytest.mark.asyncio
async def test_runner_keeps_existing_messages(tmp_path, monkeypatch):
    provider = FakeProvider(
        [
            [FakeStreamChunk(content="done")],
            [FakeStreamChunk(content="next")],
        ]
    )
    runner = await open_runner(tmp_path, monkeypatch, provider, system="test")
    try:
        async for _ in runner.run("earlier"):
            pass
        existing_messages = list(runner.messages.data)

        async for _ in runner.run("next"):
            pass

        assert runner.messages.data[: len(existing_messages)] == existing_messages
        assert provider.calls[0]["messages"][-1] == {
            "role": "user",
            "content": "earlier",
        }
        assert provider.calls[1]["messages"][-1] == {"role": "user", "content": "next"}
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_runner_accumulates_assistant_chunks_in_messages(tmp_path, monkeypatch):
    provider = FakeProvider(
        [
            [
                FakeStreamChunk(reasoning="let"),
                FakeStreamChunk(reasoning=" me think"),
                FakeStreamChunk(content="hel"),
                FakeStreamChunk(content="lo"),
            ]
        ]
    )
    runner = await open_runner(tmp_path, monkeypatch, provider, system="test")
    try:
        async for _ in runner.run("hi"):
            pass

        assert [message.role for message in runner.messages.data] == [
            "system",
            "user",
            "assistant",
            "assistant",
        ]
        assert all(message.message_id for message in runner.messages.data)
        assert runner.messages.data[1].turn_id == 1
        assert runner.messages.data[2].content.text == "let me think"
        assert runner.messages.data[2].turn_id == 1
        assert runner.messages.data[3].content.text == "hello"
        assert runner.messages.data[3].turn_id == 1
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_runner_reuses_messages_across_runs(tmp_path, monkeypatch):
    provider = FakeProvider(
        [
            [FakeStreamChunk(content="one")],
            [FakeStreamChunk(content="two")],
        ]
    )
    runner = await open_runner(tmp_path, monkeypatch, provider, system="sys")
    try:
        async for _ in runner.run("hi"):
            pass
        async for _ in runner.run("again"):
            pass

        roles = [message.role for message in runner.messages.data]
        assert roles == ["system", "user", "assistant", "user", "assistant"]
        assert runner.messages.data[1].turn_id == 1
        assert runner.messages.data[2].turn_id == 1
        assert runner.messages.data[3].turn_id == 2
        assert runner.messages.data[4].turn_id == 2
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_runner_isolates_separate_threads(tmp_path, monkeypatch):
    provider = FakeProvider(
        [
            [FakeStreamChunk(content="a")],
            [FakeStreamChunk(content="b")],
        ]
    )
    monkeypatch.chdir(tmp_path)
    left = await Runner.create(
        "left",
        provider,
        overrides={"backend": "local"},
        extra_system="sys",
    )
    right = await Runner.create(
        "right",
        provider,
        overrides={"backend": "local"},
        extra_system="sys",
    )
    try:
        async for _ in left.run("hi"):
            pass
        async for _ in right.run("hi"):
            pass

        assert [m.role for m in left.messages.data] == ["system", "user", "assistant"]
        assert [m.role for m in right.messages.data] == ["system", "user", "assistant"]
        assert left.messages.data[-1].content.text == "a"
        assert right.messages.data[-1].content.text == "b"
    finally:
        await left.close()
        await right.close()


@pytest.mark.asyncio
async def test_run_yields_text(tmp_path, monkeypatch):
    provider = FakeProvider(
        [[FakeStreamChunk(content="he"), FakeStreamChunk(content="llo")]]
    )
    runner = await open_runner(tmp_path, monkeypatch, provider, system="s")
    try:
        chunks = []
        async for text in runner.run("hi", return_type="text"):
            chunks.append(text)
        assert "".join(chunks) == "hello"
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_run_calls_sync_event_handler(tmp_path, monkeypatch):
    provider = FakeProvider(
        [[FakeStreamChunk(content="he"), FakeStreamChunk(content="llo")]]
    )
    runner = await open_runner(tmp_path, monkeypatch, provider, system="s")
    seen: list[str] = []

    def handler(event):
        seen.append(type(event).__name__)

    try:
        async for _ in runner.run("hi", event_handler=handler):
            pass
        assert "TextDelta" in seen
        assert "RunBegin" in seen
        assert "RunEnd" in seen
        assert "TurnBegin" in seen
        assert "TurnEnd" in seen
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_run_awaits_async_event_handler(tmp_path, monkeypatch):
    provider = FakeProvider([[FakeStreamChunk(content="ok")]])
    runner = await open_runner(tmp_path, monkeypatch, provider, system="s")
    seen: list[str] = []

    async def handler(event):
        seen.append(type(event).__name__)

    try:
        async for _ in runner.run("hi", event_handler=handler):
            pass
        assert "TextDelta" in seen
    finally:
        await runner.close()


class FakeUsage(SimpleNamespace):
    pass


@pytest.mark.asyncio
async def test_turn_result_includes_usage_from_final_chunk(tmp_path, monkeypatch):
    provider = FakeProvider(
        [
            [
                FakeStreamChunk(content="hel"),
                FakeStreamChunk(content="lo"),
                FakeStreamChunk(
                    usage=FakeUsage(
                        prompt_tokens=120,
                        completion_tokens=8,
                        total_tokens=128,
                        prompt_tokens_details=SimpleNamespace(cached_tokens=96),
                    )
                ),
            ]
        ]
    )
    runner = await open_runner(tmp_path, monkeypatch, provider, system="test")
    turn_results: list[TurnResult] = []
    try:
        async for event in runner.run("hi"):
            if isinstance(event, TurnResult):
                turn_results.append(event)
    finally:
        await runner.close()

    assert len(turn_results) == 1
    assert turn_results[0].usage == {
        "prompt_tokens": 120,
        "completion_tokens": 8,
        "total_tokens": 128,
        "prompt_tokens_details": {"cached_tokens": 96},
    }


@pytest.mark.asyncio
async def test_turn_result_usage_none_without_usage_chunk(tmp_path, monkeypatch):
    provider = FakeProvider([[FakeStreamChunk(content="ok")]])
    runner = await open_runner(tmp_path, monkeypatch, provider, system="test")
    turn_results: list[TurnResult] = []
    try:
        async for event in runner.run("hi"):
            if isinstance(event, TurnResult):
                turn_results.append(event)
    finally:
        await runner.close()

    assert len(turn_results) == 1
    assert turn_results[0].usage is None


# ---------------------------------------------------------------------------
# Task 5: atomic runtime context replacement
# ---------------------------------------------------------------------------


def _make_dummy_tool(name: str) -> FunctionTool:
    async def noop() -> str:
        return ""

    return FunctionTool(
        name=name,
        description=f"Tool {name}",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        func=noop,
    )


class FakeProviderForContext:
    def __init__(self):
        self.calls = []

    async def complete(self, messages, tools=None, **run_kwargs):
        self.calls.append({"tools": tools, **run_kwargs})

        async def stream():
            if False:
                yield

        return stream()


def test_agent_replace_runtime_context_rebuilds_tool_schema_and_map():
    """replace_runtime_context updates tool_schemas and tool_map atomically."""
    t1 = _make_dummy_tool("alpha")
    t2 = _make_dummy_tool("beta")
    agent = AgentCore(FakeProviderForContext(), tools=[t1])

    agent.replace_runtime_context(tools=[t1, t2])
    assert sorted(agent.tool_map) == ["alpha", "beta"]
    assert agent.tool_schemas is not None
    schemas = agent.tool_schemas
    assert len(schemas) == 2


def test_agent_replace_runtime_context_rejects_duplicate_tools_atomically():
    """Duplicate tool names raise ValueError without mutating agent state."""
    t1 = _make_dummy_tool("dup")
    t2 = _make_dummy_tool("dup2")
    agent = AgentCore(FakeProviderForContext(), tools=[t1, t2])

    old_system = agent.system
    old_tools = list(agent.tools)
    old_map = dict(agent.tool_map)
    old_schemas = agent.tool_schemas

    dupe_a = _make_dummy_tool("dup")
    dupe_b = _make_dummy_tool("dup")  # same name
    with pytest.raises(ValueError, match="duplicate tool names"):
        agent.replace_runtime_context(tools=[t1, t2, dupe_a, dupe_b])

    # State must be unchanged after error
    assert agent.system is old_system
    assert agent.tools == old_tools
    assert agent.tool_map == old_map
    assert agent.tool_schemas is old_schemas


def test_agent_replace_runtime_context_replaces_system():
    """replace_runtime_context with system= updates the system prompt."""
    agent = AgentCore(FakeProviderForContext(), system="old system")
    agent.replace_runtime_context(system="new system")
    assert agent.system == "new system"


def test_agent_replace_runtime_context_preserves_unchanged_system():
    """When system is None, the system prompt is left intact."""
    agent = AgentCore(FakeProviderForContext(), system="keep me")
    agent.replace_runtime_context(system=None)
    assert agent.system == "keep me"
