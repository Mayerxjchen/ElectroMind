"""M5: 子 Agent 治理测试（结构化结果 / 委派预算 / 边界）。"""

from __future__ import annotations

import json

import pytest

from electromind.core.message import Message, Messages
from electromind.core.tool import FunctionTool
from electromind.ithread import SubAgentSpec
from electromind.tools.delegate import (
    SYSTEM_MAX_DEPTH,
    SubAgentResult,
    _count_tool_calls,
    bound_paths,
    check_delegation_allowed,
    delegation_depth,
    filter_tools_by_whitelist,
    run_sub_agent,
)

# ── SubAgentResult ──────────────────────────────────────────────────────


def test_subagent_result_serialization():
    result = SubAgentResult(
        status="completed",
        summary="分析完成",
        artifacts=["out.json"],
        evidence=["cmd exit 0"],
        assumptions=["单精度足够"],
        unresolved_questions=["是否需要泛化"],
        verification=["脚本生成指标"],
        usage={"tokens": {"total_tokens": 10}, "tool_calls": 1},
    )
    d = result.to_dict()
    assert d["status"] == "completed"
    assert d["artifacts"] == ["out.json"]
    assert json.loads(result.to_json())["summary"] == "分析完成"


def test_subagent_result_defaults():
    result = SubAgentResult()
    assert result.status == "completed"
    assert result.summary == ""
    assert result.artifacts == []
    assert result.usage == {}


# ── 委派深度 ────────────────────────────────────────────────────────────


class _FakeContext:
    def __init__(self, frames_count):
        self.frames = list(range(frames_count))


def test_delegation_depth():
    assert delegation_depth(_FakeContext(1)) == 0  # 仅基帧
    assert delegation_depth(_FakeContext(3)) == 2


def test_check_delegation_allowed():
    spec = SubAgentSpec()  # 默认 max_depth=1 → 只允许 1 层
    assert check_delegation_allowed(_FakeContext(1), spec, "coder") is None
    denied = check_delegation_allowed(_FakeContext(2), spec, "coder")
    assert denied is not None and "深度超限" in denied
    # 系统最大深度硬限制：即使 spec 声明 5 也只能到 2 层
    deep = SubAgentSpec(max_depth=5)
    assert check_delegation_allowed(_FakeContext(1), deep, "coder") is None  # 主→子
    assert check_delegation_allowed(_FakeContext(2), deep, "coder") is None  # 子→孙
    assert (
        check_delegation_allowed(_FakeContext(3), deep, "coder") is not None
    )  # 孙→曾孙 拒绝
    assert SYSTEM_MAX_DEPTH == 2


# ── 工具白名单与路径边界 ────────────────────────────────────────────────


def _tool(name, path_arg="path"):
    async def fn(**kwargs):
        return f"{name}:{kwargs.get(path_arg, '')}"

    return FunctionTool(
        name=name,
        description=name,
        parameters={"type": "object", "properties": {path_arg: {"type": "string"}}},
        func=fn,
    )


def test_filter_tools_by_whitelist():
    tools = [_tool("read_file"), _tool("write_file"), _tool("list_dir")]
    assert [t.name for t in filter_tools_by_whitelist(tools, ())] == [
        "read_file",
        "write_file",
        "list_dir",
    ]
    assert [t.name for t in filter_tools_by_whitelist(tools, ("read_file",))] == [
        "read_file"
    ]


async def test_bound_paths_blocks_escape():
    tools = [_tool("read_file"), _tool("write_file")]
    bounded = bound_paths(tools, read_paths=("data/",), write_paths=("out/",))
    read_result = await bounded[0].acall('{"path": "data/a.txt"}', context=None)
    assert read_result.ok
    blocked = await bounded[0].acall('{"path": "../secret.txt"}', context=None)
    assert not blocked.ok
    assert "路径越界" in blocked.content
    # 写边界
    write_ok = await bounded[1].acall('{"path": "out/b.txt"}', context=None)
    assert write_ok.ok
    write_blocked = await bounded[1].acall('{"path": "data/b.txt"}', context=None)
    assert not write_blocked.ok
    # 未配置边界 → 原样
    plain = bound_paths(tools)
    assert plain[0].func is tools[0].func


# ── 工具调用计数 ────────────────────────────────────────────────────────


def test_count_tool_calls():
    messages = Messages()
    messages += Message.assistant(
        {"type": "function", "id": "c1", "name": "x", "arguments": "{}"}
    )
    messages += Message.tool_result("c1", "ok")
    messages += Message.assistant({"type": "text", "text": "答"})
    assert _count_tool_calls(messages.data) == 1


# ── run_sub_agent 结构化终止 ────────────────────────────────────────────


class _FakeAgent:
    last_usage = {"total_tokens": 42}
    budget = type("B", (), {"model_calls": 2})()


class _FakeContext2:
    """最小 context 桩：run 行为可注入。"""

    def __init__(self, messages, run_impl):
        self.messages = messages
        self.agent = _FakeAgent()
        self._run = run_impl

    async def run(self, task):
        async for event in self._run(task):
            yield event


async def test_run_sub_agent_timeout():
    import asyncio

    async def slow(task):
        await asyncio.sleep(5)
        yield None

    context = _FakeContext2(Messages(), slow)
    result = await run_sub_agent(
        context, "slow", "任务", SubAgentSpec(timeout_seconds=0.05)
    )
    assert result.status == "timeout"


