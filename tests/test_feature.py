import asyncio

from pagent import JUDGER_SYSTEM, Agent, RunResult, Session


class FakeLLM:
    def __init__(self, results):
        self._results = list(results)

    async def invoke(self, messages, tools=None):
        del messages, tools
        return self._results.pop(0)


def test_agent_with_judger_system_prompt():
    llm = FakeLLM([RunResult(content="fail: wrong", tool_calls=[])])
    agent = Agent(llm, Session(JUDGER_SYSTEM), tools=[], max_turns=4)
    out = asyncio.run(agent.run("Is sqrt(2) rational?"))
    assert out.content == "fail: wrong"
    assert agent.session.messages[0]["role"] == "system"
    assert "impartial judge" in agent.session.messages[0]["content"]
