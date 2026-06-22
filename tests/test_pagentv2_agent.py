import pytest

from pagentv2 import Agent, Message, TurnResult, reply_text
from pagentv2.tool import tool


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
        self.choices = [type("Choice", (), {"delta": delta})()]
        self.usage = usage


class FakeProvider:
    def __init__(self, steps: list[list[FakeStreamChunk]]):
        self._steps = list(steps)
        self.calls: list[dict] = []

    async def complete(self, messages, tools=None, **run_kwargs):
        self.calls.append({"messages": messages, "tools": tools, **run_kwargs})
        chunks = self._steps.pop(0)

        async def stream():
            for chunk in chunks:
                yield chunk

        return stream()


@tool()
def echo(msg: str) -> str:
    """Echo.

    Args:
        msg: Text.
    """
    return f"echo:{msg}"


@pytest.mark.asyncio
async def test_agent_stream_messages():
    provider = FakeProvider(
        [
            [FakeStreamChunk(content="hel"), FakeStreamChunk(content="lo")],
        ]
    )
    agent = Agent(provider, system="test")

    chunks = [m async for m in agent.arun("hi", return_type="message")]
    texts = [
        m.content.text
        for m in chunks
        if m.role == "assistant" and m.content.type == "text"
    ]

    assert texts == ["hel", "lo"]
    assert (
        reply_text([m for m in agent.messages.data if m.role == "assistant"]) == "hello"
    )


@pytest.mark.asyncio
async def test_events_returns_turn_result():
    provider = FakeProvider([[FakeStreamChunk(content="hello")]])
    agent = Agent(provider, system="test")
    result = None
    async for event in agent.arun("hi"):
        if isinstance(event, TurnResult):
            result = event

    assert result is not None
    assert result.content == "hello"
    assert len(provider.calls) == 1
    assert provider.calls[0]["messages"][-1] == {"role": "user", "content": "hi"}


def test_reply_text():
    msgs = [
        Message.assistant({"type": "thinking", "text": "hmm"}),
        Message.assistant({"type": "text", "text": "ok"}),
    ]
    assert reply_text(msgs) == "ok"


@pytest.mark.asyncio
async def test_turn_result_after_stream_messages():
    provider = FakeProvider(
        [[FakeStreamChunk(content="a"), FakeStreamChunk(content="b")]]
    )
    agent = Agent(provider, system="test")

    async for _ in agent.arun("hi", return_type="message"):
        pass
    turn = TurnResult.from_slice(agent.messages.data, start=1)

    assert turn.content == "ab"


def test_turn_result_from_slice():
    messages = [
        Message.assistant({"type": "thinking", "text": "hmm"}),
        Message.assistant({"type": "text", "text": "ok"}),
    ]
    turn = TurnResult.from_slice(messages)
    assert turn.content == "ok"
    assert turn.reasoning_content == "hmm"


@pytest.mark.asyncio
async def test_message_mode_runs_tools_across_turns():
    tc = type(
        "ToolCallDelta",
        (),
        {
            "index": 0,
            "id": "c1",
            "type": "function",
            "function": type(
                "FunctionDelta",
                (),
                {"name": "echo", "arguments": '{"msg":"x"}'},
            )(),
        },
    )()
    provider = FakeProvider(
        [
            [FakeStreamChunk(tool_calls=[tc])],
            [FakeStreamChunk(content="done")],
        ]
    )
    agent = Agent(provider, system="test", tools=[echo], max_turns=4)

    messages = [m async for m in agent.arun("go", return_type="message")]

    assert [m.role for m in messages] == ["assistant", "tool", "assistant"]
    assert messages[0].content.type == "function"
    assert messages[1].content.type == "tool_result"
    assert messages[1].content.text == "echo:x"
    assert messages[2].content.type == "text"
    assert messages[2].content.text == "done"
    assert len(provider.calls) == 2
    assert [m.role for m in agent.messages.data] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
    ]


@pytest.mark.asyncio
async def test_message_mode_projects_reasoning_tool_and_text():
    tc = type(
        "ToolCallDelta",
        (),
        {
            "index": 0,
            "id": "c1",
            "type": "function",
            "function": type(
                "FunctionDelta",
                (),
                {"name": "echo", "arguments": '{"msg":"x"}'},
            )(),
        },
    )()
    provider = FakeProvider(
        [
            [FakeStreamChunk(reasoning="think"), FakeStreamChunk(tool_calls=[tc])],
            [FakeStreamChunk(content="done")],
        ]
    )
    agent = Agent(provider, system="test", tools=[echo], max_turns=4)

    messages = [m async for m in agent.arun("go", return_type="message")]

    assert [m.role for m in messages] == ["assistant", "assistant", "tool", "assistant"]
    assert messages[0].content.type == "thinking"
    assert messages[0].content.text == "think"
    assert messages[1].content.type == "function"
    assert messages[2].content.type == "tool_result"
    assert messages[2].content.text == "echo:x"
    assert messages[3].content.type == "text"
    assert messages[3].content.text == "done"


@pytest.mark.asyncio
async def test_arun_rejects_unknown_return_type_before_running():
    provider = FakeProvider([[FakeStreamChunk(content="unused")]])
    agent = Agent(provider, system="test")

    with pytest.raises(ValueError, match="unknown return_type"):
        async for _ in agent.arun("hi", return_type="bad"):  # type: ignore[arg-type]
            pass

    assert provider.calls == []
