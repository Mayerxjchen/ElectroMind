import pytest

from electromind import FunctionTool, RunEnd, Runner, ToolCallBegin, TurnEnd


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

    async def complete(self, messages, tools=None, **run_kwargs):
        chunks = self.steps.pop(0)

        async def stream():
            for chunk in chunks:
                yield chunk

        return stream()


async def open_runner(tmp_path, monkeypatch, provider, *, tools=(), max_turns=24):
    monkeypatch.chdir(tmp_path)
    return await Runner.create(
        "test",
        provider,
        overrides={"backend": "local"},
        max_turns=max_turns,
        tools=tools,
    )


def tool_call_chunk(
    *,
    call_id: str = "call_1",
    name: str = "echo",
    arguments: str = '{"x": 1}',
):
    function = type(
        "Function",
        (),
        {"name": name, "arguments": arguments},
    )()
    tool_call = type(
        "ToolCall",
        (),
        {"index": 0, "id": call_id, "type": "function", "function": function},
    )()
    return FakeStreamChunk(tool_calls=[tool_call])


@pytest.mark.asyncio
async def test_runner_cancel_run_emits_cancelled_turn_end(tmp_path, monkeypatch):
    provider = FakeProvider(
        [
            [FakeStreamChunk(content="part1"), FakeStreamChunk(content="part2")],
            [FakeStreamChunk(content="unused")],
        ]
    )
    runner = await open_runner(tmp_path, monkeypatch, provider)
    try:
        events = []
        async for event in runner.run("hi"):
            events.append(event)
            if len(events) == 2:
                runner.cancel_run()
        ended = [event for event in events if isinstance(event, TurnEnd)]
        run_ended = [event for event in events if isinstance(event, RunEnd)]
        assert ended[-1].stop_reason == "cancelled"
        assert ended[-1].stopped is True
        assert run_ended[-1].stop_reason == "cancelled"
        assert runner.run_state.phase == "ended"
        assert runner.run_state.stop_reason == "cancelled"
        assert not runner.run_state.active
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_runner_steer_appends_user_message(tmp_path, monkeypatch):
    async def echo_tool(x: int) -> str:
        return f"echo:{x}"

    provider = FakeProvider(
        [
            [tool_call_chunk()],
            [FakeStreamChunk(content="done")],
        ]
    )
    runner = await open_runner(
        tmp_path,
        monkeypatch,
        provider,
        tools=[
            FunctionTool(
                "echo",
                "echo",
                {
                    "type": "object",
                    "properties": {"x": {"type": "integer"}},
                    "required": ["x"],
                },
                echo_tool,
                effect="execute",
            )
        ],
        max_turns=4,
    )
    try:
        async for event in runner.run("start"):
            if isinstance(event, TurnEnd) and event.stop_reason == "continuing":
                runner.steer("follow up")
        users = [
            message.content.text
            for message in runner.messages.data
            if message.role == "user"
        ]
        assert users == ["start", "follow up"]
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_runner_steer_during_tool_round_is_deferred(tmp_path, monkeypatch):
    async def echo_tool(x: int) -> str:
        return f"echo:{x}"

    provider = FakeProvider(
        [
            [tool_call_chunk()],
            [FakeStreamChunk(content="done")],
        ]
    )
    runner = await open_runner(
        tmp_path,
        monkeypatch,
        provider,
        tools=[
            FunctionTool(
                "echo",
                "echo",
                {
                    "type": "object",
                    "properties": {"x": {"type": "integer"}},
                    "required": ["x"],
                },
                echo_tool,
                effect="execute",
            )
        ],
        max_turns=4,
    )
    try:
        async for event in runner.run("start"):
            if isinstance(event, ToolCallBegin):
                runner.steer("too early")
                users = [
                    message.content.text
                    for message in runner.messages.data
                    if message.role == "user"
                ]
                assert users == ["start"]
        users = [
            message.content.text
            for message in runner.messages.data
            if message.role == "user"
        ]
        assert users == ["start", "too early"]
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_runner_steer_goes_to_semantic_checkpoint(tmp_path, monkeypatch):
    """M1 契约：steer 进入语义检查点（而非旧 inbound 邮箱）。"""
    provider = FakeProvider([[FakeStreamChunk(content="ok")]])
    runner = await open_runner(tmp_path, monkeypatch, provider)
    try:
        assert runner.inbound is not None  # 邮箱保留（permit/deny 用）
        assert runner.inbound_checkpoint is not None
        runner.steer("queued")
        assert runner.inbound_checkpoint.has_pending_immediate
    finally:
        await runner.close()
