"""CodeRunner 单测：conversation 和 sandbox 都必须挂在 Thread 上。"""

import types

import pytest

from electromind import Agent, CodeAgent, CodeRunner, RunEnd, TextDelta, Thread, tool
from electromind.core.tool import FunctionTool


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
        self.calls = []

    async def complete(self, messages, tools=None, **run_kwargs):
        self.calls.append({"messages": messages, "tools": tools, **run_kwargs})
        chunks = self.steps.pop(0)

        async def stream():
            for chunk in chunks:
                yield chunk

        return stream()


@tool()
def agent_tool() -> str:
    """Agent 原有工具。"""
    return "agent"


@tool()
def sandbox_tool() -> str:
    """Sandbox 工具。"""
    return "sandbox"


@tool()
def extra_tool() -> str:
    """额外注入工具。"""
    return "extra"


class FakeSandbox:
    def __init__(self, workdir):
        self.workdir = str(workdir)
        self.closed = False
        self.installed = False

    def tools(self) -> list[FunctionTool]:
        return [sandbox_tool]

    async def describe(self) -> str:
        return f"fake sandbox at {self.workdir}"

    async def install_skills(self, registry):
        del registry
        self.installed = True
        return {}

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_sandbox(monkeypatch):
    opened: list[FakeSandbox] = []

    async def open_sandbox(self, name="main"):
        sandbox = FakeSandbox(self.workspace_path)
        opened.append(sandbox)
        return sandbox

    monkeypatch.setattr(Thread, "open_sandbox", open_sandbox)
    return opened


def tool_names(agent: Agent) -> set[str]:
    return set(agent.tool_map)


def schema_names(agent: Agent) -> set[str]:
    if agent.tool_schemas is None:
        return set()
    return {item["function"]["name"] for item in agent.tool_schemas}


def test_code_agent_alias_points_to_code_runner():
    assert CodeAgent is CodeRunner


def test_code_runner_constructor_defers_sandbox_init(tmp_path, fake_sandbox):
    provider = FakeProvider([])
    agent = Agent(provider)

    runner = CodeRunner(agent, thread_id="lazy-code", root=tmp_path)

    assert runner.thread.id == "lazy-code"
    assert runner.sandbox is None
    assert runner.code_initialized is False
    assert fake_sandbox == []


