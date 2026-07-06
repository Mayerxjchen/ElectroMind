import asyncio

import pytest

from pagentv4 import (
    FunctionTool,
    Runner,
    ToolCallBegin,
    ToolDecision,
    ToolHooks,
    ToolOutput,
    ToolResult,
)
from pagentv4.runtime.hooks import PostToolHookContext, ToolHookContext


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


async def open_runner(tmp_path, monkeypatch, provider, *, tools=(), tool_hooks=None):
    monkeypatch.setenv("PAGENT_THREADS_DIR", str(tmp_path))
    return await Runner.open(
        "test",
        provider,
        overrides={"backend": "local"},
        tools=tools,
        tool_hooks=tool_hooks,
    )


@pytest.mark.asyncio
async def test_before_tool_deny_skips_execution(tmp_path, monkeypatch):
    seen: list[str] = []

    async def echo(x: int) -> str:
        seen.append("ran")
        return f"echo:{x}"

    def deny_shell(ctx: ToolHookContext) -> ToolDecision:
        if ctx.name == "echo":
            return ToolDecision.deny("blocked")
        return ToolDecision.allow()

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
                echo,
            )
        ],
        tool_hooks=ToolHooks(before=[deny_shell]),
    )
    try:
        results = []
        async for event in runner.run("go"):
            if isinstance(event, ToolResult):
                results.append(event)
        assert seen == []
        assert results == [
            ToolResult("call_1", "echo", "blocked", ok=False),
        ]
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_after_tool_rewrites_result(tmp_path, monkeypatch):
    cleanup: list[str] = []

    async def echo(x: int) -> str:
        return f"raw:{x}"

    def redact(ctx: PostToolHookContext) -> ToolOutput:
        cleanup.append("done")
        return ToolOutput.succeed(ctx.output.content.replace("raw:", "safe:"))

    provider = FakeProvider(
        [
            [tool_call_chunk()],
            [FakeStreamChunk(content="ok")],
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
                echo,
            )
        ],
        tool_hooks=ToolHooks(after=[redact]),
    )
    try:
        results = []
        async for event in runner.run("go"):
            if isinstance(event, ToolResult):
                results.append(event)
        assert cleanup == ["done"]
        assert results == [ToolResult("call_1", "echo", "safe:1", ok=True)]
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_wait_tool_permit_blocks_until_approved(tmp_path, monkeypatch):
    async def echo(x: int) -> str:
        return f"echo:{x}"

    async def require_permit(ctx: ToolHookContext) -> ToolDecision | None:
        if ctx.name != "echo":
            return None
        approved = await ctx.runner.wait_tool_permit(ctx.tool_call_id)
        if not approved.approved:
            return ToolDecision.deny(approved.reason or "not permitted")
        return None

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
                echo,
            )
        ],
        tool_hooks=ToolHooks(before=[require_permit]),
    )

    async def approve_later():
        await asyncio.sleep(0.05)
        runner.inbound.permit("call_1")

    try:
        task = asyncio.create_task(approve_later())
        results = []
        begins = []
        async for event in runner.run("go"):
            if isinstance(event, ToolCallBegin):
                begins.append(event)
            if isinstance(event, ToolResult):
                results.append(event)
        await task
        assert len(begins) == 1
        assert results == [ToolResult("call_1", "echo", "echo:1", ok=True)]
    finally:
        await runner.close()


@pytest.mark.asyncio
async def test_no_hooks_preserves_existing_behavior(tmp_path, monkeypatch):
    async def echo(x: int) -> str:
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
                echo,
            )
        ],
    )
    try:
        results = []
        async for event in runner.run("go"):
            if isinstance(event, ToolResult):
                results.append(event)
        assert results == [ToolResult("call_1", "echo", "echo:1", ok=True)]
    finally:
        await runner.close()
