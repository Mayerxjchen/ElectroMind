from types import SimpleNamespace

import pytest
from acp import text_block

from pagent_acp.adapter import PagentACPAgent, prompt_to_text
from pagentv2 import Agent, TextChunk, ToolCallBegin, ToolResult, TurnEnd, TurnResult
from pagentv2.acp_adapter import decode_event_line
from pagentv2.tool import tool


class FakeStreamChunk:
    def __init__(self, *, content=None, reasoning=None, tool_calls=None, usage=None):
        delta = SimpleNamespace(
            content=content,
            reasoning_content=reasoning,
            tool_calls=tool_calls,
        )
        self.choices = [SimpleNamespace(delta=delta)]
        self.usage = usage


class FakeProvider:
    def __init__(self, steps: list[list[FakeStreamChunk]]):
        self._steps = list(steps)

    async def complete(self, messages, tools=None, **run_kwargs):
        chunks = self._steps.pop(0)

        async def stream():
            for chunk in chunks:
                yield chunk

        return stream()


class RecordingClient:
    def __init__(self):
        self.updates: list[tuple[str, object]] = []

    async def session_update(self, session_id, update, **kwargs):
        self.updates.append((session_id, update))


@tool()
def echo(msg: str) -> str:
    """Echo.

    Args:
        msg: Text.
    """
    return f"echo:{msg}"


def make_v2_agent(_cwd: str) -> Agent:
    return Agent(
        FakeProvider([[FakeStreamChunk(content="Hi")]]),
        system="test",
    )


@pytest.mark.asyncio
async def test_acp_v2_prompt_streams_text():
    client = RecordingClient()
    acp = PagentACPAgent(make_v2_agent)
    acp.on_connect(client)
    session = await acp.new_session(cwd="/tmp")
    await acp.prompt([text_block("Hello")], session_id=session.session_id)

    chunks = [u for _, u in client.updates if u.session_update == "agent_message_chunk"]
    assert "".join(c.content.text for c in chunks) == "Hi"


@pytest.mark.asyncio
async def test_acp_v2_prompt_tool_calls():
    tc_delta = SimpleNamespace(
        index=0,
        id="tc1",
        type="function",
        function=SimpleNamespace(name="echo", arguments='{"msg":"x"}'),
    )
    provider = FakeProvider(
        [
            [FakeStreamChunk(tool_calls=[tc_delta])],
            [FakeStreamChunk(content="done")],
        ]
    )

    def factory(_cwd: str) -> Agent:
        return Agent(provider, system="test", tools=[echo])

    client = RecordingClient()
    acp = PagentACPAgent(factory)
    acp.on_connect(client)
    session = await acp.new_session(cwd="/tmp")
    await acp.prompt([text_block("go")], session_id=session.session_id)

    kinds = [u.session_update for _, u in client.updates]
    assert "tool_call" in kinds
    assert "tool_call_update" in kinds


@pytest.mark.asyncio
async def test_arun_splits_reasoning_and_text():
    provider = FakeProvider(
        [
            [
                FakeStreamChunk(reasoning="think-"),
                FakeStreamChunk(reasoning="ing"),
                FakeStreamChunk(content="ans"),
                FakeStreamChunk(content="wer"),
            ]
        ]
    )
    agent = Agent(provider, system="test")

    events = [e async for e in agent.arun("hi")]
    kinds = [type(e).__name__ for e in events]
    assert kinds.count("ReasoningDelta") == 2
    assert kinds.count("TextDelta") == 2
    assert (
        "".join(e.text for e in events if type(e).__name__ == "ReasoningDelta")
        == "think-ing"
    )
    assert (
        "".join(e.text for e in events if type(e).__name__ == "TextDelta") == "answer"
    )

    chunks = [m.content for m in agent.messages.data if m.role == "assistant"]
    assert [c.type for c in chunks] == ["thinking", "thinking", "text", "text"]


@pytest.mark.asyncio
async def test_events_plain_text():
    provider = FakeProvider([[FakeStreamChunk(content="hi")]])
    agent = Agent(provider, system="test")

    events = [e async for e in agent.arun("hello")]
    kinds = [type(e).__name__ for e in events]
    assert kinds == [
        "RunBegin",
        "TurnBegin",
        "TextDelta",
        "TurnResult",
        "TurnEnd",
    ]
    assert events[0].user_input == "hello"
    assert events[2].text == "hi"
    assert events[3].content == "hi"
    assert events[4].stopped is True
    assert events[4].stop_reason == "no_tool_calls"


