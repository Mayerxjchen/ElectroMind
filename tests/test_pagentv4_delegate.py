"""delegate 工具：子 agent 委派、帧栈进出、子对话落盘、资源归属。"""

import types

import pytest

from pagentv4 import Agent, Runner
from pagentv4.ithread import SubAgentSpec, ThreadSpec
from pagentv4.runtime.base_runner import assemble_harness_tools
from pagentv4.tools.delegate import (
    SUBAGENT_TOOL_NAME,
    make_delegate_tool,
    make_delegate_tools,
    make_subagent_tool,
    next_sub_conversation_id,
    provider_with_model,
)


class FakeStreamChunk:
    def __init__(self, *, content=None, tool_calls=None):
        delta = types.SimpleNamespace(
            content=content,
            reasoning_content=None,
            tool_calls=tool_calls,
        )
        self.choices = [types.SimpleNamespace(delta=delta)]


class FakeProvider:
    """按 model_id 分脚本发流；同一 provider 派生子 provider 时按子 model 取脚本。"""

    def __init__(self, scripts: dict[str, list], model_id="main-model"):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.model_id = model_id

    async def complete(self, messages, tools=None, **run_kwargs):
        chunks = self.scripts[self.model_id].pop(0)

        async def stream():
            for chunk in chunks:
                yield chunk

        return stream()


def tool_call_chunk(call_id, name, arguments):
    tc = types.SimpleNamespace(
        index=0,
        id=call_id,
        type="function",
        function=types.SimpleNamespace(name=name, arguments=arguments),
    )
    return FakeStreamChunk(tool_calls=[tc])


async def make_runner(provider, *, tools=(), subs=None):
    runner = await Runner.create(
        "deleg",
        provider,
        overrides={"backend": "none"},
        tools=list(tools),
    )
    # Runner.create 已装好基帧；把 delegate 工具挂进主 agent。
    if subs:
        delegated = make_delegate_tools(subs)
        runner.agent = Agent(
            provider,
            system=runner.agent.system,
            tools=[*runner.agent.tools, *delegated],
            max_turns=runner.agent.max_turns,
        )
    return runner


def test_provider_with_model_swaps_model_id():
    p = FakeProvider({"main-model": []}, model_id="main-model")
    derived = provider_with_model(p, "sub-model")
    assert derived.model_id == "sub-model"
    assert p.model_id == "main-model"  # 原 provider 不受影响


def test_provider_with_model_empty_returns_same():
    p = FakeProvider({"main-model": []})
    assert provider_with_model(p, "") is p


def test_next_sub_conversation_id_increments():
    class FakeStore:
        def __init__(self, ids):
            self._ids = ids

        def list(self):
            return list(self._ids)

    store = FakeStore(["messages", "messages.sub.coder.0"])
    assert (
        next_sub_conversation_id(store, "messages", "coder") == "messages.sub.coder.1"
    )
    assert (
        next_sub_conversation_id(store, "messages", "writer") == "messages.sub.writer.0"
    )


