"""G1b: Plan / Artifact 模型工具桥测试。

覆盖：
- 引擎访问器（set_engine/get_engine，未注册返回 None 不崩溃）
- plan_propose 工具：结构化步骤 → 引擎冻结 READY；空参数/非法拒绝
- plan_step_update 工具：running/failed/skipped；completed 无证据被 Evidence 门拒绝
- artifact_register 工具：跨后端读文件 + SHA-256；expected_artifacts 匹配
  自动附加文件证据 → 步骤随后可 completed
- created_by="agent"：用户 accept 不触发自证守卫
- Effect 声明齐全（正式 Runner 注册门）
- assemble_harness_tools 白名单装配
"""

from __future__ import annotations

import asyncio

import pytest

from electromind.engine import RunEngine
from electromind.engine.accessor import get_engine, set_engine
from electromind.execution.plan import PlanStatus, StepStatus
from electromind.runtime.base_runner import assemble_harness_tools
from electromind.tools.plan_artifacts import make_plan_tools


class FakeThread:
    id = "thread-tool-bridge"


class FakeFiles:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def read(self, path: str):
        if path == "missing.txt":
            raise FileNotFoundError(path)
        return self.content


class FakeSandbox:
    def __init__(self, content: bytes = b"hello-g1b") -> None:
        self.files = FakeFiles(content)


class FakeRunner:
    def __init__(self, content: bytes = b"hello-g1b") -> None:
        self.thread = FakeThread()
        self.sandbox = FakeSandbox(content)


@pytest.fixture(autouse=True)
def _engine(monkeypatch):
    """每个用例独立的引擎 + accessor 注册（不污染其他用例）。"""
    engine = RunEngine()
    set_engine(engine)
    yield engine
    set_engine(None)


def tool_by_name(name: str):
    return next(t for t in make_plan_tools() if t.name == name)


async def _acall(tool, arguments: dict, runner: FakeRunner):
    import json

    return await tool.acall(json.dumps(arguments), context=runner)


# ── accessor ───────────────────────────────────────────────────────────


def test_accessor_roundtrip():
    engine = RunEngine()
    set_engine(engine)
    assert get_engine() is engine
    set_engine(None)
    assert get_engine() is None


def test_effects_declared():
    for tool in make_plan_tools():
        assert tool.effect is not None, tool.name
        assert str(tool.effect) == "write_workspace"


# ── plan_propose ───────────────────────────────────────────────────────


def test_plan_propose_tool_creates_ready_plan(_engine):
    runner = FakeRunner()
    tool = tool_by_name("plan_propose")
    output = asyncio.run(
        _acall(
            tool,
            {
                "goal": "生成 CP2K 输入并运行",
                "steps": [
                    {"title": "写输入文件", "expected_artifacts": ["cp2k.inp"]},
                    {"title": "运行计算", "depends_on": ["s1"]},
                ],
                "verification": ["收敛"],
            },
            runner,
        )
    )
    assert output.ok
    plan = _engine.plan_state("thread-tool-bridge")
    assert plan is not None
    assert plan.status == PlanStatus.READY
    assert len(plan.steps) == 2
    assert plan.steps[0].id == "s1" and plan.steps[0].title == "写输入文件"
    assert plan.steps[1].depends_on == ("s1",)
    assert plan.verification == ("收敛",)


def test_plan_propose_rejects_empty(_engine):
    tool = tool_by_name("plan_propose")
    output = asyncio.run(_acall(tool, {"goal": "", "steps": []}, FakeRunner()))
    assert not output.ok
    assert "不能为空" in output.content


def test_plan_propose_versions_after_existing(_engine):
    runner = FakeRunner()
    tool = tool_by_name("plan_propose")
    asyncio.run(_acall(tool, {"goal": "v1", "steps": [{"title": "a"}]}, runner))
    asyncio.run(_acall(tool, {"goal": "v2", "steps": [{"title": "b"}]}, runner))
    plan = _engine.plan_state("thread-tool-bridge")
    assert plan is not None and plan.version == 2 and plan.objective == "v2"


def test_plan_propose_without_engine_fails():
    set_engine(None)
    tool = tool_by_name("plan_propose")
    output = asyncio.run(
        _acall(tool, {"goal": "x", "steps": [{"title": "a"}]}, FakeRunner())
    )
    assert not output.ok
    assert "引擎未就绪" in output.content


# ── plan_step_update ───────────────────────────────────────────────────