@pytest.mark.asyncio
async def test_events_with_tools():
    tc = SimpleNamespace(
        index=0,
        id="c1",
        type="function",
        function=SimpleNamespace(name="echo", arguments='{"msg":"x"}'),
    )
    provider = FakeProvider(
        [
            [FakeStreamChunk(tool_calls=[tc])],
            [FakeStreamChunk(content="ok")],
        ]
    )
    agent = Agent(provider, system="test", tools=[echo], max_turns=4)

    events = [e async for e in agent.arun("go")]
    assert any(isinstance(e, ToolCallBegin) and e.name == "echo" for e in events)
    tr = next(e for e in events if isinstance(e, ToolResult))
    assert tr.content == "echo:x"
    assert tr.ok is True
    assert events[-1].stopped is True
    assert events[-1].stop_reason == "no_tool_calls"
    last_turn = next(e for e in reversed(events) if isinstance(e, TurnResult))
    assert last_turn.content == "ok"


@pytest.mark.asyncio
async def test_text_yields_text_only():
    provider = FakeProvider(
        [[FakeStreamChunk(content="he"), FakeStreamChunk(content="llo")]]
    )
    agent = Agent(provider, system="test")

    parts = [t async for t in agent.arun("say", return_type="text")]
    assert "".join(parts) == "hello"


@pytest.mark.asyncio
async def test_acp_adapter_matches_events():
    provider = FakeProvider([[FakeStreamChunk(content="hi")]])
    agent = Agent(provider, system="test")

    lines = [line async for line in agent.arun("hello", return_type="acp")]
    events = [decode_event_line(line) for line in lines]
    kinds = [type(e).__name__ for e in events]
    assert "TextDelta" in kinds
    assert kinds[-1] == "TurnEnd"


@pytest.mark.asyncio
async def test_stream_messages():
    provider = FakeProvider(
        [[FakeStreamChunk(content="hel"), FakeStreamChunk(content="lo")]]
    )
    agent = Agent(provider, system="test")

    chunks = [m async for m in agent.arun("hi", return_type="message")]
    texts = [m.content.text for m in chunks if isinstance(m.content, TextChunk)]
    assert texts == ["hel", "lo"]


@pytest.mark.asyncio
async def test_events_turn_result_with_tools():
    tc = SimpleNamespace(
        index=0,
        id="c1",
        type="function",
        function=SimpleNamespace(name="echo", arguments='{"msg":"x"}'),
    )
    provider = FakeProvider(
        [
            [FakeStreamChunk(tool_calls=[tc])],
            [FakeStreamChunk(content="ok")],
        ]
    )
    agent = Agent(provider, system="test", tools=[echo], max_turns=4)
    result = None
    async for event in agent.arun("go"):
        if isinstance(event, TurnResult):
            result = event
    assert result is not None
    assert result.content == "ok"


@pytest.mark.asyncio
async def test_turn_end_continuing_after_tools():
    tc = SimpleNamespace(
        index=0,
        id="c1",
        type="function",
        function=SimpleNamespace(name="echo", arguments='{"msg":"x"}'),
    )
    provider = FakeProvider(
        [
            [FakeStreamChunk(tool_calls=[tc])],
            [FakeStreamChunk(content="ok")],
        ]
    )
    agent = Agent(provider, system="test", tools=[echo], max_turns=4)

    turn_ends = [e async for e in agent.arun("go") if isinstance(e, TurnEnd)]

    assert len(turn_ends) == 2
    assert turn_ends[0].stopped is False
    assert turn_ends[0].stop_reason == "continuing"
    assert turn_ends[1].stopped is True
    assert turn_ends[1].stop_reason == "no_tool_calls"


@pytest.mark.asyncio
async def test_turn_end_max_turns():
    tc = SimpleNamespace(
        index=0,
        id="c1",
        type="function",
        function=SimpleNamespace(name="echo", arguments='{"msg":"x"}'),
    )
    provider = FakeProvider([[FakeStreamChunk(tool_calls=[tc])]])
    agent = Agent(provider, system="test", tools=[echo], max_turns=1)

    turn_ends = [e async for e in agent.arun("go") if isinstance(e, TurnEnd)]

    assert len(turn_ends) == 1
    assert turn_ends[0].stopped is True
    assert turn_ends[0].stop_reason == "max_turns"


def test_prompt_to_text():
    assert prompt_to_text([text_block("a"), text_block("b")]) == "a\nb"
