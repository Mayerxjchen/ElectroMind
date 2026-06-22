import pytest

from pagentv2 import Agent, FunctionTool, ToolResult, to_openai_tools, tool


@tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@tool()
async def add_async(a: int, b: int) -> int:
    """Add two numbers asynchronously."""
    return a + b


@tool()
async def boom_async():
    raise RuntimeError("kaboom")


def test_tool_call_json_string():
    out = add.call('{"a": 2, "b": 3}')
    assert out.content == "5"
    assert out.ok is True


def test_tool_call_dict():
    out = add.call({"a": 1, "b": 1})
    assert out.content == "2"


def test_tool_call_invalid_json():
    out = add.call("{not json")
    assert out.ok is False
    assert "Invalid JSON" in out.content


def test_tool_no_func_errors():
    ft = FunctionTool("x", "", {"type": "object", "properties": {}})
    out = ft.call()
    assert out.ok is False
    assert "no bound function" in out.content


@tool()
def boom():
    raise RuntimeError("kaboom")


def test_tool_call_catches_exception():
    out = boom.call("{}")
    assert out.ok is False
    assert "kaboom" in out.content


def test_to_openai_tools():
    tools = to_openai_tools([add])
    assert tools[0]["function"]["name"] == "add"


@pytest.mark.asyncio
async def test_acall_async_tool():
    out = await add_async.acall('{"a": 2, "b": 3}')
    assert out.content == "5"
    assert out.ok is True


def test_call_rejects_async_tool():
    out = add_async.call('{"a": 1, "b": 2}')
    assert out.ok is False
    assert "async" in out.content


@pytest.mark.asyncio
async def test_acall_catches_async_exception():
    out = await boom_async.acall("{}")
    assert out.ok is False
    assert "kaboom" in out.content


class FakeStreamChunk:
    def __init__(self, *, content=None, tool_calls=None):
        delta = type(
            "Delta",
            (),
            {"content": content, "reasoning_content": None, "tool_calls": tool_calls},
        )()
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


@pytest.mark.asyncio
async def test_agent_runs_async_tool():
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
                {"name": "add_async", "arguments": '{"a": 4, "b": 5}'},
            )(),
        },
    )()
    provider = FakeProvider(
        [
            [FakeStreamChunk(tool_calls=[tc])],
            [FakeStreamChunk(content="done")],
        ]
    )
    agent = Agent(provider, system="test", tools=[add_async], max_turns=4)

    events = [e async for e in agent.arun("go")]
    tool_result = next(e for e in events if isinstance(e, ToolResult))

    assert tool_result.content == "9"
    assert tool_result.ok is True
