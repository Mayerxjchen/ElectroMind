import pytest

from pagentv3 import Agent, JsonlBackend, Message, Messages, Persistence


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
async def test_agent_persists_messages_with_auto_created_conversation(tmp_path):
    persistence = Persistence(JsonlBackend(tmp_path))
    provider = FakeProvider(
        [[FakeStreamChunk(content="hel"), FakeStreamChunk(content="lo")]]
    )
    agent = Agent(provider, persistence=persistence, system="test")

    assert agent.conversation_id

    async for _ in agent.arun("hi"):
        pass

    restored = persistence.load_messages(agent.conversation_id)
    assert restored == agent.messages
    assert [message.role for message in restored.data] == [
        "system",
        "user",
        "assistant",
    ]
    assert len({message.message_id for message in restored.data}) == len(restored.data)
    assert restored.data[0].turn_id == 0
    assert restored.data[1].turn_id == 1
    assert restored.data[2].turn_id == 1
    assert restored.data[-1].content.text == "hello"


@pytest.mark.asyncio
async def test_agent_loads_messages_from_persistence_by_conversation_id(tmp_path):
    persistence = Persistence(JsonlBackend(tmp_path))
    conversation_id = persistence.create_conversation()
    messages = Messages()
    messages += Message.system("test")
    messages += Message.user("earlier", turn_id=1)
    messages += Message.assistant({"type": "text", "text": "done"}, turn_id=1)
    persistence.save_messages(conversation_id, messages)

    provider = FakeProvider([[FakeStreamChunk(content="done")]])
    agent = Agent(
        provider,
        persistence=persistence,
        conversation_id=conversation_id,
    )

    async for _ in agent.arun("next"):
        pass

    assert agent.messages.data[:3] == messages.data
    assert provider.calls[0]["messages"][0] == {"role": "system", "content": "test"}
    assert provider.calls[0]["messages"][1] == {
        "role": "user",
        "content": "earlier",
    }
    assert provider.calls[0]["messages"][2] == {"role": "assistant", "content": "done"}
    assert provider.calls[0]["messages"][3] == {"role": "user", "content": "next"}
    assert agent.messages.data[3].turn_id == 2
    assert agent.messages.data[4].turn_id == 2


@pytest.mark.asyncio
async def test_agent_accumulates_assistant_chunks_in_messages(tmp_path):
    persistence = Persistence(JsonlBackend(tmp_path))
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
    agent = Agent(provider, persistence=persistence, system="test")

    async for _ in agent.arun("hi"):
        pass

    assert [message.role for message in agent.messages.data] == [
        "system",
        "user",
        "assistant",
        "assistant",
    ]
    assert all(message.message_id for message in agent.messages.data)
    assert agent.messages.data[1].turn_id == 1
    assert agent.messages.data[2].content.text == "let me think"
    assert agent.messages.data[2].turn_id == 1
    assert agent.messages.data[3].content.text == "hello"
    assert agent.messages.data[3].turn_id == 1