async def test_run_sub_agent_budget_exceeded():
    from electromind.core.budget import BudgetExceededError

    async def boom(task):
        raise BudgetExceededError("total_tokens 超限")
        yield None  # pragma: no cover

    context = _FakeContext2(Messages(), boom)
    result = await run_sub_agent(
        context, "costly", "任务", SubAgentSpec(max_tokens=100)
    )
    assert result.status == "budget_exceeded"


async def test_run_sub_agent_tool_call_limit():
    async def normal(task):
        yield None

    one_call = Messages()
    one_call += Message.assistant(
        {"type": "function", "id": "c1", "name": "x", "arguments": "{}"}
    )
    one_call += Message.tool_result("c1", "ok")
    one_call += Message.assistant({"type": "text", "text": "做了 1 次调用"})

    two_calls = Messages()
    two_calls += Message.assistant(
        {"type": "function", "id": "c1", "name": "x", "arguments": "{}"}
    )
    two_calls += Message.tool_result("c1", "ok")
    two_calls += Message.assistant(
        {"type": "function", "id": "c2", "name": "y", "arguments": "{}"}
    )
    two_calls += Message.tool_result("c2", "ok")
    two_calls += Message.assistant({"type": "text", "text": "做了 2 次调用"})

    context = _FakeContext2(one_call, normal)
    result = await run_sub_agent(
        context, "limited", "任务", SubAgentSpec(max_tool_calls=1)
    )
    assert result.status == "completed"
    assert result.usage["tool_calls"] == 1

    context2 = _FakeContext2(two_calls, normal)
    result2 = await run_sub_agent(
        context2, "limited", "任务", SubAgentSpec(max_tool_calls=1)
    )
    assert result2.status == "budget_exceeded"
    assert result2.usage["tool_calls"] == 2


# ── P0-6 验收：路径穿越 / 事前预算 / Reviewer 角色 ─────────────────────


async def test_path_traversal_normalized_blocked():
    """P0-6: ``data/../../secret`` 归一后必须被边界拒绝。"""
    tools = [_tool("read_file"), _tool("write_file")]
    bounded = bound_paths(tools, read_paths=("data/",), write_paths=("data/",))
    blocked = await bounded[0].acall('{"path": "data/../../secret.txt"}', context=None)
    assert not blocked.ok
    assert "路径越界" in blocked.content
    # 归一后仍在边界内 → 放行
    ok = await bounded[0].acall('{"path": "data/sub/../a.txt"}', context=None)
    assert ok.ok
    # 绝对路径拒绝
    abs_blocked = await bounded[0].acall('{"path": "/etc/passwd"}', context=None)
    assert not abs_blocked.ok


async def test_frame_tool_budget_pre_enforced(tmp_path, monkeypatch):
    """P0-6: 工具调用预算在执行前硬限（真实 Runner 双调用验证）。"""
    from evals.provider import ProviderStep, ScriptedProvider

    from electromind.runtime import Runner

    monkeypatch.chdir(tmp_path)
    provider = ScriptedProvider(
        [
            ProviderStep.tools(
                {"name": "read_file", "arguments": {"path": "a.txt"}},
                {"name": "read_file", "arguments": {"path": "b.txt"}},
            ),
            ProviderStep.text("ok"),
        ]
    )
    ws = tmp_path / ".electromind" / "threads" / "t-budget" / "workspaces" / "main"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "a.txt").write_text("a", encoding="utf-8")
    (ws / "b.txt").write_text("b", encoding="utf-8")
    runner = await Runner.create("t-budget", provider, overrides={"backend": "local"})
    try:
        # 预算 1：第一次允许，第二次执行前拒绝
        runner.frame.max_tool_calls = 1
        results = []
        async for event in runner.run("读两个文件"):
            from electromind.core.events import ToolResult

            if isinstance(event, ToolResult):
                results.append(event)
        assert len(results) == 2
        assert results[0].ok is True
        assert results[1].ok is False
        assert "预算已超限" in results[1].content
        assert runner.frame.tool_calls_executed == 1
    finally:
        await runner.close()


def test_reviewer_role_cannot_accept_own_artifact():
    """P0-6: Reviewer 角色不能批准自己创建的产物。"""
    from electromind.artifacts import ArtifactManifest
    from electromind.artifacts.manifest import ArtifactTransitionError

    m = (
        ArtifactManifest(
            artifact_id="r1",
            type="report",
            path="review.md",
            sha256="b" * 64,
            created_by="reviewer-bob",
            created_by_role="reviewer",
        )
        .complete()
        .validate(parser="checker")
    )
    # 同名 → 身份门拒绝
    with pytest.raises(ArtifactTransitionError, match="创建者"):
        m.accept(who="reviewer-bob", role="reviewer")
    # 异名同角色 → 角色门拒绝（Reviewer 不能批准同角色产物）
    with pytest.raises(ArtifactTransitionError, match="创建者角色"):
        m.accept(who="reviewer-carol", role="reviewer")
    # 跨角色评审：reviewer 接受 agent 角色创建的产物 ✓
    from electromind.artifacts import ArtifactManifest as _AM

    m2 = (
        _AM(
            artifact_id="r2",
            type="report",
            path="analysis.md",
            sha256="c" * 64,
            created_by="analysis-1",
            created_by_role="agent",
        )
        .complete()
        .validate(parser="checker")
    )
    accepted = m2.accept(who="reviewer-alice", role="reviewer")
    assert accepted.acceptance_status == "accepted"
    # 同角色不能互批（reviewer 不能接受 reviewer 的产物）
    with pytest.raises(ArtifactTransitionError, match="创建者角色"):
        m.accept(who="reviewer-carol", role="reviewer")
