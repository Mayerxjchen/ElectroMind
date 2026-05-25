import asyncio
import json

from pagent import CompactingSession, RunResult, compactor
from pagent.tokens import count_tokens


class FakeLLM:
    def __init__(self, results):
        self._results = list(results)
        self.invoke_calls = []

    async def invoke(self, messages, tools=None, **run_kwargs):
        self.invoke_calls.append((list(messages), tools, run_kwargs))
        return self._results.pop(0)


def test_compactor_returns_agent():
    llm = FakeLLM([RunResult(content="summary text", tool_calls=[])])
    agent = compactor(llm)
    out = asyncio.run(agent.run("history blob"))
    assert out.content == "summary text"
    assert llm.invoke_calls[0][0][0]["role"] == "system"
    assert "conversation compactor" in llm.invoke_calls[0][0][0]["content"]


def test_compact_replaces_conversation_keeps_system():
    llm = FakeLLM([RunResult(content="User asked about X.", tool_calls=[])])
    session = CompactingSession("SYS", llm=llm)
    session += {"role": "user", "content": "long " * 50}
    session += {"role": "assistant", "content": "reply " * 50}

    asyncio.run(session.compact())

    assert session.messages == [
        {"role": "system", "content": "SYS"},
        {
            "role": "user",
            "content": "[Previous conversation summary]\nUser asked about X.",
        },
    ]
    assert llm.invoke_calls[0][0][-1]["role"] == "user"
    history = json.loads(llm.invoke_calls[0][0][-1]["content"])
    assert len(history) == 2


def test_compact_empty_conversation_is_noop():
    llm = FakeLLM([RunResult(content="unused", tool_calls=[])])
    session = CompactingSession("SYS", llm=llm)
    asyncio.run(session.compact())
    assert session.messages == [{"role": "system", "content": "SYS"}]
    assert llm.invoke_calls == []


def test_should_compact_when_over_threshold():
    llm = FakeLLM([RunResult(content="ok", tool_calls=[])])
    session = CompactingSession("", llm=llm, compact_at_tokens=10)
    session += {"role": "user", "content": "x" * 200}
    assert count_tokens(session.messages) > 10
    assert session.should_compact is True


def test_should_compact_false_without_threshold():
    llm = FakeLLM([])
    session = CompactingSession("", llm=llm)
    session += {"role": "user", "content": "x" * 200}
    assert session.should_compact is False