@pytest.mark.asyncio
async def test_delegate_runs_sub_agent_and_returns_answer(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider(
        {
            # 主 agent：先调 delegate，再据结果收尾。
            "main-model": [
                [tool_call_chunk("c1", "delegate_to_coder", '{"task":"写快排"}')],
                [FakeStreamChunk(content="主 agent 汇总：子任务已完成")],
            ],
            # 子 agent：直接给出答复（无工具调用）。
            "coder-model": [
                [FakeStreamChunk(content="这是快排实现")],
            ],
        }
    )
    subs = {"coder": SubAgentSpec(system="你是程序员", model="coder-model")}
    runner = await make_runner(provider, subs=subs)

    texts = [t async for t in runner.run("帮我写快排", return_type="text")]
    joined = "".join(texts)
    assert "主 agent 汇总" in joined

    # 弹帧后回到基帧：栈只剩一层。
    assert len(runner.frames) == 1
    assert runner.conversation_id == "messages"
    await runner.close()

    # 子对话已落盘：同一 thread 的 messages 目录下多了命名空间 id 的文件。
    thread_root = tmp_path / ".pagent" / "threads" / "deleg"
    sub_file = thread_root / "messages" / "messages.sub.coder.0.jsonl"
    assert sub_file.is_file()
    main_file = thread_root / "messages" / "messages.jsonl"
    assert main_file.is_file()


@pytest.mark.asyncio
async def test_delegate_isolates_messages(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider(
        {
            "main-model": [
                [tool_call_chunk("c1", "delegate_to_helper", '{"task":"子任务"}')],
                [FakeStreamChunk(content="done")],
            ],
            "helper-model": [
                [FakeStreamChunk(content="子答复")],
            ],
        }
    )
    subs = {"helper": SubAgentSpec(model="helper-model")}
    runner = await make_runner(provider, subs=subs)

    async for _ in runner.run("go", return_type="event"):
        pass

    # 主对话里看不到子 agent 的内部消息，只有 delegate 的工具结果。
    main_texts = [
        m.content.text
        for m in runner.messages.data
        if m.role == "assistant" and hasattr(m.content, "text")
    ]
    assert "子答复" not in "".join(main_texts)
    await runner.close()


@pytest.mark.asyncio
async def test_delegate_can_observe_subagent_events(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider(
        {
            "main-model": [
                [tool_call_chunk("c1", "delegate_to_helper", '{"task":"子任务"}')],
                [FakeStreamChunk(content="done")],
            ],
            "helper-model": [
                [FakeStreamChunk(content="子答复")],
            ],
        }
    )
    subs = {"helper": SubAgentSpec(model="helper-model")}
    runner = await make_runner(provider, subs=subs)
    observed: list[tuple[str, str, str]] = []

    def observe_subagent_event(*, name: str, conversation_id: str, event) -> None:
        observed.append((name, conversation_id, type(event).__name__))

    runner.observe_subagent_event = observe_subagent_event
    async for _ in runner.run("go", return_type="event"):
        pass

    assert observed == [
        ("helper", "messages.sub.helper.0", "RunBegin"),
        ("helper", "messages.sub.helper.0", "TurnBegin"),
        ("helper", "messages.sub.helper.0", "TextDelta"),
        ("helper", "messages.sub.helper.0", "TurnResult"),
        ("helper", "messages.sub.helper.0", "TurnEnd"),
        ("helper", "messages.sub.helper.0", "RunEnd"),
    ]
    await runner.close()


@pytest.mark.asyncio
async def test_delegate_without_context_fails_gracefully():
    tool = make_delegate_tool("x", SubAgentSpec())
    out = await tool.acall('{"task":"t"}', context=None)
    assert out.ok is False


def test_subagent_tool_enum_covers_configured_subs():
    subs = {
        "researcher": SubAgentSpec(system="调研员"),
        "writer": SubAgentSpec(system="作者"),
    }
    tool = make_subagent_tool(subs)
    assert tool.name == SUBAGENT_TOOL_NAME
    props = tool.parameters["properties"]
    assert set(props["type"]["enum"]) == {"researcher", "writer"}
    assert tool.parameters["required"] == ["type", "task"]


@pytest.mark.asyncio
async def test_subagent_tool_unknown_type_fails():
    tool = make_subagent_tool({"coder": SubAgentSpec()})

    class FakeCtx:
        thread = object()

        def push_frame(self, frame):
            pass

    out = await tool.acall('{"type":"ghost","task":"t"}', context=FakeCtx())
    assert out.ok is False
    assert "ghost" in out.content


def test_assemble_harness_tools_gated_by_whitelist():
    subs = {"coder": SubAgentSpec(system="程序员")}

    # 列出白名单 + 配了 subs：挂统一委派工具。
    on = ThreadSpec(agent_tools=(SUBAGENT_TOOL_NAME,), subs=subs)
    tools = assemble_harness_tools(on)
    assert [t.name for t in tools] == [SUBAGENT_TOOL_NAME]

    # 没列白名单：不挂（即便配了 subs）。
    off = ThreadSpec(subs=subs)
    assert assemble_harness_tools(off) == []

    # 列了 delegate 但没配 subs：显式报错（空 enum 的委派工具无意义）。
    with pytest.raises(ValueError, match="sub"):
        assemble_harness_tools(ThreadSpec(agent_tools=(SUBAGENT_TOOL_NAME,)))


def test_assemble_harness_tools_resolves_web_tools():
    spec = ThreadSpec(agent_tools=("web_search", "fetch_url"))
    names = [t.name for t in assemble_harness_tools(spec)]
    assert names == ["web_search", "fetch_url"]

    # 未配置就没有 harness 工具。
    assert assemble_harness_tools(ThreadSpec()) == []


def test_assemble_harness_tools_rejects_unknown_name():
    with pytest.raises(ValueError, match="不是已知的 harness 工具"):
        assemble_harness_tools(ThreadSpec(agent_tools=("bogus_tool",)))


@pytest.mark.asyncio
async def test_subagent_tool_delegates_by_type(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    provider = FakeProvider(
        {
            "main-model": [
                [
                    tool_call_chunk(
                        "c1",
                        "delegate_to_subagent",
                        '{"type":"coder","task":"写快排"}',
                    )
                ],
                [FakeStreamChunk(content="主 agent 汇总")],
                [FakeStreamChunk(content="子 agent 的答复")],  # coder 继承 main-model
            ],
        }
    )
    subs = {"coder": SubAgentSpec(system="你是程序员")}
    runner = await Runner.create(
        "subagent-cfg",
        provider,
        overrides={
            "backend": "none",
            "agent_tools": (SUBAGENT_TOOL_NAME,),
            "subs": subs,
        },
    )

    tool_names = [t.name for t in runner.agent.tools]
    assert tool_names.count(SUBAGENT_TOOL_NAME) == 1

    async for _ in runner.run("帮我写快排", return_type="event"):
        pass

    assert len(runner.frames) == 1
    sub_ids = [cid for cid in runner.store.list() if ".sub.coder." in cid]
    assert sub_ids, "子对话应已落盘"
    await runner.close()
