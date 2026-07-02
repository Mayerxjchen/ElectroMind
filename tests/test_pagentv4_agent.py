import pytest

from pagentv4 import Agent, Message, Messages, Runner, run_agent


class FakeStreamChunk:
    def __init__(self, *, content=None, reasoning=None, tool_calls=None):
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


@pytest.mark.asyncio
async def test_runner_populates_messages_with_system_prompt():
    provider = FakeProvider(
        [[FakeStreamChunk(content="hel"), FakeStreamChunk(content="lo")]]
    )
    agent = Agent(provider, system="test")
    runner = Runner()
    messages = Messages()

    async for _ in runner.arun(agent, "hi", messages):
        pass

    assert [message.role for message in messages.data] == [
        "system",
        "user",
        "assistant",
    ]
    assert len({message.message_id for message in messages.data}) == len(messages.data)
    assert messages.data[0].turn_id == 0
    assert messages.data[1].turn_id == 1
    assert messages.data[2].turn_id == 1
    assert messages.data[-1].content.text == "hello"


@pytest.mark.asyncio
async def test_runner_keeps_existing_messages():
    messages = Messages()
    messages += Message.system("test")
    messages += Message.user("earlier", turn_id=1)
    messages += Message.assistant({"type": "text", "text": "done"}, turn_id=1)
    existing_messages = list(messages.data)

    provider = FakeProvider([[FakeStreamChunk(content="done")]])
    agent = Agent(provider)
    runner = Runner()

    async for _ in runner.arun(agent, "next", messages):
        pass

    assert messages.data[:3] == existing_messages
    assert provider.calls[0]["messages"][0] == {"role": "system", "content": "test"}
    assert provider.calls[0]["messages"][1] == {
        "role": "user",
        "content": "earlier",
    }
    assert provider.calls[0]["messages"][2] == {"role": "assistant", "content": "done"}
    assert provider.calls[0]["messages"][3] == {"role": "user", "content": "next"}
    assert messages.data[3].turn_id == 2
    assert messages.data[4].turn_id == 2


@pytest.mark.asyncio
async def test_runner_accumulates_assistant_chunks_in_messages():
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
    agent = Agent(provider, system="test")
    runner = Runner()
    messages = Messages()

    async for _ in runner.arun(agent, "hi", messages):
        pass

    assert [message.role for message in messages.data] == [
        "system",
        "user",
        "assistant",
        "assistant",
    ]
    assert all(message.message_id for message in messages.data)
    assert messages.data[1].turn_id == 1
    assert messages.data[2].content.text == "let me think"
    assert messages.data[2].turn_id == 1
    assert messages.data[3].content.text == "hello"
    assert messages.data[3].turn_id == 1


@pytest.mark.asyncio
async def test_runner_reuses_messages_across_runs():
    provider = FakeProvider(
        [
            [FakeStreamChunk(content="one")],
            [FakeStreamChunk(content="two")],
        ]
    )
    agent = Agent(provider, system="sys")
    runner = Runner()
    messages = Messages()

    async for _ in runner.arun(agent, "hi", messages):
        pass
    async for _ in runner.arun(agent, "again", messages):
        pass

    roles = [message.role for message in messages.data]
    assert roles == ["system", "user", "assistant", "user", "assistant"]
    assert messages.data[1].turn_id == 1
    assert messages.data[2].turn_id == 1
    assert messages.data[3].turn_id == 2
    assert messages.data[4].turn_id == 2


@pytest.mark.asyncio
async def test_runner_isolates_separate_message_containers():
    provider = FakeProvider(
        [
            [FakeStreamChunk(content="a")],
            [FakeStreamChunk(content="b")],
        ]
    )
    agent = Agent(provider, system="sys")
    runner = Runner()
    left = Messages()
    right = Messages()

    async for _ in runner.arun(agent, "hi", left):
        pass
    async for _ in runner.arun(agent, "hi", right):
        pass

    assert [m.role for m in left.data] == ["system", "user", "assistant"]
    assert [m.role for m in right.data] == ["system", "user", "assistant"]
    assert left.data[-1].content.text == "a"
    assert right.data[-1].content.text == "b"


@pytest.mark.asyncio
async def test_runner_shared_across_agents():
    provider_a = FakeProvider([[FakeStreamChunk(content="from-a")]])
    provider_b = FakeProvider([[FakeStreamChunk(content="from-b")]])
    agent_a = Agent(provider_a, system="A")
    agent_b = Agent(provider_b, system="B")
    runner = Runner()

    messages_a = Messages()
    messages_b = Messages()

    async for _ in runner.arun(agent_a, "hi", messages_a):
        pass
    async for _ in runner.arun(agent_b, "hi", messages_b):
        pass

    assert messages_a.data[0].content.text == "A"
    assert messages_b.data[0].content.text == "B"
    assert messages_a.data[-1].content.text == "from-a"
    assert messages_b.data[-1].content.text == "from-b"


@pytest.mark.asyncio
async def test_run_agent_helper_yields_text():
    provider = FakeProvider(
        [[FakeStreamChunk(content="he"), FakeStreamChunk(content="llo")]]
    )
    agent = Agent(provider, system="s")

    chunks = []
    async for text in run_agent(agent, "hi", return_type="text"):
        chunks.append(text)

    assert "".join(chunks) == "hello"


@pytest.mark.asyncio
async def test_arun_calls_sync_event_handler():
    provider = FakeProvider(
        [[FakeStreamChunk(content="he"), FakeStreamChunk(content="llo")]]
    )
    agent = Agent(provider, system="s")
    runner = Runner()
    messages = Messages()

    seen: list[str] = []

    def handler(event):
        seen.append(type(event).__name__)

    async for _ in runner.arun(agent, "hi", messages, event_handler=handler):
        pass

    assert "TextDelta" in seen
    assert "RunBegin" in seen
    assert "TurnBegin" in seen
    assert "TurnEnd" in seen


@pytest.mark.asyncio
async def test_arun_awaits_async_event_handler():
    provider = FakeProvider([[FakeStreamChunk(content="ok")]])
    agent = Agent(provider, system="s")
    runner = Runner()
    messages = Messages()

    seen: list[str] = []

    async def handler(event):
        seen.append(type(event).__name__)

    async for _ in runner.arun(agent, "hi", messages, event_handler=handler):
        pass

    assert "TextDelta" in seen
