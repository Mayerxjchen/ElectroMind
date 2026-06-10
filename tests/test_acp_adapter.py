from types import SimpleNamespace

import pytest
from acp import text_block

from pagent import Agent, Session, tool
from pagent_acp.adapter import PagentACPAgent, prompt_to_text, tool_kind


@tool()
def echo(msg: str) -> str:
    """Echo.

    Args:
        msg: Text.
    """
    return f"echo:{msg}"


class FakeStreamLLM:
    def __init__(self, turns):
        self._turns = [list(chunks) for chunks in turns]

    async def invoke_stream(self, messages, tools=None, **run_kwargs):
        for chunk in self._turns.pop(0):
            yield chunk


def make_chunk(content=None, tool_calls=None, usage=None, reasoning_content=None):
    delta = SimpleNamespace(
        content=content, tool_calls=tool_calls, reasoning_content=reasoning_content
    )
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=usage)


class RecordingClient:
    def __init__(self):
        self.updates: list[tuple[str, object]] = []

    async def session_update(self, session_id, update, **kwargs):
        self.updates.append((session_id, update))


def make_agent(cwd: str) -> Agent:
    return Agent(
        llm=FakeStreamLLM([[make_chunk(content="Hi")]]),
        session=Session("test"),
        tools=[],
    )


@pytest.mark.asyncio
async def test_initialize():
    agent = PagentACPAgent(make_agent)
    resp = await agent.initialize(protocol_version=1)
    assert resp.protocol_version == 1
    assert resp.agent_info.name == "pagent"


@pytest.mark.asyncio
async def test_prompt_streams_text():
    client = RecordingClient()
    acp = PagentACPAgent(make_agent)
    acp.on_connect(client)
    session = await acp.new_session(cwd="/tmp")
    await acp.prompt([text_block("Hello")], session_id=session.session_id)

    chunks = [u for _, u in client.updates if u.session_update == "agent_message_chunk"]
    assert "".join(c.content.text for c in chunks) == "Hi"


@pytest.mark.asyncio
async def test_prompt_tool_calls():
    tc_delta = SimpleNamespace(
        index=0,
        id="tc1",
        type="function",
        function=SimpleNamespace(name="echo", arguments='{"msg":"x"}'),
    )
    llm = FakeStreamLLM(
        [
            [make_chunk(tool_calls=[tc_delta])],
            [make_chunk(content="done")],
        ]
    )

    def factory(_cwd: str) -> Agent:
        return Agent(llm=llm, session=Session("test"), tools=[echo])

    client = RecordingClient()
    acp = PagentACPAgent(factory)
    acp.on_connect(client)
    session = await acp.new_session(cwd="/tmp")
    await acp.prompt([text_block("go")], session_id=session.session_id)

    kinds = [u.session_update for _, u in client.updates]
    assert "tool_call" in kinds
    assert "tool_call_update" in kinds


def test_prompt_to_text():
    assert prompt_to_text([text_block("a"), text_block("b")]) == "a\nb"


def test_tool_kind_mapping():
    assert tool_kind("readfile") == "read"
    assert tool_kind("bash") == "execute"
    assert tool_kind("custom") == "other"
