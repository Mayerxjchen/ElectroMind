"""危险工具审批 — run_command、copy_from_host。"""

from __future__ import annotations

import asyncio
import json

from pagentv4 import Runner, ToolCallBegin, ToolDecision, ToolHooks
from pagentv4.runtime.hooks import ToolHookContext

from .terminal import emit, emit_prompt

DIM = "\033[90m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def _c(text: str, code: str, *, on: bool) -> str:
    return f"{code}{text}{RESET}" if on else text


PERMIT_TOOLS = frozenset({"run_command", "copy_from_host"})

USER_DENIED_TOOL_MESSAGE = "用户拒绝了此工具调用。"


def needs_tool_permit(tool_name: str) -> bool:
    return tool_name in PERMIT_TOOLS


def runner_supports_permit(runner: object) -> bool:
    return hasattr(runner, "inbound")


def summarize_tool_args(name: str, arguments: str) -> str:
    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError:
        return arguments
    if name == "run_command":
        command = payload.get("command")
        return command if isinstance(command, str) else arguments
    if name == "copy_from_host":
        host_path = payload.get("host_path", "?")
        dest = payload.get("dest", ".")
        return f"{host_path} → {dest}"
    return arguments


def format_permit_prompt(event: ToolCallBegin) -> str:
    detail = summarize_tool_args(event.name, event.arguments)
    return f"审批 {event.name}：{detail}"


def parse_permit_answer(text: str) -> bool | None:
    word = text.strip().lower()
    if word in {"y", "yes", "是", "好", "ok", "批准", "同意"}:
        return True
    if word in {"n", "no", "否", "不", "拒绝", "deny"}:
        return False
    return None


def apply_permit_answer(runner: Runner, tool_call_id: str, approved: bool) -> None:
    if approved:
        runner.inbound.permit(tool_call_id)
    else:
        runner.inbound.deny(tool_call_id, reason=USER_DENIED_TOOL_MESSAGE)


async def require_tool_permit(ctx: ToolHookContext) -> ToolDecision | None:
    if not needs_tool_permit(ctx.name):
        return None
    result = await ctx.runner.wait_tool_permit(ctx.tool_call_id)
    if not result.approved:
        message = result.reason.strip() or USER_DENIED_TOOL_MESSAGE
        return ToolDecision.deny(message)
    return None


def build_app_tool_hooks(*, auto: bool = False) -> ToolHooks | None:
    if auto:
        return None
    return ToolHooks(before=[require_tool_permit])


async def prompt_permit_blocking(
    runner: Runner, event: ToolCallBegin, *, color: bool
) -> None:
    emit(_c(f"{format_permit_prompt(event)} [y/N]", YELLOW, on=color))
    while True:
        line = await asyncio.to_thread(emit_prompt, "permit> ")
        answer = parse_permit_answer(line)
        if answer is None:
            emit(_c("输入 y 批准 / n 拒绝", DIM, on=color))
            continue
        apply_permit_answer(runner, event.tool_call_id, answer)
        label = "已批准" if answer else "已拒绝"
        emit(_c(label, DIM, on=color))
        return


async def wait_for_layout_permit(
    runner: Runner,
    event: ToolCallBegin,
    run_state: dict,
    *,
    color: bool,
) -> None:
    emit(_c(f"{format_permit_prompt(event)} [y/N]", YELLOW, on=color))
    run_state["permit"] = event
    run_state["permit_wait"] = asyncio.Event()
    from .render import sync_run_state_ui
    from .terminal import layout_terminal

    sync_run_state_ui(runner, run_state)
    layout = layout_terminal.get()
    if layout is not None:
        layout.invalidate()
    try:
        await run_state["permit_wait"].wait()
    finally:
        run_state.pop("permit", None)
        wait = run_state.pop("permit_wait", None)
        if wait is not None and not wait.is_set():
            wait.set()
        sync_run_state_ui(runner, run_state)
        layout = layout_terminal.get()
        if layout is not None:
            layout.invalidate()
