"""Eval 框架自身测试（M0 §5.4：框架覆盖率 ≥90%）。

覆盖：任务声明解析/校验、注册表、脚本化 Provider、harness 执行、
确定性验证器、报告/基线对比、CLI、driver 执行。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals import (
    ExpectedArtifact,
    ExpectedOutcome,
    ExpectedState,
    ExpectedToolCall,
    FailureCategory,
    ProviderStep,
    RiskLevel,
    TaskSpec,
)
from evals.cli import main as cli_main
from evals.drivers import DRIVERS, get_driver, run_task_with_driver
from evals.harness import (
    make_safety_guard,
    make_side_effect_tool,
    run_agent_task,
)
from evals.provider import EvalChunk, ScriptedProvider
from evals.registry import (
    TaskRegistry,
    category_counts,
    load_all_tasks,
    load_task_file,
)
from evals.report import (
    TaskResult,
    build_report,
    compare_to_baseline,
    load_report,
    make_result,
    save_report,
    summarize,
)
from evals.task import FailureCategory as FC
from evals.verifier import (
    DeterministicVerifier,
    EvalObservation,
    _args_match,
    _find_orphan_tool_results,
    _is_subsequence,
    _safe_join,
    sha256_file,
    side_effect_digest,
)

from electromind.core.tool import ToolOutput

# ── 任务声明解析 ────────────────────────────────────────────────────────


def test_task_spec_roundtrip():
    raw = {
        "id": "t-1",
        "category": "tool_use",
        "input": "读取文件",
        "title": "读文件",
        "provider": [
            {
                "type": "tools",
                "calls": [{"name": "read_file", "arguments": {"path": "a"}}],
            },
            {"type": "text", "content": "完成"},
        ],
        "expected": {
            "tools": [{"name": "read_file", "args": {"path": "a"}}],
            "forbidden_tools": ["rm"],
            "artifacts": [{"path": "out.txt", "contains": ["x"]}],
            "state": {"stop_reason": "no_tool_calls"},
            "constraints": ["约束"],
            "verification_command": "true",
            "risk_level": "high",
            "timeout_seconds": 12,
            "runs_required": 3,
            "failed_calls": [1],
            "call_results": [{"index": 0, "contains": "err"}],
        },
        "fixtures": [{"path": "f.txt", "content": "data"}],
        "tools": ["eval_side_effect"],
        "cancel_after_events": 4,
    }
    spec = TaskSpec.from_dict(raw)
    assert spec.id == "t-1"
    assert spec.category == "tool_use"
    assert len(spec.provider) == 2
    assert spec.provider[0].type == "tools"
    assert spec.provider[0].calls[0]["arguments"]["path"] == "a"
    assert spec.provider[1].content == "完成"
    assert spec.expected.tools[0].name == "read_file"
    assert spec.expected.tools[0].args == {"path": "a"}
    assert spec.expected.forbidden_tools == ("rm",)
    assert spec.expected.artifacts[0].path == "out.txt"
    assert spec.expected.state.stop_reason == "no_tool_calls"
    assert spec.expected.constraints == ("约束",)
    assert spec.expected.risk_level == RiskLevel.HIGH
    assert spec.expected.timeout_seconds == 12
    assert spec.expected.runs_required == 3
    assert spec.expected.failed_calls == (1,)
    assert spec.expected.call_results == ({"index": 0, "contains": "err"},)
    assert spec.fixtures == (("f.txt", "data"),)
    assert spec.tools == ("eval_side_effect",)
    assert spec.cancel_after_events == 4
    assert spec.declares_provider


def test_task_spec_validate_errors():
    base = {
        "id": "bad",
        "category": "tool_use",
        "input": "x",
        "provider": [{"type": "text", "content": "ok"}],
    }
    errors = TaskSpec.from_dict(base).validate()
    assert errors == []

    # 缺 provider 键
    d = dict(base)
    del d["provider"]
    assert TaskSpec.from_dict(d).validate()

    # 非法类别
    d = dict(base, category="nope")
    assert TaskSpec.from_dict(d).validate()

    # driver 与 provider 互斥
    d = dict(base, driver="plan_lifecycle")
    assert TaskSpec.from_dict(d).validate()

    # 空 provider 显式声明合法（空响应测试）
    d = dict(base, provider=[])
    assert TaskSpec.from_dict(d).validate() == []

    # orphan 检查需要 stop_reason
    d = dict(base)
    d["expected"] = {"state": {"no_orphan_tool_results": True}}
    assert TaskSpec.from_dict(d).validate()


def test_provider_step_factories():
    s = ProviderStep.text("你好")
    assert s.type == "text" and s.content == "你好"
    t = ProviderStep.tools({"name": "x"})
    assert t.type == "tools" and t.calls == ({"name": "x"},)


# ── 注册表 ──────────────────────────────────────────────────────────────


def test_registry_loads_60_tasks():
    tasks = load_all_tasks()
    assert len(tasks) >= 60  # M0 基线 60；后续里程碑新增 golden 任务
    counts = category_counts(tasks)
    assert all(counts[c] >= 10 for c in counts)
    ids = [t.id for t in tasks]
    assert len(set(ids)) == len(tasks)  # id 唯一


def test_registry_duplicate_id_rejected(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(
        json.dumps(
            {
                "id": "dup",
                "category": "planning",
                "input": "x",
                "driver": "plan_lifecycle",
            }
        ),
        encoding="utf-8",
    )
    spec = load_task_file(p)
    registry = TaskRegistry([spec])
    with pytest.raises(ValueError, match="重复任务 id"):
        registry.add_all([spec])


def test_registry_queries():
    tasks = [
        TaskSpec(id="a", category="planning", input="i1", driver="plan_lifecycle"),
        TaskSpec(id="b", category="safety", input="i2", declares_provider=True),
    ]
    registry = TaskRegistry(tasks)
    assert registry.get("a").id == "a"
    assert [t.id for t in registry.by_category("safety")] == ["b"]
    assert registry.ids() == ["a", "b"]
    assert len(registry) == 2


def test_load_task_file_rejects_bad():
    with pytest.raises(ValueError, match="必须是 JSON"):
        load_task_file(Path("/tmp/x.yaml"))


# ── 脚本化 Provider ─────────────────────────────────────────────────────


async def test_scripted_provider_text_and_tools():
    provider = ScriptedProvider(
        [
            ProviderStep.text("答"),
            ProviderStep.tools({"name": "ls", "arguments": {"path": "."}}),
        ]
    )
    stream = await provider.complete([], tools=None)
    chunks = [c async for c in stream]
    assert chunks[0].choices[0].delta.content == "答"
    stream2 = await provider.complete([], tools=None)
    chunks2 = [c async for c in stream2]
    assert chunks2[0].choices[0].delta.tool_calls[0].function.name == "ls"
    assert chunks2[0].choices[0].delta.tool_calls[0].id.startswith("call_")
    assert (
        chunks2[0].choices[0].delta.tool_calls[0].function.arguments == '{"path": "."}'
    )
    # 步骤耗尽 → 空流
    stream3 = await provider.complete([], tools=None)
    assert [c async for c in stream3] == []


async def test_scripted_provider_reasoning():
    provider = ScriptedProvider(
        [ProviderStep(type="text", content="答", reasoning="思")]
    )
    stream = await provider.complete([], tools=None)
    chunks = [c async for c in stream]
    assert chunks[0].choices[0].delta.reasoning_content == "思"
    assert chunks[1].choices[0].delta.content == "答"


def test_eval_chunk_usage():
    chunk = EvalChunk(usage={"total_tokens": 10})
    assert chunk.usage == {"total_tokens": 10}
    empty = EvalChunk()
    assert empty.choices == []


# ── verifier ────────────────────────────────────────────────────────────


def _obs(**kw) -> EvalObservation:
    defaults = dict(
        thread_dir=Path("/tmp"),
        workdir=Path("/tmp/w"),
        tool_calls=[],
        call_results=[],
        messages=[],
        stop_reason="",
        run_phase="",
        side_effect_log=[],
        error="",
    )
    defaults.update(kw)
    return EvalObservation(**defaults)


def test_verifier_tools_order_and_args(tmp_path):
    verifier = DeterministicVerifier()
    task = TaskSpec(
        id="v1",
        category="tool_use",
        input="x",
        declares_provider=True,
        expected=ExpectedOutcome(
            tools=(
                ExpectedToolCall("read_file", {"path": "a.txt"}),
                ExpectedToolCall("list_dir"),
            )
        ),
    )
    obs = _obs(
        tool_calls=[("read_file", {"path": "a.txt"}), ("list_dir", {"path": "."})],
        run_phase="ended",
        stop_reason="no_tool_calls",
    )
    assert verifier.verify(task, obs).passed

    # 顺序错误（子序列不匹配）
    obs2 = _obs(
        tool_calls=[("list_dir", {"path": "."}), ("read_file", {"path": "a.txt"})],
        run_phase="ended",
        stop_reason="no_tool_calls",
    )
    assert not verifier.verify(task, obs2).passed

    # 参数不匹配
    obs3 = _obs(
        tool_calls=[("read_file", {"path": "b.txt"}), ("list_dir", {"path": "."})],
        run_phase="ended",
        stop_reason="no_tool_calls",
    )
    assert not verifier.verify(task, obs3).passed


def test_verifier_forbidden_and_failed(tmp_path):
    verifier = DeterministicVerifier()
    task = TaskSpec(
        id="v2",
        category="safety",
        input="x",
        declares_provider=True,
        expected=ExpectedOutcome(
            tools=(ExpectedToolCall("read_file"),),
            forbidden_tools=("write_file",),
            failed_calls=(0, 1),
        ),
    )
    # write_file 被拒绝（ok=False）+ read 成功 → 通过
    obs = _obs(
        tool_calls=[("write_file", {}), ("write_file", {}), ("read_file", {})],
        call_results=[
            {"name": "write_file", "args": {}, "ok": False, "content": "denied"},
            {"name": "write_file", "args": {}, "ok": False, "content": "denied"},
            {"name": "read_file", "args": {}, "ok": True, "content": "ok"},
        ],
        run_phase="ended",
        stop_reason="no_tool_calls",
    )
    assert verifier.verify(task, obs).passed

    # write_file 成功执行 → 违规
    obs2 = _obs(
        tool_calls=[("write_file", {}), ("read_file", {})],
        call_results=[
            {"name": "write_file", "args": {}, "ok": True, "content": "wrote"},
            {"name": "read_file", "args": {}, "ok": True, "content": "ok"},
        ],
        run_phase="ended",
        stop_reason="no_tool_calls",
    )
    result = verifier.verify(task, obs2)
    assert not result.passed
    assert result.failure == FailureCategory.SAFETY


def test_verifier_artifacts_and_command(tmp_path):
    verifier = DeterministicVerifier()
    wd = tmp_path / "w"
    wd.mkdir()
    (wd / "out.txt").write_text("能量: -76.4 Hartree", encoding="utf-8")
    task = TaskSpec(
        id="v3",
        category="scientific",
        input="x",
        declares_provider=True,
        expected=ExpectedOutcome(
            artifacts=(ExpectedArtifact("out.txt", ("Hartree",), ("错误",)),),
            verification_command='python3 -c \'assert "Hartree" in open("out.txt").read()\'',
        ),
    )
    obs = _obs(workdir=wd, run_phase="ended", stop_reason="no_tool_calls")
    assert verifier.verify(task, obs).passed

    # 缺失片段
    task2 = TaskSpec(
        id="v4",
        category="scientific",
        input="x",
        declares_provider=True,
        expected=ExpectedOutcome(artifacts=(ExpectedArtifact("nope.txt", ("x",)),)),
    )
    assert not verifier.verify(task2, obs).passed


def test_verifier_constraints_and_cancelled():
    verifier = DeterministicVerifier()
    task = TaskSpec(
        id="v5",
        category="context",
        input="x",
        declares_provider=True,
        expected=ExpectedOutcome(
            constraints=("必须使用 UTF-8",),
            state=ExpectedState(
                terminal="cancelled",
                stop_reason="cancelled",
                no_orphan_tool_results=True,
            ),
        ),
    )
    obs = _obs(
        messages=[{"role": "user", "content": "约束：必须使用 UTF-8"}],
        stop_reason="cancelled",
        run_phase="ended",
    )
    assert verifier.verify(task, obs).passed

    # 约束丢失
    obs2 = _obs(
        messages=[{"role": "user", "content": "无约束"}],
        stop_reason="cancelled",
        run_phase="ended",
    )
    assert not verifier.verify(task, obs2).passed


def test_verifier_failed_terminal():
    verifier = DeterministicVerifier()
    task = TaskSpec(
        id="v6",
        category="recovery",
        input="x",
        declares_provider=True,
        expected=ExpectedOutcome(state=ExpectedState(terminal="failed")),
    )
    assert verifier.verify(task, _obs(error="模拟中断")).passed
    assert not verifier.verify(task, _obs(error="")).passed


def test_verifier_orphans_in_messages():
    orphans = _find_orphan_tool_results(
        [
            {"role": "assistant", "tool_calls": [{"id": "c1"}]},
            {"role": "tool", "tool_call_id": "c1"},
            {"role": "assistant", "tool_calls": [{"id": "c2"}]},
        ]
    )
    assert orphans == ["c2"]


# ── 辅助函数 ────────────────────────────────────────────────────────────


def test_args_match():
    assert _args_match({"path": "a"}, {"path": "a", "extra": 1})
    assert not _args_match({"path": "a"}, {"path": "b"})
    assert _args_match({"nested": {"x": 1}}, {"nested": {"x": 1, "y": 2}})
    assert not _args_match({"tags": ["a"]}, {"tags": ["a", "b"]})  # 列表需精确相等
    assert not _args_match({"tags": ["a"]}, {"tags": ["b"]})


def test_is_subsequence():
    assert _is_subsequence(["a", "b"], ["x", "a", "y", "b"])
    assert not _is_subsequence(["a", "b"], ["b", "a"])
    assert _is_subsequence([], ["a"])


def test_safe_join_rejects_escape(tmp_path):
    with pytest.raises(ValueError):
        _safe_join(tmp_path, "../escape")


def test_sha256_and_digest(tmp_path):
    p = tmp_path / "f"
    p.write_bytes(b"hello")
    assert (
        sha256_file(p)
        == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )
    obs = _obs(side_effect_log=["a", "b"])
    assert side_effect_digest(obs) == side_effect_digest(
        _obs(side_effect_log=["a", "b"])
    )
    assert side_effect_digest(obs) != side_effect_digest(_obs(side_effect_log=["a"]))


# ── harness ─────────────────────────────────────────────────────────────


def test_make_side_effect_tool(tmp_path):
    tool = make_side_effect_tool(tmp_path / "se.log")
    assert tool.name == "eval_side_effect"

    async def run():
        return await tool.acall('{"name": "submit"}', context=None)

    import asyncio

    output = asyncio.run(run())
    assert output.ok
    assert (tmp_path / "se.log").read_text(encoding="utf-8") == "submit|ok\n"


def test_safety_guard_denies_and_allows():
    calls: list[str] = []

    class FakeRunner:
        async def execute_tool(self, tool_call):
            calls.append(tool_call.name)
            return ToolOutput.succeed("ok")

    runner = FakeRunner()
    install = make_safety_guard(lambda name, args: "denied" if name == "rm" else None)
    install(runner)

    import asyncio

    async def run():
        denied = await runner.execute_tool(
            type("TC", (), {"name": "rm", "arguments": "{}"})()
        )
        allowed = await runner.execute_tool(
            type("TC", (), {"name": "ls", "arguments": "{}"})()
        )
        return denied, allowed

    denied, allowed = asyncio.run(run())
    assert not denied.ok
    assert allowed.ok
    assert calls == ["ls"]  # rm 未执行


async def test_run_agent_task_observation(tmp_path):
    task = TaskSpec(
        id="smoke",
        category="tool_use",
        input="读取 data.txt",
        declares_provider=True,
        provider=(
            ProviderStep.tools(
                {"name": "read_file", "arguments": {"path": "data.txt"}}
            ),
            ProviderStep.text("完成"),
        ),
        fixtures=(("data.txt", "内容"),),
    )
    obs = await run_agent_task(task, thread_root=tmp_path / "home")
    assert obs.tool_names() == ["read_file"]
    assert obs.stop_reason == "no_tool_calls"
    assert obs.call_results[0]["ok"] is True
    assert (obs.workdir / "data.txt").exists()


# ── report ──────────────────────────────────────────────────────────────


def test_report_summary_and_compare(tmp_path):
    results = [
        TaskResult(id="a", category="safety", passed=True),
        TaskResult(
            id="b", category="recovery", passed=False, failure="state", details="x"
        ),
        TaskResult(id="c", category="safety", passed=True),
    ]
    summary = summarize(results)
    assert summary["total"] == 3 and summary["passed"] == 2
    assert summary["by_category"]["safety"]["passed"] == 2
    assert summary["by_failure"] == {"state": 1}

    report = build_report(results, tested_commit="abc")
    assert report["tested_commit"] == "abc"
    path = tmp_path / "r.json"
    save_report(report, path)
    assert load_report(path)["summary"]["total"] == 3

    baseline = build_report(
        [
            TaskResult(id="a", category="safety", passed=True),
            TaskResult(id="b", category="recovery", passed=True),
            TaskResult(id="c", category="safety", passed=True),
        ]
    )
    comparison = compare_to_baseline(report, baseline)
    assert not comparison["safe"]  # recovery 从 1.0 掉到 0.0
    assert comparison["regressions"][0]["category"] == "recovery"


def test_make_result_digest():
    task = TaskSpec(id="m", category="recovery", input="x", declares_provider=True)
    verification = DeterministicVerifier().verify(
        task, _obs(run_phase="ended", stop_reason="no_tool_calls")
    )
    result = make_result(
        task,
        verification,
        runs=2,
        observations=[_obs(side_effect_log=["a"]), _obs(side_effect_log=["a"])],
    )
    assert result.passed
    assert result.runs == 2
    assert result.side_effect_digest


# ── drivers ─────────────────────────────────────────────────────────────


def test_drivers_registry():
    assert "plan_lifecycle" in DRIVERS
    assert callable(get_driver("plan_lifecycle"))
    with pytest.raises(KeyError):
        get_driver("nope")


async def test_run_driver_task_happy_and_timeout(tmp_path):
    spec = TaskSpec(id="d1", category="planning", input="x", driver="plan_lifecycle")

    result = await run_task_with_driver(spec, tmp_path)
    assert result["passed"]
    assert result["failure"] is None

    # 未知 driver
    spec2 = TaskSpec(id="d2", category="planning", input="x", driver="missing")
    result2 = await run_task_with_driver(spec2, tmp_path)
    assert not result2["passed"]
    assert result2["failure"] == str(FC.ENVIRONMENT)


# ── CLI ─────────────────────────────────────────────────────────────────


def test_cli_list_and_run(tmp_path, monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)
    assert cli_main(["list"]) == 0
    assert cli_main(["list", "--json"]) == 0
    out = tmp_path / "report.json"
    code = cli_main(["run", "--ids", "plan-001", "--output", str(out)])
    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["summary"]["total"] == 1
    assert report["summary"]["passed"] == 1


def test_cli_baseline_and_unknown_id(tmp_path, monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)
    out_dir = tmp_path / "base"
    code = cli_main(["baseline", "--ids", "sci-001", "--output-dir", str(out_dir)])
    assert code == 0
    assert (out_dir / "baseline.json").exists()
    code2 = cli_main(["run", "--ids", "does-not-exist"])
    assert code2 == 2


def test_cli_run_categories_and_failure_path(tmp_path, monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)
    out = tmp_path / "cat.json"
    code = cli_main(["run", "--categories", "safety", "--output", str(out)])
    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["summary"]["total"] >= 10
    assert report["category_counts"]["safety"] >= 10

    # 失败路径：monkeypatch agent 执行为必然失败
    import evals.cli as cli_mod
    from evals.verifier import EvalObservation

    async def failing_run(task, **kw):
        return EvalObservation(
            thread_dir=tmp_path,
            workdir=tmp_path,
            stop_reason="no_tool_calls",
            run_phase="ended",
        )

    monkeypatch.setattr(cli_mod, "run_agent_task", failing_run)
    out2 = tmp_path / "fail.json"
    code2 = cli_main(["run", "--ids", "ctx-001", "--output", str(out2)])
    assert code2 == 2
    report2 = json.loads(out2.read_text(encoding="utf-8"))
    assert report2["summary"]["passed"] == 0


# ── 边界分支补充（框架覆盖率 ≥90%） ────────────────────────────────────


def test_verifier_state_edge_branches():
    verifier = DeterministicVerifier()
    # terminal=completed 但 phase 不在允许集且无 error → 失败
    t1 = TaskSpec(id="e1", category="tool_use", input="x", declares_provider=True)
    r1 = verifier.verify(t1, _obs(run_phase="cancelled", stop_reason="cancelled"))
    assert not r1.passed and r1.failure == FailureCategory.STATE
    # 显式 phase 不匹配
    t2 = TaskSpec(
        id="e2",
        category="tool_use",
        input="x",
        declares_provider=True,
        expected=ExpectedOutcome(state=ExpectedState(phase="completed")),
    )
    r2 = verifier.verify(t2, _obs(run_phase="ended"))
    assert not r2.passed
    # failed_calls 越界
    t3 = TaskSpec(
        id="e3",
        category="safety",
        input="x",
        declares_provider=True,
        expected=ExpectedOutcome(failed_calls=(5,)),
    )
    r3 = verifier.verify(t3, _obs(call_results=[]))
    assert not r3.passed and r3.failure == FailureCategory.SAFETY
    # call_results 越界
    t4 = TaskSpec(
        id="e4",
        category="tool_use",
        input="x",
        declares_provider=True,
        expected=ExpectedOutcome(call_results=({"index": 3, "contains": "x"},)),
    )
    r4 = verifier.verify(t4, _obs(call_results=[]))
    assert not r4.passed and r4.failure == FailureCategory.TOOL


def test_verifier_artifact_and_command_failures(tmp_path):
    verifier = DeterministicVerifier()
    wd = tmp_path / "w"
    wd.mkdir()
    (wd / "out.txt").write_text("坏内容", encoding="utf-8")
    task = TaskSpec(
        id="e5",
        category="scientific",
        input="x",
        declares_provider=True,
        expected=ExpectedOutcome(
            artifacts=(ExpectedArtifact("out.txt", ("好",), ("坏",)),),
        ),
    )
    r = verifier.verify(task, _obs(workdir=wd, run_phase="ended"))
    assert not r.passed and r.failure == FailureCategory.VALIDATION
    # verification_command 非零退出
    task2 = TaskSpec(
        id="e6",
        category="scientific",
        input="x",
        declares_provider=True,
        expected=ExpectedOutcome(verification_command="exit 1"),
    )
    r2 = verifier.verify(task2, _obs(workdir=wd, run_phase="ended"))
    assert not r2.passed and r2.failure == FailureCategory.VALIDATION
    # 成功命令通过
    task3 = TaskSpec(
        id="e7",
        category="scientific",
        input="x",
        declares_provider=True,
        expected=ExpectedOutcome(verification_command="true"),
    )
    assert verifier.verify(task3, _obs(workdir=wd, run_phase="ended")).passed


def test_verifier_orphan_tool_results():
    verifier = DeterministicVerifier()
    task = TaskSpec(
        id="e8",
        category="recovery",
        input="x",
        declares_provider=True,
        expected=ExpectedOutcome(
            state=ExpectedState(
                terminal="cancelled",
                stop_reason="cancelled",
                no_orphan_tool_results=True,
            ),
        ),
    )
    obs = _obs(
        stop_reason="cancelled",
        run_phase="ended",
        messages=[{"role": "assistant", "tool_calls": [{"id": "c2"}]}],
    )
    r = verifier.verify(task, obs)
    assert not r.passed and r.failure == FailureCategory.STATE


async def test_harness_unknown_tool_and_escape(tmp_path):
    from evals.harness import _build_extra_tools, _safe_path

    task = TaskSpec(
        id="e9",
        category="tool_use",
        input="x",
        declares_provider=True,
        tools=("not_a_tool",),
    )
    with pytest.raises(ValueError, match="未知 eval 工具"):
        _build_extra_tools(task, tmp_path)

    with pytest.raises(ValueError, match="逃逸"):
        _safe_path(tmp_path, "../escape")


def test_harness_parse_arguments_fallback():
    from evals.harness import _parse_arguments

    assert _parse_arguments('{"a": 1}') == {"a": 1}
    assert _parse_arguments("not json") == {}
    assert _parse_arguments(None) == {}
    assert _parse_arguments([1, 2]) == {}


def test_cli_baseline_failure_returns_2(tmp_path, monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)
    import evals.cli as cli_mod
    from evals.verifier import EvalObservation

    async def failing_run(task, **kw):
        return EvalObservation(
            thread_dir=tmp_path,
            workdir=tmp_path,
            stop_reason="x",
            run_phase="x",
        )

    monkeypatch.setattr(cli_mod, "run_agent_task", failing_run)
    out_dir = tmp_path / "base2"
    code = cli_main(["baseline", "--ids", "ctx-001", "--output-dir", str(out_dir)])
    assert code == 2
    report = json.loads((out_dir / "baseline.json").read_text(encoding="utf-8"))
    assert report["summary"]["passed"] == 0


# ── 全部 driver 任务可执行（M0：100% 任务有确定性验证器） ──────────────


@pytest.mark.parametrize(
    "task_id",
    [t.id for t in load_all_tasks() if t.driver],
)
async def test_all_driver_tasks_pass(tmp_path, task_id):
    from evals.registry import load_all_tasks

    task = next(t for t in load_all_tasks() if t.id == task_id)
    result = await run_task_with_driver(task, tmp_path / task_id)
    assert result["passed"], (
        f"{task_id} 失败: [{result.get('failure')}] {result.get('details')}"
    )
