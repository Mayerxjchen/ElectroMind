"""RenderItem → 行文本（plain / ANSI 双份）。宽度按桶缓存由 store 负责。

视觉语言（见渲染改造计划）：
- 颜色只表达语义；状态带符号：✓ completed / ! warning / × failed / ● running / ? approval
- 主时间线 Tool Card 最多 3–5 行；完整日志进 Overlay
"""

from __future__ import annotations

import json
from typing import Iterable

from ..render import inline
from .theme import (
    BLUE,
    CYAN,
    DIM,
    GREEN,
    RED,
    SYMBOL_APPROVAL,
    SYMBOL_FAIL,
    SYMBOL_OK,
    SYMBOL_RUNNING,
    SYMBOL_WARN,
    YELLOW,
    c,
)
from .view_model import (
    ActivityItem,
    ApprovalItem,
    AssistantMessageItem,
    ErrorItem,
    RenderItem,
    RunStatusItem,
    SystemNoticeItem,
    ToolItem,
    UserMessageItem,
)

APPROVAL_ACTION_HINT = "[y] 批准一次  [n] 拒绝  [d] 详情"


# ---------------------------------------------------------------------------
# 单条目渲染
# ---------------------------------------------------------------------------


def render_user(item: UserMessageItem, *, color: bool) -> list[str]:
    head = c("You", BLUE, on=color)
    if item.delivery:
        head = f"{head} {c(f'[{item.delivery}]', DIM, on=color)}"
    return [head, item.text]


def render_assistant(item: AssistantMessageItem, *, color: bool) -> list[str]:
    head = c("ElectroMind", GREEN, on=color)
    return [head, *render_body(item.text)]


def render_activity(item: ActivityItem, *, color: bool) -> list[str]:
    if item.done:
        return []
    symbol = SYMBOL_RUNNING if item.running else SYMBOL_OK
    return [f"{symbol} {item.text}"]


def _tool_command(name: str, arguments: str) -> str:
    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError:
        return inline(arguments)
    if isinstance(payload, dict):
        command = payload.get("command")
        if isinstance(command, str):
            return command
        path = payload.get("path")
        if isinstance(path, str):
            return f"{name} {path}"
    return inline(arguments)


def _tool_target_line(item: ToolItem) -> str:
    parts = [item.target or "sandbox"]
    if item.workdir:
        parts.append(item.workdir)
    return " · ".join(parts)


def render_tool(item: ToolItem, *, color: bool) -> list[str]:
    if item.status == "running":
        symbol = SYMBOL_RUNNING
        status_code = CYAN
    elif item.status == "ok":
        symbol = SYMBOL_OK
        status_code = GREEN
    else:
        symbol = SYMBOL_FAIL
        status_code = RED

    lines = [
        c(f"{symbol} {item.name}", status_code, on=color)
        + c(f"  {_tool_target_line(item)}", DIM, on=color)
    ]
    command = _tool_command(item.name, item.args_summary)
    if command:
        lines.append(f"  {command}")

    if item.status != "running":
        meta: list[str] = []
        if item.exit_code is not None:
            meta.append(f"exit {item.exit_code}")
        if item.duration_s is not None:
            meta.append(f"{item.duration_s}s")
        if item.output_lines:
            meta.append(f"{item.output_lines} lines")
        if meta:
            lines.append(
                c(f"  {' · '.join(meta)}", DIM, on=color)
                + c("  [查看输出]", DIM, on=color)
            )
    return lines


def render_approval(item: ApprovalItem, *, color: bool) -> list[str]:
    symbol = {
        "pending": SYMBOL_APPROVAL,
        "approved": SYMBOL_OK,
        "denied": SYMBOL_FAIL,
        "expired": SYMBOL_WARN,
    }.get(item.status, SYMBOL_WARN)
    code = {
        "pending": YELLOW,
        "approved": GREEN,
        "denied": RED,
        "expired": DIM,
    }.get(item.status, DIM)
    lines = [c(f"{symbol} {item.name}  ({item.status})", code, on=color)]
    if item.command:
        lines.append(f"  {item.command}")
    meta = [f"Target {item.target or '—'}"]
    if item.workdir:
        meta.append(f"Workdir {item.workdir}")
    if item.risk:
        meta.append(f"Risk {item.risk}")
    lines.append(c("  " + "  ".join(meta), DIM, on=color))
    if item.status == "pending":
        lines.append(c(f"  {APPROVAL_ACTION_HINT}", DIM, on=color))
    return lines


def render_error(item: ErrorItem, *, color: bool) -> list[str]:
    return [c(f"{SYMBOL_FAIL} {item.message}", RED, on=color)]


def render_run_status(item: RunStatusItem, *, color: bool) -> list[str]:
    del color
    return [item.text]


def render_notice(item: SystemNoticeItem, *, color: bool) -> list[str]:
    return [c(item.text, DIM, on=color)]


def render_body(text: str) -> list[str]:
    """基础 Markdown：标题 / 引用 / 列表 / 代码块 / 行内代码（保序输出）。"""
    lines: list[str] = []
    in_code = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            lines.append(stripped)
            continue
        if in_code:
            lines.append(raw)
            continue
        if stripped.startswith("|") and "|" in stripped[1:]:
            lines.append(stripped)
            continue
        if raw.startswith(("### ", "#### ", "##### ")):
            lines.append(raw[4:])
        elif raw.startswith("## "):
            lines.append(raw[3:])
        elif raw.startswith("# "):
            lines.append(raw[2:])
        elif raw.startswith(("> ", ">")):
            lines.append(f"  {raw.lstrip('> ')}")
        elif raw.startswith(("- ", "* ", "• ")):
            lines.append(f"  {raw}")
        elif raw.startswith(("1.", "2.", "3.")):
            lines.append(f"  {raw}")
        else:
            lines.append(raw)
    return lines or [""]


def render_item(item: RenderItem, *, color: bool) -> list[str]:
    if isinstance(item, UserMessageItem):
        return render_user(item, color=color)
    if isinstance(item, AssistantMessageItem):
        return render_assistant(item, color=color)
    if isinstance(item, ActivityItem):
        return render_activity(item, color=color)
    if isinstance(item, ToolItem):
        return render_tool(item, color=color)
    if isinstance(item, ApprovalItem):
        return render_approval(item, color=color)
    if isinstance(item, ErrorItem):
        return render_error(item, color=color)
    if isinstance(item, RunStatusItem):
        return render_run_status(item, color=color)
    if isinstance(item, SystemNoticeItem):
        return render_notice(item, color=color)
    return [f"<{type(item).__name__}>"]


def render_all(items: Iterable[RenderItem], *, color: bool) -> list[str]:
    lines: list[str] = []
    for item in items:
        lines.extend(render_item(item, color=color))
        lines.append("")
    return lines
