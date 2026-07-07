import types
from types import SimpleNamespace

import pytest

from pagentv4 import (
    AgenticRunner,
    CodeAgent,
    RunConfig,
    SimpleQuestionAnswerRunner,
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
async def test_simple_question_answer_runner():
    provider = FakeProvider(
        [[FakeStreamChunk(content="two"), FakeStreamChunk(content=" opponents")]]
    )
    runner = SimpleQuestionAnswerRunner(
        RunConfig(provider=provider, system="answer briefly")
    )
    article = "The hero fought one foe, then another."
    answer = await runner.run(article + "\n\nHow many opponents did the hero defeat?")

    assert answer == "two opponents"


@pytest.mark.asyncio
async def test_agentic_runner_default_tools():
    tc = SimpleNamespace(
        index=0,
        id="c1",
        type="function",
        function=SimpleNamespace(name="echo", arguments='{"msg":"ping"}'),
    )
    provider = FakeProvider(
        [
            [FakeStreamChunk(tool_calls=[tc])],
            [FakeStreamChunk(content="done")],
        ]
    )
    runner = AgenticRunner(
        RunConfig(provider=provider, system="test", max_turns=4),
        tools=[echo],
    )
    answer = await runner.run("go")

    assert answer == "done"


@pytest.mark.asyncio
async def test_agentic_runner_per_run_tools():
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
    runner = AgenticRunner(RunConfig(provider=provider, system="test", max_turns=4))
    answer = await runner.run("go", tools=[echo])

    assert answer == "ok"


@pytest.mark.asyncio
async def test_code_agent(tmp_path, monkeypatch):
    provider = FakeProvider([[FakeStreamChunk(content="patched file")]])
    monkeypatch.setenv("PAGENT_THREADS_DIR", str(tmp_path))
    agent = CodeAgent(
        RunConfig(
            provider=provider,
            system="fix the bug",
            thread_id="code-test",
            backend="local",
            max_turns=2,
        )
    )
    try:
        answer = await agent.run("apply the SWE-bench patch")
        assert answer == "patched file"
        assert agent.runner.sandbox is not None
    finally:
        await agent.close()
