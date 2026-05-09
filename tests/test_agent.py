import asyncio

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

    async def invoke(self, messages, tools=None):
        self.invoke_calls.append((list(messages), tools))
        return self._results.pop(0)


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
    first_msgs = llm.invoke_calls[0][0]
    assert first_msgs[-1]["role"] == "user"
    assert first_msgs[0]["role"] == "system"


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
