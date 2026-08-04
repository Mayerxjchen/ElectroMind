"""CliApp — 客户端驱动的多 Thread 语义化交互应用（CLI-4）。

- 事件来源：EmbeddedAgentClient 的事件流（thread_id/seq/run_id/item_id），
  不再直接消费 Runner 事件；每个 Thread 一个视图（reducer+store），后台
  Run 的事件进入自己的视图，切换视图不关闭 Runner。
- 输入：Composer → client.send_input（auto / immediate / enqueue），交付状态
  由 input/state 事件驱动（accepted/applied/queued/deferred/rejected）。
- 审批：approval/requested → 卡片浮层；y/n/d → client.resolve_approval（绑定
  thread+run，Manager 校验后原子消费）。
- 本类不创建 Runner、不修改 Harness 状态。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.layout import Float, FloatContainer, Layout, Window
from prompt_toolkit.layout.containers import HSplit
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension

from electromind import ReasoningDelta, RunEnd, TextDelta, ToolCallBegin, ToolResult

from ..tool_permit import (
    MAX_TOOL_OUTPUT_CHARS,
)
from . import components
from .completer import CliCompleter
from .keymap import build_key_bindings
from .reducer import EventReducer
from .store import ItemStore
from .theme import DIM, c
from .view_model import ApprovalItem, AssistantMessageItem

MODE_PREFIX = {"ask": "Ask> ", "plan": "Plan> ", "run": "Run> "}
MAX_OUTPUT_OVERLAY_LINES = 200
DELIVERY_LABELS = {
    "accepted": "accepted",
    "applied": "applied",
    "queued": "queued",
    "deferred": "deferred",
    "rejected": "rejected",
    "immediate_pending": "immediate",
}


@dataclass(slots=True)
class ThreadView:
    """单 Thread 的时间线视图：reducer + store（reducer 与 store 共享 items）。"""

    thread_id: str
    reducer: EventReducer = field(default_factory=EventReducer)
    store: ItemStore = field(default_factory=lambda: ItemStore(color=True))
    hydrated: bool = False
    last_assistant_text: str = ""
    pending_approval: ApprovalItem | None = None
    active_run_id: str = ""
    last_seq: int = -1  # 已渲染的最大 seq（重复事件去重）


def version_string() -> str:
    try:
        from importlib.metadata import version

        return version("electromind")
    except Exception:
        return "dev"


class CliApp:
    """交互应用：状态机 idle / running / approval + 浮层 + 多视图。"""

    def __init__(
        self,
        *,
        color: bool,
        mode: str = "run",
        target: str = "sandbox",
        permission: str = "prompt",
        model: str = "",
        project: str = "",
        thread_id: str = "",
        full_screen: bool = True,
        client=None,
    ) -> None:
        self.color = color
        self.full_screen = full_screen
        self.client = client
        self.thread_id = thread_id
        self._mode = mode
        self._target = target
        self._permission = permission
        self._model = model
        self._project = project
        self.views: dict[str, ThreadView] = {}

        self.state = "idle"  # idle | running | approval（当前视图）
        self.overlay: dict | None = None
        self.pending_approval: ApprovalItem | None = None
        self._active_run_id = ""

        self.composer_buffer = Buffer(multiline=True)
        self.slash_buffer = Buffer()
        self.slash_entries: list[tuple[str, str]] = []
        self.slash_selected = 0
        self._slash_command = ""

        self.delivery = ""
        self._shell_seq = 0
        self._delivery_pending: dict[str, str] = {}  # request_id → user item id

        self.input_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.pt_app: Application | None = None
        self.pane = None
        self._invalidate_scheduled = False
        self._invalidate_handle = None

    # ------------------------------------------------------------------
    # 视图解析
    # ------------------------------------------------------------------

    def _view_for(self, thread_id: str) -> ThreadView:
        if thread_id not in self.views:
            reducer = EventReducer(
                mode=self._mode,
                target=self._target,
                permission=self._permission,
                model=self._model,
                project=self._project,
            )
            view = ThreadView(thread_id=thread_id, reducer=reducer)
            view.store.color = self.color
            view.store.items = view.reducer.items
            self.views[thread_id] = view
        return self.views[thread_id]

    @property
    def view(self) -> ThreadView:
        return self._view_for(self.thread_id)

    @property
    def reducer(self) -> EventReducer:
        return self.view.reducer

    @property
    def store(self) -> ItemStore:
        return self.view.store

    # ------------------------------------------------------------------
    # 启动头
    # ------------------------------------------------------------------

    def show_header(self) -> None:
        self.notice(f"ElectroMind {version_string()}", "notice")
        project = self.reducer.status.project or __import__("pathlib").Path.cwd().name
        self.notice(
            f"{project} · {self.reducer.status.target} · {self.reducer.status.permission}"
            f" · {self.reducer.status.model}",
            "notice",
        )
        self.notice("Type /help for commands", "notice")

    def notice(self, text: str, kind: str = "notice") -> None:
        del kind
        self.reducer.system_notice(text)
        self.invalidate()

    def clear_timeline(self) -> None:
        """/clear：清空当前视图时间线与渲染缓存（状态行保留）。"""
        view = self.view
        view.reducer.items.clear()
        view.store._cache.clear()
        self.invalidate()

    # ------------------------------------------------------------------
    # 事件入口（client.event_sink）
    # ------------------------------------------------------------------

    def handle_event(self, line: dict) -> None:
        """客户端事件 → 对应 Thread 视图；当前视图同步状态机。

        验收 G-3：按 seq 去重——重复 event_id/seq（重放/幂等回放）不重复渲染。
        """
        method = line.get("method", "")
        params = line.get("params", {}) or {}
        thread_id = str(params.get("thread_id", ""))
        if not thread_id:
            return
        view = self._view_for(thread_id)
        seq = params.get("seq")
        if isinstance(seq, int) and seq <= view.last_seq:
            return  # 已渲染过的重复事件
        if isinstance(seq, int):
            view.last_seq = seq
        touched = self._apply_event(view, method, params)
        if touched == "all":
            view.store.invalidate_all()
        elif touched:
            view.store.invalidate(touched)
        if thread_id == self.thread_id:
            self._update_state(method, params)
            self.invalidate()

    def _apply_event(self, view: ThreadView, method: str, params: dict) -> str:
        """协议事件 → reducer（返回被触碰条目 id）。"""
        reducer = view.reducer
        if method == "run/started":
            view.active_run_id = str(params.get("run_id", ""))
            reducer.run_status("generating")
            return ""
        if method == "item/delta":
            kind = params.get("kind")
            text = str(params.get("text", ""))
            if kind == "text":
                view.last_assistant_text += text
                return reducer.handle(TextDelta(text))
            if kind == "reasoning":
                return reducer.handle(ReasoningDelta(text))
            return ""
        if method == "item/started" and params.get("kind") == "tool":
            return reducer.handle(
                ToolCallBegin(
                    str(params.get("tool_call_id", "")),
                    str(params.get("name", "")),
                    str(params.get("arguments", "")),
                )
            )
        if method == "item/completed" and params.get("kind") == "tool":
            return reducer.handle(
                ToolResult(
                    str(params.get("tool_call_id", "")),
                    str(params.get("name", "")),
                    str(params.get("content", "")),
                    ok=bool(params.get("ok", False)),
                )
            )
        if method == "approval/requested":
            item = reducer.approval_pending(
                str(params.get("tool_call_id", "")),
                name=str(params.get("name", "")),
                command=str(params.get("summary", "")),
                target=str(params.get("target", "")),
                workdir=str(params.get("workdir", "")),
                risk=str(params.get("risk", "")),
                approval_id=str(params.get("approval_id", "")),
            )
            view.pending_approval = item
            return item.id
        if method == "approval/resolved":
            tool_call_id = str(params.get("tool_call_id", ""))
            view.pending_approval = None
            reducer.approval_resolved(
                tool_call_id,
                bool(params.get("approved", False)),
                expired=str(params.get("status", "")) == "expired",
            )
            return f"approval-{tool_call_id}"
        if method == "run/completed":
            view.active_run_id = ""
            stop_reason = str(params.get("stop_reason", "completed"))
            return reducer.handle(RunEnd(turn=0, stop_reason=stop_reason))
        if method == "input/state":
            request_id = str(params.get("request_id", ""))
            state = str(params.get("state", ""))
            if request_id and request_id in self._delivery_pending:
                item_id = self._delivery_pending[request_id]
                item = self._find_item(view, item_id)
                if item is not None and hasattr(item, "delivery"):
                    item.delivery = state
                    # 终态后解除关联（queued→applied 全链路仍可持续更新）
                    if state in ("applied", "deferred", "rejected"):
                        self._delivery_pending.pop(request_id, None)
                    return item_id
            return ""
        return ""

    def _update_state(self, method: str, params: dict) -> None:
        """当前视图的状态机（背景 Thread 的事件不触碰）。"""
        if method == "input/state":
            state = str(params.get("state", ""))
            self.delivery = state
            if state in ("queued", "immediate_pending", "accepted"):
                self.state = "running"
            elif state == "rejected":
                self.state = "idle"
        elif method == "run/started":
            self.state = "running"
            self._active_run_id = str(params.get("run_id", ""))
        elif method == "run/completed":
            self.state = "idle"
            self.delivery = ""
            self._active_run_id = ""
            self.pending_approval = None
            self.view.pending_approval = None
            self._refresh_context_pct()
        elif method == "approval/requested":
            self.state = "approval"
            self._active_run_id = str(params.get("run_id", ""))
            self.pending_approval = self.view.pending_approval
        elif method == "approval/resolved":
            self.pending_approval = None
            self.state = (
                "running"
                if self.client is not None
                and self.client.has_active_run(self.thread_id)
                else "idle"
            )

    def _refresh_context_pct(self) -> None:
        if self.client is None:
            return
        runner = self.client.runner(self.thread_id)
        if runner is None:
            return
        self.reducer.set_context_pct(_context_pct(runner, self.reducer.status.model))

    # ------------------------------------------------------------------
    # 输入路由（由 keymap 调用）
    # ------------------------------------------------------------------

    def send_line(self, line: str | None) -> None:
        self.input_queue.put_nowait(line)

    def send_turn(self, text: str, delivery: str = "auto") -> None:
        """发送输入（auto=新 Run / immediate=steer / enqueue=FIFO）。

        乐观渲染：用户消息立即进入时间线（验收 P0-3），input/state 事件
        驱动交付状态（accepted/applied/queued/deferred/rejected）。
        """
        from electromind.harness.identity import new_request_id

        client = self.client
        if client is None:
            self.notice("(未接入 Harness 客户端)")
            return
        thread_id = self.thread_id
        request_id = new_request_id()
        item = self.reducer.user_message(text)
        # 等待 input/state 回填交付状态（queued/immediate_pending/applied/
        # deferred/rejected）—— 关联保留到终态，不因首个状态提前解除
        self._delivery_pending[request_id] = item.id

        async def _send() -> None:
            try:
                await client.send_input(
                    thread_id,
                    text,
                    delivery=delivery,
                    request_id=request_id,
                    mode=self.reducer.status.mode,
                )
            except Exception as exc:
                self.notice(f"发送失败: {type(exc).__name__}: {exc}")

        asyncio.create_task(_send())
        self.invalidate()

    def cancel_run(self) -> None:
        if self.client is None:
            return
        if self.pending_approval is not None:
            self.resolve_approval(approved=False)
        self.reducer.run_status("cancelling")
        # 精确绑定当前 Run：迟到 Cancel 不作用于新 Run（验收 P0-4）
        asyncio.create_task(
            self.client.cancel_run(self.thread_id, run_id=self._active_run_id or None)
        )
        self.invalidate()

    def resolve_approval(self, *, approved: bool) -> None:
        item = self.pending_approval
        client = self.client
        if item is None or client is None:
            return

        async def _resolve() -> None:
            await client.resolve_approval(
                self.thread_id,
                self._active_run_id,
                item.approval_id,
                approved,
                tool_call_id=item.tool_call_id,
            )

        asyncio.create_task(_resolve())

    def copy_last_reply(self) -> None:
        text = self.view.last_assistant_text
        if not text:
            self.notice("（还没有可复制的回复）")
            return
        if self.pt_app is not None:
            self.pt_app.clipboard.set_text(text)
        try:
            import subprocess

            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=False)
        except Exception:
            pass
        self.notice("已复制最近回复")

    def scroll(self, direction: int) -> None:
        if self.pane is None:
            return
        page = max(1, self.pt_app.output.get_size().rows - 3) if self.pt_app else 10
        self.pane.stick_to_bottom = False
        self.pane.vertical_scroll = max(0, self.pane.vertical_scroll - direction * page)

    def _composer_prefix(self) -> str:
        mode_prefix = MODE_PREFIX.get(self.reducer.status.mode, "Run> ")
        if self.delivery:
            label = DELIVERY_LABELS.get(self.delivery, self.delivery)
            return f"{mode_prefix}{c(f'[{label}] ', DIM, on=self.color)}"
        if self.pending_approval is not None:
            return f"{mode_prefix}{c('[approval] ', DIM, on=self.color)}"
        return mode_prefix

    # ------------------------------------------------------------------
    # 视图切换（/resume、/new：不关闭旧 Runner）
    # ------------------------------------------------------------------

    async def switch_thread(self, thread_id: str) -> None:
        """切换当前视图；旧 Thread 的 Runner 与后台 Run 不受影响。"""
        view = self._view_for(thread_id)
        self.thread_id = thread_id
        self.pending_approval = None
        self.delivery = ""
        if self.client is not None and not view.hydrated:
            try:
                runner = await self.client.get_runner(thread_id)
                self._hydrate(view, runner)
            except BaseException as exc:
                self.notice(f"打开会话失败: {type(exc).__name__}: {exc}")
            view.hydrated = True
        self.invalidate()

    def _hydrate(self, view: ThreadView, runner) -> None:
        """恢复会话：把磁盘历史消息灌进视图时间线（用户/助手消息）。"""
        messages = getattr(runner, "messages", None)
        if messages is None:
            return
        for message in messages.data:
            role = getattr(message, "role", "")
            content = str(getattr(message, "content", ""))
            if not content:
                continue
            if role == "user":
                view.reducer.user_message(content)
            elif role == "assistant":
                view.reducer.append_item(
                    AssistantMessageItem(
                        id=view.reducer._next_id("assistant"), text=content, done=True
                    )
                )

    # ------------------------------------------------------------------
    # Slash Popup
    # ------------------------------------------------------------------

    def set_slash_entries(self, entries: list[tuple[str, str]]) -> None:
        self.slash_entries = entries

    def open_slash_popup(self) -> None:
        self._slash_command = "/"
        self.slash_selected = 0
        self.slash_buffer.text = ""
        self.overlay = {"kind": "slash"}
        self.invalidate()
        if self.pt_app is not None:
            self.pt_app.set_focus(self.slash_buffer)

    def open_session_picker(self) -> None:
        """/resume 无参：TUI 内会话选择器 overlay（复用 slash popup 的模糊搜索）。"""
        from ..sessions import list_sessions

        sessions = list_sessions()
        if not sessions:
            self.notice("没有可恢复的会话")
            return
        self.overlay = {
            "kind": "sessions",
            "sessions": [(s.id, s.title or "(无标题)") for s in sessions],
            "selected": 0,
        }
        self.slash_selected = 0
        self.slash_buffer.text = ""
        self.invalidate()
        if self.pt_app is not None:
            self.pt_app.set_focus(self.slash_buffer)

    def open_help(self) -> None:
        """/help：Help overlay（Esc 关闭，不污染时间线）。"""
        from ..repl import format_slash_help

        lines = format_slash_help().splitlines()
        lines.append("")
        lines.append(
            "Keys: Enter 发送 · Alt+Enter 换行 · Esc 取消/关闭 · Ctrl+C 取消/清空/退出"
        )
        lines.append(
            "      Ctrl+R 历史 · Ctrl+O 复制回复 · o 查看 Tool 输出 · Tab 运行中排队"
        )
        self.overlay = {"kind": "text", "title": "Help", "lines": lines}

    # -- 选择器（model / target / files）：复用 popup 机制 -----------------

    MODEL_CANDIDATES = (
        ("deepseek-v4-flash", "默认模型"),
        ("deepseek-v4-pro", "更强推理"),
        ("deepseek-reasoner", "深度推理"),
        ("deepseek-chat", "通用对话"),
    )

    TARGET_CANDIDATES = (
        ("sandbox", "容器沙箱（默认）"),
        ("local", "本地执行（需显式选择）"),
        ("ssh", "远程 SSH"),
    )

    def _open_selector(self, kind: str, entries: list[tuple[str, str]]) -> None:
        self.overlay = {"kind": kind, "entries": entries, "selected": 0}
        self.slash_selected = 0
        self.slash_buffer.text = ""
        self.invalidate()
        if self.pt_app is not None:
            self.pt_app.set_focus(self.slash_buffer)

    def open_model_selector(self) -> None:
        self._open_selector("model", list(self.MODEL_CANDIDATES))

    def open_target_selector(self) -> None:
        self._open_selector("target", list(self.TARGET_CANDIDATES))

    def open_file_picker(self) -> None:
        """文件浏览：项目相对路径，Enter 插入 Composer。"""
        from .completer import list_project_files

        project = self._project_root()
        files = [(path, "") for path in list_project_files(project, limit=40)]
        if not files:
            self.notice("（项目目录为空或不可读）")
            return
        self._open_selector("files", files)

    def _project_root(self) -> str:
        runner = self.client.runner(self.thread_id) if self.client is not None else None
        project = getattr(getattr(runner, "thread", None), "project_path", "") or ""
        return str(project) if project else __import__("os").getcwd()

    _PICKER_KINDS = ("slash", "sessions", "model", "target", "files")

    def _filtered_slash(self) -> list[tuple[str, str]]:
        """当前 overlay 的候选列表，按输入过滤（模糊搜索）。"""
        if self.overlay is not None and self.overlay.get("kind") in (
            "sessions",
            "model",
            "target",
            "files",
        ):
            entries = list(
                self.overlay.get("entries", self.overlay.get("sessions", []))
            )
        else:
            entries = self.slash_entries
        query = self.slash_buffer.text.strip()
        if not query:
            return entries
        return [
            (name, summary)
            for name, summary in entries
            if query in name or query in summary
        ]

    def popup_select(self, delta: int) -> None:
        count = len(self._filtered_slash())
        if count == 0:
            return
        self.slash_selected = (self.slash_selected + delta) % count
        self.invalidate()

    def popup_confirm(self) -> None:
        entries = self._filtered_slash()
        if not entries:
            self.close_overlay()
            return
        kind = self.overlay.get("kind") if self.overlay is not None else "slash"
        name, _ = entries[self.slash_selected]
        self.close_overlay()
        if kind == "sessions":
            self.send_line(f"/resume {name}")
        elif kind == "model":
            self.send_line(f"/model {name}")
        elif kind == "target":
            self.send_line(f"/target {name}")
        elif kind == "files":
            self.composer_buffer.insert_text(name)  # 插入 Composer（@ 风格路径）
        else:
            self.send_line(f"/{name}")

    def close_overlay(self) -> None:
        if self.overlay is not None:
            self.overlay = None
            self.invalidate()
            if self.pt_app is not None:
                self.pt_app.set_focus(self.composer_buffer)

    # ------------------------------------------------------------------
    # ! 命令（当前 Execution Target；经 sandbox Commands.run 的权限生命周期）
    # ------------------------------------------------------------------

    async def run_shell_command(self, command: str) -> None:
        import time

        from .view_model import ToolItem

        runner = self.client.runner(self.thread_id) if self.client is not None else None
        sandbox = getattr(runner, "sandbox", None)
        workdir = getattr(sandbox, "workdir", "") or ""
        item = ToolItem(
            id=f"shell-{self._shell_seq}",
            name="Command",
            args_summary=command,
            target=self.reducer.status.target,
            workdir=workdir,
            status="running",
        )
        self._shell_seq += 1
        self.reducer.append_item(item)
        self.reducer.run_status("running_tool")
        self.invalidate()

        start = time.monotonic()
        try:
            result = await sandbox.commands.run(command)
        except Exception as exc:
            item.status = "failed"
            item.output_preview = f"{type(exc).__name__}: {exc}"
            item.full_output = item.output_preview
        else:
            item.status = "ok" if result.exit_code == 0 else "failed"
            item.exit_code = result.exit_code
            item.duration_s = round(time.monotonic() - start, 1)
            parts = [
                getattr(result, "stdout", "") or "",
                getattr(result, "stderr", "") or "",
            ]
            output = "\n".join(part for part in parts if part)
            item.output_lines = output.count("\n") + 1 if output.strip() else 0
            item.output_preview = " ".join(output.split())[:160]
            item.full_output = output[:MAX_TOOL_OUTPUT_CHARS]
        self.reducer.run_status("idle")
        self.store.invalidate(item.id)
        self.invalidate()

    # ------------------------------------------------------------------
    # Tool 输出查看（o 键 → Overlay）
    # ------------------------------------------------------------------

    def open_last_tool_output(self) -> None:
        tool = self._last_completed_tool()
        if tool is None:
            self.notice("（还没有已完成的 Tool 输出）")
            return
        lines = (tool.full_output or tool.output_preview or "(no output)").splitlines()
        self.overlay = {
            "kind": "text",
            "title": f"Output: {tool.name}",
            "lines": lines,
        }

    @staticmethod
    def _find_item(view, item_id: str):
        for item in view.reducer.items:
            if getattr(item, "id", "") == item_id:
                return item
        return None

    def _last_completed_tool(self):
        for item in reversed(self.reducer.items):
            if getattr(item, "kind", "") == "tool" and item.status in ("ok", "failed"):
                return item
        return None

    # ------------------------------------------------------------------
    # prompt_toolkit 应用
    # ------------------------------------------------------------------

    # Delta 批处理（R6）：流式事件在 ~30ms 窗口内合并为一次重绘，
    # 不因每个 Token 重绘完整界面。
    INVALIDATE_BATCH_MS = 0.03

    def invalidate(self) -> None:
        if self.pt_app is None or self._invalidate_scheduled:
            return
        self._invalidate_scheduled = True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            self._invalidate_handle = loop.call_later(
                self.INVALIDATE_BATCH_MS, self._flush_invalidate
            )
        else:
            self._flush_invalidate()

    def _flush_invalidate(self) -> None:
        self._invalidate_scheduled = False
        self._invalidate_handle = None
        if self.pt_app is not None:
            self.pt_app.invalidate()

    def flush_invalidate_now(self) -> None:
        """退出/切视图等关键节点立即重绘（取消合并窗口）。"""
        if self._invalidate_handle is not None:
            self._invalidate_handle.cancel()
            self._invalidate_handle = None
        self._invalidate_scheduled = False
        if self.pt_app is not None:
            self.pt_app.invalidate()

    def build(self) -> Application:
        kb = build_key_bindings(self)
        self.pane = components.transcript_pane(self.store)

        status_win = components.status_line(self.store, self.reducer.status)
        composer_win = components.composer_window(
            self.composer_buffer,
            get_prefix=self._composer_prefix,
            completer=CliCompleter(self),
        )
        search_win = _search_toolbar(self.composer_buffer)
        body = HSplit([self.pane, status_win, search_win, composer_win])

        floats: list[Float] = []
        floats.append(
            Float(
                content=_conditional(
                    lambda: components.approval_card(
                        "Approval required",
                        self._approval_body(),
                        color=self.color,
                    ),
                    lambda: self.pending_approval is not None,
                ),
                left=4,
                top=4,
                transparent=False,
            )
        )
        floats.append(
            Float(
                content=_conditional(
                    lambda: Window(
                        FormattedTextControl(lambda: self._slash_popup_text()),
                        style="class:popup-list",
                    ),
                    lambda: (
                        self.overlay is not None
                        and self.overlay.get("kind") in self._PICKER_KINDS
                    ),
                ),
                left=0,
                top=0,
            )
        )
        floats.append(
            Float(
                content=_conditional(
                    lambda: Window(
                        FormattedTextControl(lambda: self._text_overlay_text()),
                        style="class:text-overlay",
                    ),
                    lambda: (
                        self.overlay is not None and self.overlay.get("kind") == "text"
                    ),
                ),
                left=2,
                top=1,
            )
        )

        container = FloatContainer(body, floats)
        self.pt_app = Application(
            layout=Layout(container),
            key_bindings=kb,
            full_screen=self.full_screen,
        )
        return self.pt_app

    def _approval_body(self) -> list[str]:
        item = self.pending_approval
        if item is None:
            return [""]
        return [
            f"Tool      {item.name}",
            f"Command   {item.command}",
            f"Target    {item.target or '—'}",
            f"Workdir   {item.workdir or '—'}",
            f"Risk      {item.risk or '—'}",
        ]

    def _slash_popup_text(self) -> str:
        entries = self._filtered_slash()
        if self.slash_selected >= len(entries):
            self.slash_selected = 0
        lines: list[str] = []
        for idx, (name, summary) in enumerate(entries[:12]):
            marker = ">" if idx == self.slash_selected else " "
            if idx == self.slash_selected:
                lines.append(
                    c(f"{marker} /{name}", "\033[36m", on=self.color)
                    + c(f"  {summary}", DIM, on=self.color)
                )
            else:
                lines.append(f"{marker} /{name}  {summary}")
        if not lines:
            lines.append("(no matches)")
        return "\n".join(lines)

    def _text_overlay_text(self) -> str:
        if self.overlay is None:
            return ""
        lines = self.overlay.get("lines", [])
        visible = lines[:MAX_OUTPUT_OVERLAY_LINES]
        text = "\n".join(visible)
        return f"─ {self.overlay.get('title', '')} ─\n{text}"


def _conditional(render_fn, visible_fn):
    """prompt_toolkit 3.0.52：Float 无 hidden 参数，用 DynamicContainer 条件渲染。"""
    from prompt_toolkit.layout import DynamicContainer
    from prompt_toolkit.layout.containers import HSplit as _HSplit

    def content():
        if not visible_fn():
            return _HSplit([])  # 零高度占位
        return render_fn()

    return DynamicContainer(content)


def _search_toolbar(buffer: Buffer) -> Window:
    def content() -> str:
        state = buffer.search_state
        if state is None or not state.text:
            return ""
        return f"Search: {state.text}  [Ctrl+G 取消]"

    return Window(
        FormattedTextControl(content),
        height=Dimension.exact(1),
        dont_extend_height=True,
        style="class:search-toolbar",
    )


def _context_pct(runner, model: str) -> int | None:
    """消息 token 估计 / 模型上下文窗口 → 百分比（失败返回 None）。"""
    try:
        import tiktoken

        from electromind.core.context_limit import resolve_context_limit

        enc = tiktoken.get_encoding("cl100k_base")
        total = sum(
            len(enc.encode(str(message.content))) for message in runner.messages.data
        )
        limit = resolve_context_limit(model)
        return min(100, total * 100 // limit) if limit else None
    except Exception:
        return None
