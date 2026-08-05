"""Eval 执行 harness — 在隔离 thread 目录中驱动确定性任务。

- ``run_agent_task``：用 ``ScriptedProvider`` 驱动完整 ``Runner`` 循环，
  收集确定性观察（工具调用序列、事件配对、终态、消息历史）。
- ``install_safety_guard``：M0 参考实现的审批闸门（M4 之后由引擎自身的
  权限层替代，任务语义不变：高风险动作未授权不得执行、不得绕过）。
- ``run_driver_task``：engine 类任务（planning/recovery 等）执行注册的
  确定性 driver。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from electromind.core.events import RunEnd, ToolCallBegin, ToolResult
from electromind.core.tool import FunctionTool, ToolOutput
from electromind.runtime import Runner

from .provider import ScriptedProvider
from .task import TaskSpec
from .verifier import EvalObservation

# ── 参考审批闸门（M4 之前的安全基线）──────────────────────────────────


# 高风险工具名 → 允许的执行环境（eval 用 reference guard 拒绝）
HIGH_RISK_TOOLS = frozenset(
    {"run_command", "write_file", "str_replace", "copy_to_host"}
)


def make_side_effect_tool(
    log_path: Path, name: str = "eval_side_effect"
) -> FunctionTool:
    """记录外部副作用到 log 文件的 eval 专用工具。

    每次调用向 ``<log_path>`` 追加一行 ``<name>|<json-args>|ok``。
    恢复类任务用它验证副作用不重复执行。
    """

    async def eval_side_effect(name: str = "side_effect") -> ToolOutput:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"{name}|ok\n")
        return ToolOutput.succeed(f"side effect recorded: {name}")

    from electromind.execution.effects import ToolEffect

    return FunctionTool(
        name=name,
        description="记录一次外部副作用（eval 专用，用于幂等验证）。",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "副作用名称"}},
            "required": ["name"],
        },
        func=eval_side_effect,
        effect=ToolEffect.WRITE_WORKSPACE,
    )


def make_safety_guard(
    deny: Callable[[str, dict], str | None],
) -> Callable[[Runner], None]:
    """构造包装 ``execute_tool`` 的审批闸门安装器。

    ``deny(tool_name, arguments)`` 返回拒绝原因字符串（None = 放行）。
    被拒绝的工具产生 ``ToolOutput.fail``，其副作用不执行。
    """

    def install(runner: Runner) -> None:
        original = runner.execute_tool

        async def guarded(tool_call) -> ToolOutput:
            args = _parse_arguments(tool_call.arguments)
            reason = deny(tool_call.name, args)
            if reason is not None:
                return ToolOutput.fail(f"eval policy denied: {reason}")
            return await original(tool_call)

        runner.execute_tool = guarded  # type: ignore[method-assign]

    return install


def _parse_arguments(arguments: Any) -> dict:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


# ── Agent 任务执行 ─────────────────────────────────────────────────────


async def run_agent_task(
    task: TaskSpec,
    *,
    thread_root: Path,
    runner_factory: Callable[..., Awaitable[Runner]] | None = None,
    cancel_after_events: int | None = None,
) -> EvalObservation:
    """运行一个 agent 类 Golden Task，返回确定性观察。

    - 每个任务使用独立 thread_id（任务 id），在 ``thread_root`` 下创建。
    - fixtures 写入 ``workspaces/main/``（主 agent 工作目录）。
    - 事件流记录工具调用序列；RunEnd 记录 stop_reason。
    - 可选 safety guard 通过任务声明的 ``tools`` 触发。
    - ``cancel_after_events`` > 0：收到第 N 个事件后注入取消
      （recovery 类取消注入测试）。
    """
    import os

    from electromind.paths import reset_home

    thread_id = f"eval-{task.id}"
    # Runner.create 走默认 threads root；用 ELECTROMIND_HOME 隔离每个任务。
    # 必须在 finally 还原——否则 env 泄漏会污染同进程后续测试/代码
    # （曾导致 test_logs_missing_file 在全量序中失败）。
    reset_home()
    prev_home = os.environ.get("ELECTROMIND_HOME")
    os.environ["ELECTROMIND_HOME"] = str(thread_root)
    provider = ScriptedProvider(list(task.provider), model=f"eval-{task.id}")

    extra_tools = _build_extra_tools(task, thread_root)

    factory = runner_factory
    if factory is None:

        async def _default_factory(provider=provider):
            return await Runner.create(
                thread_id,
                provider,
                overrides={"backend": "local"},
                extra_system=task.system,
                max_turns=task.max_turns,
                tools=extra_tools,
            )

        factory = _default_factory

    runner = await factory()
    try:
        workdir = _workspace_of(runner)
        for relpath, content in task.fixtures:
            path = _safe_path(workdir, relpath)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        # 参考审批闸门：声明了 safety_guard 的任务安装拒绝策略
        if _wants_guard(task):
            guard = make_safety_guard(_reference_deny_policy(task))
            guard(runner)

        tool_calls: list[tuple[str, dict]] = []
        call_results: list[dict] = []
        begin_ids: set[str] = set()
        result_ids: set[str] = set()
        stop_reason = ""
        error = ""
        seen = 0
        call_index = -1  # 顺序执行下 ToolCallBegin/ToolResult 一一对应
        cancel_at = (
            task.cancel_after_events
            if cancel_after_events is None
            else cancel_after_events
        )
        try:
            async for event in runner.run(task.input, return_type="event"):
                seen += 1
                if cancel_at and seen == cancel_at:
                    runner.cancel_run()
                if isinstance(event, ToolCallBegin):
                    begin_ids.add(event.tool_call_id)
                    call_index += 1
                    tool_calls.append((event.name, _parse_arguments(event.arguments)))
                elif isinstance(event, ToolResult):
                    result_ids.add(event.tool_call_id)
                    call_results.append(
                        {
                            "name": event.name,
                            "args": (
                                tool_calls[call_index][1]
                                if 0 <= call_index < len(tool_calls)
                                else {}
                            ),
                            "ok": bool(event.ok),
                            "content": event.content,
                        }
                    )
                elif isinstance(event, RunEnd):
                    stop_reason = event.stop_reason
        except Exception as exc:  # noqa: BLE001 — 模拟中断：记录为 failed
            error = f"{type(exc).__name__}: {exc}"

        side_effect_log = _read_side_effect_log(thread_root)
        # 孤立工具检查在事件层：ToolCallBegin 必须都有 ToolResult 配对
        if begin_ids - result_ids:
            tool_calls.append(("<orphan>", {"ids": sorted(begin_ids - result_ids)}))
            call_results.append(
                {
                    "name": "<orphan>",
                    "args": {"ids": sorted(begin_ids - result_ids)},
                    "ok": False,
                    "content": "",
                }
            )

        return EvalObservation(
            thread_dir=thread_root,
            workdir=workdir,
            tool_calls=tool_calls,
            call_results=call_results,
            messages=_messages_to_dicts(runner.messages.data),
            stop_reason=stop_reason,
            run_phase=str(runner.run_state.phase),
            side_effect_log=side_effect_log,
            error=error,
        )
    finally:
        await runner.close()
        _restore_electromind_home(prev_home)


# ── Driver 任务执行 ────────────────────────────────────────────────────


DriverFn = Callable[[TaskSpec, Path], Awaitable[dict]]


async def run_driver_task(
    task: TaskSpec, driver: DriverFn, *, thread_root: Path
) -> dict:
    """执行 engine 类任务 driver，返回观察字典。"""
    return await driver(task, thread_root)


# ── 内部 ───────────────────────────────────────────────────────────────


def _restore_electromind_home(prev: str | None) -> None:
    """还原 ELECTROMIND_HOME（None = 原本未设置）。"""
    import os

    if prev is None:
        os.environ.pop("ELECTROMIND_HOME", None)
    else:
        os.environ["ELECTROMIND_HOME"] = prev


def _workspace_of(runner: Runner) -> Path:
    thread = getattr(runner, "thread", None)
    ws = getattr(thread, "workspace_path", None)
    if isinstance(ws, Path):
        path = ws
    elif callable(ws):
        path = Path(ws())
    else:
        path = Path.cwd() / "workspaces" / "main"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_path(root: Path, rel: str) -> Path:
    p = (root / rel).resolve()
    if not p.is_relative_to(root.resolve()):
        raise ValueError(f"fixture 路径逃逸: {rel!r}")
    return p


def _build_extra_tools(task: TaskSpec, thread_root: Path) -> list[FunctionTool]:
    tools: list[FunctionTool] = []
    for name in task.tools:
        if name == "eval_side_effect":
            tools.append(make_side_effect_tool(thread_root / "side_effect.log"))
        else:
            raise ValueError(f"未知 eval 工具: {name!r}")
    return tools


def _wants_guard(task: TaskSpec) -> bool:
    # safety 类任务默认安装参考审批闸门（声明 risk ≥ high 或 category=safety）
    if task.category != "safety":
        return False
    return task.expected.risk_level in ("high", "critical")


def _reference_deny_policy(task: TaskSpec):
    """参考策略：拒绝 HIGH_RISK_TOOLS 中未被任务显式期望的工具调用。

    任务声明 ``expected.tools`` 里出现的工具视为已授权；其余高风险工具
    一律拒绝——模拟「未授权高风险动作不得执行」的引擎契约。
    """

    allowed = {t.name for t in task.expected.tools}

    def deny(name: str, args: dict) -> str | None:
        if name in HIGH_RISK_TOOLS and name not in allowed:
            return f"high-risk tool {name!r} not approved"
        return None

    return deny


def _messages_to_dicts(messages) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        entry: dict[str, Any] = {"role": m.role}
        content = m.content
        if isinstance(content, list):
            entry["content"] = [
                c.text if hasattr(c, "text") else str(c) for c in content
            ]
        elif hasattr(content, "text"):
            entry["content"] = content.text
        elif hasattr(content, "tool_call_id"):
            entry["content"] = content.text
            entry["tool_call_id"] = content.tool_call_id
        else:
            entry["content"] = str(content)
        out.append(entry)
    return out


def _read_side_effect_log(thread_root: Path) -> list[str]:
    path = thread_root / "side_effect.log"
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()
