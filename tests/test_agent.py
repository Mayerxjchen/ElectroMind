import asyncio
from types import SimpleNamespace

import pytest

from pagent import Agent, RunResult, Session, tool


@tool()
def echo(msg: str) -> str:
    """Echo.

    Args:
        msg: Text.
    """
    return f"echo:{msg}"


class FakeLLM:
    def __init__(self, results):
        self._results = list(results)
        self.invoke_calls = []

    async def invoke(self, messages, tools=None, **run_kwargs):
        self.invoke_calls.append((list(messages), tools, run_kwargs))
        return self._results.pop(0)


class FakeStreamLLM:
    def __init__(self, turns):
        self._turns = [list(chunks) for chunks in turns]
        self.invoke_stream_calls = []

    async def invoke_stream(self, messages, tools=None, **run_kwargs):
        self.invoke_stream_calls.append((list(messages), tools, run_kwargs))
        chunks = self._turns.pop(0)
        for chunk in chunks:
            yield chunk


def make_chunk(content=None, tool_calls=None, usage=None, reasoning_content=None):
    delta = SimpleNamespace(
        content=content, tool_calls=tool_calls, reasoning_content=reasoning_content
    )
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=usage)


def test_agent_rejects_duplicate_tool_names():
    @tool(name="same")
    def a():
        """A."""
        return "a"

    @tool(name="same")
    def b():
        """B."""
        return "b"

    with pytest.raises(ValueError, match="duplicate"):
        Agent(FakeLLM([]), Session(""), tools=[a, b])


def test_agent_single_turn_no_tools():
    llm = FakeLLM([RunResult(content="ok", tool_calls=[])])
    session = Session("sys")
    agent = Agent(llm, session, tools=[], max_turns=4)
    out = asyncio.run(agent.run("hello"))
    assert out.content == "ok"
    assert agent.stats.turns == 1
    first_msgs, first_tools, first_kwargs = llm.invoke_calls[0]
    assert first_msgs[-1]["role"] == "user"
    assert first_msgs[0]["role"] == "system"
    assert first_kwargs == {}


