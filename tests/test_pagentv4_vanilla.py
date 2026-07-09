import types
from types import SimpleNamespace

import pytest

from pagentv4 import (
    Agent,
    AgentRunner,
    Message,
    Messages,
    RunEnd,
    TextDelta,
    ToolCall,
    ToolCallBegin,
    ToolResult,
    TurnResult,
    VanillaAgent,
    VanillaRunner,
    tool,
)


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
        del messages, tools, run_kwargs
        chunks = self.steps.pop(0)

        async def stream():
            for chunk in chunks:
                yield chunk

        return stream()


@tool()
def echo(msg: str) -> str:
    """Echo back."""
    return msg


@pytest.mark.asyncio
async def test_max_turns_grants_synthesis_turn():
    tc = SimpleNamespace(
        index=0,
        id="c1",
        type="function",
        function=SimpleNamespace(name="echo", arguments='{"msg":"ping"}'),
    )
    provider = FakeProvider(
        [
            [FakeStreamChunk(tool_calls=[tc])],
            [FakeStreamChunk(content="579")],
        ]
    )
    runner = VanillaRunner(
        Agent(
            provider,
            system="test",
            tools=[echo],
            max_turns=1,
        )
    )
    answer = [text async for text in runner.run("solve", return_type="text")]
    assert "".join(answer) == "579"


def test_turn_result_keeps_typed_tool_calls():
    messages = Messages()
    messages += Message.assistant(
        {
            "type": "function",
            "id": "c1",
            "name": "echo",
            "arguments": '{"msg":"ping"}',
        }
    )

    result = TurnResult.from_slice(messages.data)

    assert isinstance(result.tool_calls[0], ToolCall)
    assert result.tool_calls[0].id == "c1"
    assert result.tool_calls[0].name == "echo"


def test_vanilla_runner_implements_agent_runner_protocol():
    runner = VanillaRunner(Agent(FakeProvider([]), system="test"))

    assert isinstance(runner, AgentRunner)


def test_vanilla_agent_alias_points_to_vanilla_runner():
    assert VanillaAgent is VanillaRunner


@pytest.mark.asyncio
async def test_vanilla_runner_does_not_execute_tools_requested_by_synthesis_turn():
    calls = []

    @tool()
    def record(value: str) -> str:
        """Record a value."""
        calls.append(value)
        return value

    first_call = SimpleNamespace(
        index=0,
        id="c1",
        type="function",
        function=SimpleNamespace(name="echo", arguments='{"msg":"ping"}'),
    )
    synthesis_call = SimpleNamespace(
        index=0,
        id="c2",
        type="function",
        function=SimpleNamespace(name="record", arguments='{"value":"late"}'),
    )
    provider = FakeProvider(
        [
            [FakeStreamChunk(tool_calls=[first_call])],
            [FakeStreamChunk(tool_calls=[synthesis_call])],
        ]
    )
    runner = VanillaRunner(
        Agent(
            provider,
            system="test",
            tools=[echo, record],
            max_turns=1,
        )
    )

    parts = []
    async for text in runner.run("solve", return_type="text"):
        parts.append(text)

    assert "".join(parts) == ""
    assert calls == []


@pytest.mark.asyncio
async def test_vanilla_runner_supports_return_type_projections():
    tc = SimpleNamespace(
        index=0,
        id="c1",
        type="function",
        function=SimpleNamespace(name="echo", arguments='{"msg":"ping"}'),
    )
    provider = FakeProvider(
        [
            [FakeStreamChunk(content="checking", tool_calls=[tc])],
            [FakeStreamChunk(content="done")],
        ]
    )
    runner = VanillaRunner(
        Agent(
            provider,
            system="test",
            tools=[echo],
            max_turns=4,
        )
    )

    events = [event async for event in runner.run("go", return_type="event")]

    assert any(
        isinstance(event, TextDelta) and event.text == "checking" for event in events
    )
    assert any(
        isinstance(event, ToolCallBegin) and event.tool_call_id == "c1"
        for event in events
    )
    assert any(
        isinstance(event, ToolResult) and event.tool_call_id == "c1" for event in events
    )
    assert any(
        isinstance(event, TextDelta) and event.text == "done" for event in events
    )

    provider = FakeProvider([[FakeStreamChunk(content="hi")]])
    runner = VanillaRunner(Agent(provider, system="test"))
    text = [chunk async for chunk in runner.run("go", return_type="text")]
    assert text == ["hi"]

    provider = FakeProvider([[FakeStreamChunk(content="hi")]])
    runner = VanillaRunner(Agent(provider, system="test"))
    messages = [message async for message in runner.run("go", return_type="message")]
    assert messages[-1].role == "assistant"
    assert messages[-1].content.text == "hi"

    provider = FakeProvider([[FakeStreamChunk(content="hi")]])
    runner = VanillaRunner(Agent(provider, system="test"))
    acp = [line async for line in runner.run("go", return_type="acp")]
    assert any('"method": "TextDelta"' in line for line in acp)


@pytest.mark.asyncio
async def test_vanilla_runner_emits_run_end():
    provider = FakeProvider([[FakeStreamChunk(content="hi")]])
    runner = VanillaRunner(Agent(provider, system="test"))

    events = [event async for event in runner.run("go", return_type="event")]

    assert isinstance(events[-1], RunEnd)
    assert events[-1].stop_reason == "no_tool_calls"
