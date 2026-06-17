import pytest

from pagentv2 import Agent
from pagentv2.message import (
    ImageUrl,
    Message,
    Messages,
    TextChunk,
    ThinkingChunk,
    ToolCall,
    ToolResult,
)


class FakeStreamChunk:
    def __init__(self, *, content=None):
        delta = type("Delta", (), {"content": content})()
        self.choices = [type("Choice", (), {"delta": delta})()]


class FakeProvider:
    def __init__(self, steps: list[list[FakeStreamChunk]]):
        self._steps = list(steps)

    async def complete(self, messages, tools=None, **run_kwargs):
        chunks = self._steps.pop(0)

        async def stream():
            for chunk in chunks:
                yield chunk

        return stream()


def test_messages_to_openai_user_and_tool():
    msgs = Messages()
    msgs += Message(role="system", content=TextChunk(type="text", text="sys"))
    msgs += Message(role="user", content=TextChunk(type="text", text="hi"))
    msgs += Message(
        role="assistant",
        content=ToolCall(type="function", id="c1", name="echo", arguments='{"x":1}'),
    )
    msgs += Message(
        role="tool",
        content=ToolResult(type="tool_result", tool_call_id="c1", text="ok"),
    )

    api = msgs.to_openai()
    assert api == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "echo", "arguments": '{"x":1}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
    ]


def test_messages_to_openai_merges_assistant_chunks():
    msgs = Messages()
    msgs += Message(
        role="assistant", content=ThinkingChunk(type="thinking", text="hmm")
    )
    msgs += Message(role="assistant", content=TextChunk(type="text", text="hi"))
    msgs += Message(
        role="assistant",
        content=ToolCall(type="function", id="c2", name="f", arguments="{}"),
    )

    api = msgs.to_openai()
    assert len(api) == 1
    assert api[0]["content"] == "hi"
    assert api[0]["reasoning_content"] == "hmm"
    assert api[0]["tool_calls"][0]["id"] == "c2"


def test_tool_result_message():
    msgs = Messages()
    msgs += Message.assistant({"type": "text", "text": "answer"})
    msgs += Message.tool_result("c1", "done")
    assert isinstance(msgs.data[-1].content, ToolResult)
    assert msgs.data[-1].content.tool_call_id == "c1"


def test_messages_to_openai_user_image():
    msgs = Messages()
    msgs += Message.user("what is in this image?")
    msgs += Message.user_image("https://example.com/cat.png")

    api = msgs.to_openai()
    assert api == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "what is in this image?"},
                {
                    "type": "image_url",
                    "image_url": {"url": "https://example.com/cat.png"},
                },
            ],
        }
    ]


def test_image_url_rejected_on_assistant():
    with pytest.raises(ValueError, match="assistant message"):
        Message(role="assistant", content=ImageUrl(type="image_url", url="http://x"))


@pytest.mark.asyncio
async def test_stream_messages_yields_text_chunks():
    provider = FakeProvider(
        [
            [FakeStreamChunk(content="图 "), FakeStreamChunk(content="http://x.png")],
        ]
    )
    agent = Agent(provider, system="test")

    chunks = [m.content async for m in agent.arun("hi", return_type="message")]
    assert len(chunks) == 2
    assert all(isinstance(c, TextChunk) for c in chunks)
    assert "".join(c.text for c in chunks) == "图 http://x.png"
