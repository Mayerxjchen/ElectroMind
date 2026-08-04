"""EventReducer — Harness/Runner 事件 → 有序 RenderItem 列表 + 状态行。

- 文本按“段”建 AssistantMessageItem：文本流到来且无未完成的文本段时新建，
  Tool 开始或 Run 结束即关闭，保证文本与 Tool 卡片在时间线上交错正确。
- ReasoningDelta 只驱动一个公开 ActivityItem（“思考中…”，由调用方节流），
  默认不展示 raw reasoning。
- 本类不接触终端，纯数据；渲染由 tui.render 完成。
"""

from __future__ import annotations

import time

from electromind import ReasoningDelta, RunEnd, TextDelta, ToolCallBegin, ToolResult

from ..tool_permit import MAX_TOOL_OUTPUT_CHARS
from .view_model import (
    ActivityItem,
    ApprovalItem,
    AssistantMessageItem,
    ErrorItem,
    RenderItem,
    StatusLineState,
    SystemNoticeItem,
    ToolItem,
    UserMessageItem,
)

_THINKING_TEXT = "思考中…"


class EventReducer:
    def __init__(
        self,
        *,
        mode: str = "run",
        target: str = "sandbox",
        permission: str = "prompt",
        model: str = "",
        project: str = "",
    ) -> None:
        self.status = StatusLineState(
            mode=mode,
            target=target,
            permission=permission,
            model=model,
            project=project,
        )
        self.items: list[RenderItem] = []
        self._counters: dict[str, int] = {}
        self._open_assistant: AssistantMessageItem | None = None
        self._thinking: ActivityItem | None = None
        self._tool_started: dict[str, float] = {}

    # ------------------------------------------------------------------
    # 时间线操作
    # ------------------------------------------------------------------

    def _next_id(self, prefix: str) -> str:
        n = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = n
        return f"{prefix}-{n}"

    def _append(self, item: RenderItem) -> None:
        self.items.append(item)

    def append_item(self, item: RenderItem) -> None:
        """公开追加入口（如 ! 命令的 ToolItem、外部通知）。"""
        self._append(item)

    # ------------------------------------------------------------------
    # 用户与系统事件
    # ------------------------------------------------------------------

    def user_message(self, text: str) -> UserMessageItem:
        self._close_assistant()
        item = UserMessageItem(id=self._next_id("user"), text=text)
        self._append(item)
        return item

    def system_notice(self, text: str) -> SystemNoticeItem:
        self._close_assistant()
        item = SystemNoticeItem(id=self._next_id("notice"), text=text)
        self._append(item)
        return item

    def error(self, message: str) -> ErrorItem:
        item = ErrorItem(id=self._next_id("error"), message=message)
        self._append(item)
        return item

    def run_status(self, status: str) -> None:
        self.status.run_status = status

    def set_context_pct(self, pct: int | None) -> None:
        self.status.context_pct = pct

    # ------------------------------------------------------------------
    # Runner 事件
    # ------------------------------------------------------------------

    def handle(self, event) -> str:
        """处理事件；返回被触碰条目的 id（供渲染缓存精确失效）。

        返回 "all" 表示需要整体失效（Run 结束等批量状态变化）。
        """
        if isinstance(event, TextDelta):
            return self._append_text(event.text)
        if isinstance(event, ReasoningDelta):
            return self._append_reasoning(event.text)
        if isinstance(event, ToolCallBegin):
            self._close_assistant()
            self._finish_thinking()
            self._tool_started[event.tool_call_id] = time.monotonic()
            tool = ToolItem(
                id=event.tool_call_id,
                name=event.name,
                args_summary=event.arguments,
                status="running",
            )
            self._append(tool)
            self.run_status("running_tool")
            return tool.id
        if isinstance(event, ToolResult):
            return self._tool_result(event)
        if isinstance(event, RunEnd):
            self._close_assistant()
            finished = self._finish_thinking()
            self._tool_started.clear()
            self.run_status(
                "completed" if event.stop_reason != "cancelled" else "cancelled"
            )
            return finished or "all"
        return ""

    # -- 文本分段 --------------------------------------------------------

    def _append_text(self, text: str) -> str:
        if self._open_assistant is None:
            self._open_assistant = AssistantMessageItem(
                id=self._next_id("assistant"), text=""
            )
            self._append(self._open_assistant)
        self._open_assistant.text += text
        self.run_status("generating")
        return self._open_assistant.id

    def _close_assistant(self) -> None:
        if self._open_assistant is not None:
            self._open_assistant.done = True
            self._open_assistant = None

    # -- 思考活动 --------------------------------------------------------

    def _append_reasoning(self, text: str) -> str:
        del text  # raw reasoning 默认不展示，只亮起公开 Activity
        if self._thinking is None:
            self._thinking = ActivityItem(
                id=self._next_id("activity"), text=_THINKING_TEXT, running=True
            )
            self._append(self._thinking)
        self.run_status("generating")
        return self._thinking.id

    def _finish_thinking(self) -> str:
        if self._thinking is not None:
            self._thinking.running = False
            self._thinking.done = True
            thinking_id = self._thinking.id
            self._thinking = None
            return thinking_id
        return ""

    # -- Tool 结果 --------------------------------------------------------

    def _tool_result(self, event: ToolResult) -> str:
        item = self._find_tool(event.tool_call_id)
        if item is None:
            return ""
        ok = bool(event.ok)
        item.status = "ok" if ok else "failed"
        item.exit_code = _extract_exit_code(event.content)
        started = self._tool_started.pop(event.tool_call_id, None)
        if started is not None:
            item.duration_s = round(time.monotonic() - started, 1)
        content = event.content or ""
        item.output_lines = content.count("\n") + 1 if content.strip() else 0
        item.output_preview = " ".join(content.split())[:160]
        # 大日志不常驻：完整输出设上限（主时间线只渲染摘要）
        item.full_output = content[:MAX_TOOL_OUTPUT_CHARS]
        self.run_status("generating")
        return item.id

    def _find_tool(self, tool_call_id: str) -> ToolItem | None:
        for item in reversed(self.items):
            if isinstance(item, ToolItem) and item.id == tool_call_id:
                return item
        return None

    # ------------------------------------------------------------------
    # Approval
    # ------------------------------------------------------------------

    def approval_pending(
        self,
        tool_call_id: str,
        *,
        name: str,
        command: str,
        target: str,
        workdir: str,
        risk: str = "",
        approval_id: str = "",
    ) -> ApprovalItem:
        item = ApprovalItem(
            id=f"approval-{tool_call_id}",
            approval_id=approval_id,
            tool_call_id=tool_call_id,
            name=name,
            command=command,
            target=target,
            workdir=workdir,
            risk=risk,
            status="pending",
        )
        self._append(item)
        self.run_status("approval")
        return item

    def approval_resolved(
        self, tool_call_id: str, approved: bool, expired: bool = False
    ) -> None:
        item = self._find_approval(tool_call_id)
        if item is None:
            return
        if expired:
            item.status = "expired"
        else:
            item.status = "approved" if approved else "denied"
        self.run_status("generating")

    def _find_approval(self, tool_call_id: str) -> ApprovalItem | None:
        for entry in reversed(self.items):
            if (
                isinstance(entry, ApprovalItem)
                and entry.id == f"approval-{tool_call_id}"
            ):
                return entry
        return None


def _extract_exit_code(content: str) -> int | None:
    """从 ToolResult content（run_command 的 JSON dump）尽力取 exit_code。"""
    import json

    if not content:
        return None
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(payload, dict):
        value = payload.get("exit_code")
        return value if isinstance(value, int) else None
    return None