def test_step_update_running_and_gates(_engine):
    runner = FakeRunner()
    propose = tool_by_name("plan_propose")
    asyncio.run(
        _acall(
            propose,
            {"goal": "g", "steps": [{"title": "a"}, {"title": "b"}]},
            runner,
        )
    )
    step = tool_by_name("plan_step_update")

    # running：允许
    out = asyncio.run(_acall(step, {"step_id": "s1", "status": "running"}, runner))
    assert out.ok
    plan = _engine.plan_state("thread-tool-bridge")
    assert plan.steps[0].status == StepStatus.RUNNING

    # completed 无证据：被 Evidence 门拒绝
    out = asyncio.run(_acall(step, {"step_id": "s1", "status": "completed"}, runner))
    assert not out.ok
    assert "无 Evidence" in out.content

    # failed 缺原因 / skipped 缺理由：拒绝
    out = asyncio.run(_acall(step, {"step_id": "s1", "status": "failed"}, runner))
    assert not out.ok and "error" in out.content
    out = asyncio.run(_acall(step, {"step_id": "s1", "status": "skipped"}, runner))
    assert not out.ok and "skipped_reason" in out.content

    # failed 带原因：允许
    out = asyncio.run(
        _acall(step, {"step_id": "s1", "status": "failed", "error": "收敛失败"}, runner)
    )
    assert out.ok
    assert _engine.plan_state("thread-tool-bridge").steps[0].status == StepStatus.FAILED

    # 未知步骤 / 非法状态
    out = asyncio.run(_acall(step, {"step_id": "s9", "status": "running"}, runner))
    assert not out.ok and "不存在" in out.content
    out = asyncio.run(_acall(step, {"step_id": "s2", "status": "done"}, runner))
    assert not out.ok and "非法" in out.content


# ── artifact_register + 证据自动化 ─────────────────────────────────────


def test_artifact_register_with_auto_evidence(_engine):
    runner = FakeRunner(b"artifact-data")
    propose = tool_by_name("plan_propose")
    asyncio.run(
        _acall(
            propose,
            {
                "goal": "g",
                "steps": [{"title": "产出", "expected_artifacts": ["out.txt"]}],
            },
            runner,
        )
    )
    register = tool_by_name("artifact_register")
    out = asyncio.run(
        _acall(
            register,
            {"path": "out.txt", "type": "data", "step_id": "s1"},
            runner,
        )
    )
    assert out.ok
    assert "已登记产物 out.txt" in out.content
    assert "已附加文件证据" in out.content

    plan = _engine.plan_state("thread-tool-bridge")
    assert plan.steps[0].evidence, "证据应已自动附加"
    evidence = plan.steps[0].evidence[0]
    assert evidence.kind.value == "file" and evidence.by == "agent"

    # 证据就位后步骤可 completed
    step = tool_by_name("plan_step_update")
    out = asyncio.run(_acall(step, {"step_id": "s1", "status": "completed"}, runner))
    assert out.ok
    assert (
        _engine.plan_state("thread-tool-bridge").steps[0].status == StepStatus.COMPLETED
    )


def test_artifact_register_basename_match(_engine):
    runner = FakeRunner(b"x")
    propose = tool_by_name("plan_propose")
    asyncio.run(
        _acall(
            propose,
            {"goal": "g", "steps": [{"title": "a", "expected_artifacts": ["out.txt"]}]},
            runner,
        )
    )
    register = tool_by_name("artifact_register")
    out = asyncio.run(
        _acall(
            register, {"path": "data/out.txt", "type": "data", "step_id": "s1"}, runner
        )
    )
    assert out.ok and "已附加文件证据" in out.content


def test_artifact_register_read_failure(_engine):
    register = tool_by_name("artifact_register")
    out = asyncio.run(
        _acall(register, {"path": "missing.txt", "type": "data"}, FakeRunner())
    )
    assert not out.ok
    assert "读取产物失败" in out.content


def test_artifact_accept_by_user_after_agent_registered(_engine):
    """created_by=agent → 用户 accept 不触发自证守卫（M6 闭环）。"""
    runner = FakeRunner(b"z")
    register = tool_by_name("artifact_register")
    asyncio.run(_acall(register, {"path": "out.txt", "type": "report"}, runner))
    # M6 状态机：CREATED → COMPLETED → VALIDATED → ACCEPTED（不能跳级）
    _engine.artifact_complete("thread-tool-bridge", "out.txt")
    _engine.artifact_validate("thread-tool-bridge", "out.txt", parser="checker-1")
    accepted = _engine.artifact_accept("thread-tool-bridge", "out.txt", who="user")
    assert accepted is not None
    assert accepted.acceptance_status.value == "accepted"


# ── assemble_harness_tools 装配 ────────────────────────────────────────


def test_assemble_whitelist_plan_tools():
    from electromind.ithread import ThreadSpec

    spec = ThreadSpec(
        agent_tools=("plan_propose", "plan_step_update", "artifact_register")
    )
    tools = assemble_harness_tools(spec)
    assert {t.name for t in tools} == {
        "plan_propose",
        "plan_step_update",
        "artifact_register",
    }


def test_assemble_unknown_still_errors():
    from electromind.ithread import ThreadSpec

    spec = ThreadSpec(agent_tools=("nope",))
    with pytest.raises(ValueError, match="不是已知的 harness 工具"):
        assemble_harness_tools(spec)