def test_agent_tool_round_trip():
    tool_call = {
        "id": "c1",
        "type": "function",
        "function": {"name": "echo", "arguments": '{"msg":"hi"}'},
    }
    llm = FakeLLM(
        [
            RunResult(content="", tool_calls=[tool_call]),
            RunResult(content="done", tool_calls=[]),
        ]
    )
    session = Session("")
    agent = Agent(llm, session, tools=[echo], max_turns=4)
    out = asyncio.run(agent.run("go"))
    assert out.content == "done"
    assert agent.stats.turns == 2
    tool_msgs = [m for m in session.messages if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["content"] == "echo:hi"


def test_agent_unknown_tool():
    tool_call = {
        "id": "c1",
        "type": "function",
        "function": {"name": "missing", "arguments": "{}"},
    }
    llm = FakeLLM(
        [
            RunResult(content="", tool_calls=[tool_call]),
            RunResult(content="sorry", tool_calls=[]),
        ]
    )
    agent = Agent(llm, Session(""), tools=[], max_turns=4)
    out = asyncio.run(agent.run("x"))
    assert out.content == "sorry"
    assert "unknown tool" in llm.invoke_calls[1][0][-1]["content"]


def test_agent_keeps_reasoning_content_in_session():
    llm = FakeLLM([RunResult(content="ok", reasoning_content="think", tool_calls=[])])
    session = Session("")
    agent = Agent(llm, session, tools=[], max_turns=2)
    out = asyncio.run(agent.run("hello"))
    assert out.content == "ok"
    assert session.messages[-1]["reasoning_content"] == "think"


def test_agent_arun_stream_plain_text():
    llm = FakeStreamLLM(
        [
            [
                make_chunk(content="he"),
                make_chunk(content="llo"),
            ]
        ]
    )
    agent = Agent(llm, Session(""), tools=[], max_turns=2)

    async def collect():
        out = []
        async for token in agent.arun("say hello"):
            out.append(token)
        return out

    tokens = asyncio.run(collect())
    assert tokens == ["he", "llo"]
    assert agent.session.messages[-1] == {"role": "assistant", "content": "hello"}
    assert agent.stats.turns == 1


def test_agent_arun_stream_with_tool_call():
    tc_1 = SimpleNamespace(
        index=0,
        id="c1",
        type="function",
        function=SimpleNamespace(name="echo", arguments='{"msg":"'),
    )
    tc_2 = SimpleNamespace(
        index=0,
        id=None,
        type=None,
        function=SimpleNamespace(name=None, arguments='hi"}'),
    )
    llm = FakeStreamLLM(
        [
            [
                make_chunk(tool_calls=[tc_1]),
                make_chunk(tool_calls=[tc_2]),
            ],
            [
                make_chunk(content="done"),
            ],
        ]
    )
    session = Session("")
    agent = Agent(llm, session, tools=[echo], max_turns=4)

    async def collect():
        out = []
        async for token in agent.arun("go"):
            out.append(token)
        return out

    tokens = asyncio.run(collect())
    assert tokens == ["done"]
    tool_msgs = [m for m in session.messages if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["content"] == "echo:hi"
    assert agent.stats.turns == 2


def test_agent_deepseek_v4_pro_reasoning():
    """Simulate deepseek-v4-pro: returns reasoning_content then final answer."""
    reasoning = (
        "Let me think about this step by step.\n"
        "1. The user asks a simple math question: 2 + 3.\n"
        "2. 2 + 3 = 5.\n"
        "3. The answer is 5."
    )
    llm = FakeLLM(
        [RunResult(content="2 + 3 = 5", reasoning_content=reasoning, tool_calls=[])]
    )
    session = Session("You are a helpful assistant.")
    agent = Agent(llm, session, tools=[], max_turns=2)
    out = asyncio.run(agent.run("2 + 3 = ?"))
    assert out.content == "2 + 3 = 5"
    assert out.reasoning_content == reasoning
    assistant_msg = session.messages[-1]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["reasoning_content"] == reasoning
    assert assistant_msg["content"] == "2 + 3 = 5"


def test_agent_arun_stream_deepseek_v4_pro_reasoning():
    """Simulate deepseek-v4-pro streaming: reasoning chunks arrive first, then content."""
    llm = FakeStreamLLM(
        [
            [
                make_chunk(reasoning_content="Let me think... "),
                make_chunk(reasoning_content="2 + 3 = 5. "),
                make_chunk(reasoning_content="So the answer is 5."),
                make_chunk(content="2 + 3 = 5"),
            ]
        ]
    )
    agent = Agent(llm, Session(""), tools=[], max_turns=2)

    async def collect():
        out = []
        async for token in agent.arun("2 + 3 = ?"):
            out.append(token)
        return out

    tokens = asyncio.run(collect())
    assert tokens == ["2 + 3 = 5"]
    assistant_msg = agent.session.messages[-1]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["content"] == "2 + 3 = 5"
    assert (
        assistant_msg["reasoning_content"]
        == "Let me think... 2 + 3 = 5. So the answer is 5."
    )


def test_agent_run_passes_reasoning_effort():
    llm = FakeLLM([RunResult(content="ok", tool_calls=[])])
    agent = Agent(llm, Session(""), tools=[], max_turns=2)
    out = asyncio.run(agent.run("hello", reasoning_effort="low"))
    assert out.content == "ok"
    assert llm.invoke_calls[0][2] == {"reasoning_effort": "low"}


def test_agent_run_without_run_kwargs_is_empty():
    llm = FakeLLM([RunResult(content="ok", tool_calls=[])])
    agent = Agent(llm, Session(""), tools=[], max_turns=2)
    asyncio.run(agent.run("hello"))
    assert llm.invoke_calls[0][2] == {}


def test_agent_arun_passes_run_kwargs():
    llm = FakeStreamLLM([[make_chunk(content="ok")]])
    agent = Agent(llm, Session(""), tools=[], max_turns=2)

    async def collect():
        out = []
        async for token in agent.arun("hello", reasoning_effort=0.5, temperature=0.7):
            out.append(token)
        return out

    asyncio.run(collect())
    assert llm.invoke_stream_calls[0][2] == {
        "reasoning_effort": 0.5,
        "temperature": 0.7,
    }


def test_llm_rejects_reserved_run_kwargs():
    from pagent.llm import check_run_kwargs

    with pytest.raises(TypeError, match="reserved"):
        check_run_kwargs({"model": "hacked"})

    with pytest.raises(TypeError, match="reserved"):
        check_run_kwargs({"stream": True})

    with pytest.raises(TypeError, match="reserved"):
        check_run_kwargs({"reasoning_effort": "low", "messages": []})

    # non-reserved keys pass silently
    check_run_kwargs({"reasoning_effort": "low", "temperature": 0.5})