@pytest.mark.asyncio
async def test_code_runner_create_opens_thread_and_sandbox(
    tmp_path, fake_sandbox, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider([[FakeStreamChunk(content="done")]])
    agent = Agent(provider, system="base system", tools=[agent_tool])

    runner = await CodeRunner.create(
        agent,
        thread_id="code-test",
        root=tmp_path,
        backend="local",
        tools=[extra_tool],
    )

    assert runner.thread.id == "code-test"
    assert runner.thread.root == tmp_path / "code-test"
    assert (tmp_path / "code-test" / "thread.toml").is_file()
    assert (tmp_path / "code-test" / "workspaces" / "main").is_dir()
    assert fake_sandbox[0].workdir == str(
        tmp_path / "code-test" / "workspaces" / "main"
    )
    assert runner.sandbox is fake_sandbox[0]

    assert tool_names(runner.agent) == {
        "agent_tool",
        "sandbox_tool",
        "extra_tool",
    }
    assert schema_names(runner.agent) == tool_names(runner.agent)
    assert "fake sandbox" in (runner.agent.system or "")
    assert "base system" in (runner.agent.system or "")

    texts = [text async for text in runner.run("hi", return_type="text")]
    assert texts == ["done"]
    assert (tmp_path / "code-test" / "messages.jsonl").is_file()
    await runner.close()
    assert fake_sandbox[0].closed is True


@pytest.mark.asyncio
async def test_code_runner_lazy_init_before_run(tmp_path, fake_sandbox, monkeypatch):
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider([[FakeStreamChunk(content="lazy done")]])
    agent = Agent(provider, system="lazy system", tools=[agent_tool])

    runner = CodeRunner(
        agent,
        thread_id="lazy-run",
        root=tmp_path,
        backend="local",
        tools=[extra_tool],
    )

    assert fake_sandbox == []
    assert runner.sandbox is None

    texts = [text async for text in runner.run("hi", return_type="text")]

    assert texts == ["lazy done"]
    assert runner.code_initialized is True
    assert runner.sandbox is fake_sandbox[0]
    assert tool_names(runner.agent) == {
        "agent_tool",
        "sandbox_tool",
        "extra_tool",
    }
    assert schema_names(runner.agent) == tool_names(runner.agent)
    assert (tmp_path / "lazy-run" / "messages.jsonl").is_file()
    await runner.close()
    assert fake_sandbox[0].closed is True


@pytest.mark.asyncio
async def test_run_state_waking_sandbox_on_lazy_init(tmp_path, monkeypatch):
    import asyncio

    async def slow_open_sandbox(self, name="main"):
        await asyncio.sleep(0.05)
        sandbox = FakeSandbox(self.workspace_path)
        return sandbox

    monkeypatch.setattr(Thread, "open_sandbox", slow_open_sandbox)

    provider = FakeProvider([[FakeStreamChunk(content="lazy done")]])
    agent = Agent(provider, system="lazy system", tools=[agent_tool])
    runner = CodeRunner(
        agent,
        thread_id="wake-run",
        root=tmp_path,
        backend="local",
    )
    observed: list[str] = []

    async def poll() -> None:
        while True:
            phase = runner.run_state.phase
            if not observed or observed[-1] != phase:
                observed.append(phase)
            if phase == "ended":
                break
            await asyncio.sleep(0.005)

    poller = asyncio.create_task(poll())
    texts = [text async for text in runner.run("hi", return_type="text")]
    await poller

    assert texts == ["lazy done"]
    assert "waking_sandbox" in observed
    await runner.close()


@pytest.mark.asyncio
async def test_code_runner_conversation_id_is_compat_thread_alias(
    tmp_path, fake_sandbox
):
    provider = FakeProvider([[FakeStreamChunk(content="ok")]])
    agent = Agent(provider)

    runner = await CodeRunner.create(
        agent,
        conversation_id="compat-code",
        root=tmp_path,
        backend="local",
    )

    assert runner.thread.id == "compat-code"
    assert runner.conversation_id == "messages"
    assert runner.sandbox is fake_sandbox[0]
    await runner.close()


@pytest.mark.asyncio
async def test_code_runner_from_toml_uses_thread_workspace(
    tmp_path, fake_sandbox, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    toml_path = tmp_path / "code.toml"
    toml_path.write_text(
        "\n".join(
            [
                "[conversation]",
                'backend = "jsonl"',
                'root = "conversation"',
                'messages_id = "main"',
                "",
                "[sandbox]",
                'backend = "local"',
                "",
                "[agent]",
                'system = "spec system"',
            ]
        ),
        encoding="utf-8",
    )
    provider = FakeProvider([[FakeStreamChunk(content="from toml")]])
    agent = Agent(provider, system="agent system", tools=[agent_tool])

    runner = await CodeRunner.from_toml(
        toml_path,
        agent,
        thread_id="toml-code",
        root=tmp_path,
        tools=[extra_tool],
    )

    assert runner.thread.id == "toml-code"
    assert runner.conversation_id == "main"
    assert fake_sandbox[0].workdir == str(
        tmp_path / "toml-code" / "workspaces" / "main"
    )
    assert "spec system" in (runner.agent.system or "")
    assert "agent system" not in (runner.agent.system or "")
    assert tool_names(runner.agent) == {
        "agent_tool",
        "sandbox_tool",
        "extra_tool",
    }

    texts = [text async for text in runner.run("hi", return_type="text")]
    assert texts == ["from toml"]
    assert (tmp_path / "toml-code" / "conversation" / "main.jsonl").is_file()
    await runner.close()


@pytest.mark.asyncio
async def test_code_runner_event_stream_with_tools(tmp_path, fake_sandbox):
    from electromind import ToolCallBegin, ToolResult

    del fake_sandbox
    tc = types.SimpleNamespace(
        index=0,
        id="c1",
        type="function",
        function=types.SimpleNamespace(name="sandbox_tool", arguments="{}"),
    )
    provider = FakeProvider(
        [
            [FakeStreamChunk(content="checking", tool_calls=[tc])],
            [FakeStreamChunk(content="done")],
        ]
    )
    agent = Agent(provider, system="test", max_turns=4)

    runner = await CodeRunner.create(
        agent,
        thread_id="event-code",
        root=tmp_path,
        backend="local",
    )

    events = [event async for event in runner.run("go", return_type="event")]
    assert any(
        isinstance(event, TextDelta) and event.text == "checking" for event in events
    )
    assert any(
        isinstance(event, ToolCallBegin) and event.tool_call_id == "c1"
        for event in events
    )
    assert any(
        isinstance(event, ToolResult) and event.tool_call_id == "c1" for event in events
    )
    assert any(
        isinstance(event, TextDelta) and event.text == "done" for event in events
    )
    assert isinstance(events[-1], RunEnd)
    await runner.close()
