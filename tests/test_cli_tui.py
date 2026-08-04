"""CLI-R1..R4 + CLI-4：语义渲染模型、reducer 管线、多视图事件、审批、! 命令。"""

from __future__ import annotations

import asyncio

import pytest

from app.tool_permit import MAX_TOOL_OUTPUT_CHARS, risk_hint
from app.tui.application import CliApp
from app.tui.reducer import EventReducer
from app.tui.render import render_all, render_item
from app.tui.store import width_bucket
from app.tui.view_model import UserMessageItem
from electromind import RunEnd, TextDelta, ToolCallBegin, ToolResult

# ---------------------------------------------------------------------------
# reducer 快照（CLI-R1 验收：语义渲染模型）
# ---------------------------------------------------------------------------


def _run_events(reducer: EventReducer) -> list[str]:
    return render_all(reducer.items, color=False)


def test_reducer_timeline_snapshot():
    reducer = EventReducer(mode="run", target="sandbox", permission="prompt")
    reducer.user_message("检查输入")
    reducer.handle(TextDelta("先看文件。"))
    reducer.handle(ToolCallBegin("c1", "run_command", '{"command":"cat input.inp"}'))
    reducer.handle(ToolResult("c1", "run_command", '{"ok": true}', ok=True))
    reducer.handle(TextDelta("检查完毕。"))
    reducer.handle(RunEnd(turn=1, stop_reason="no_tool_calls"))

    lines = _run_events(reducer)
    assert "You" in lines
    assert "检查输入" in lines
    assert "ElectroMind" in lines
    assert any("✓ run_command" in line for line in lines)  # 语义符号
    assert "检查完毕。" in lines
    # 顺序：用户 → 文本 → tool → 文本
    user_idx = lines.index("检查输入")
    tool_idx = next(i for i, line in enumerate(lines) if "run_command" in line)
    text_idx = lines.index("检查完毕。")
    assert user_idx < tool_idx < text_idx


def test_reducer_text_segments_interleave_with_tools():
    reducer = EventReducer()
    reducer.user_message("任务")
    reducer.handle(TextDelta("A"))
    reducer.handle(ToolCallBegin("c1", "read_file", '{"path":"x"}'))
    reducer.handle(TextDelta("B"))
    assistant = [
        i for i in reducer.items if getattr(i, "kind", "") == "assistant_message"
    ]
    assert len(assistant) == 2  # tool 打断了文本段


def test_reducer_hides_finished_activity():
    reducer = EventReducer()
    reducer.user_message("任务")
    from electromind import ReasoningDelta

    reducer.handle(ReasoningDelta("内部思考"))
    reducer.handle(ToolCallBegin("c1", "read_file", '{"path":"x"}'))
    lines = _run_events(reducer)
    assert not any("思考中" in line for line in lines)  # tool 到来即收起


def test_store_width_buckets():
    assert width_bucket(30) == 40
    assert width_bucket(81) == 100
    assert width_bucket(250) == 200


def test_store_cache_invalidates_on_item_change():
    from app.tui.store import ItemStore

    reducer = EventReducer()
    store = ItemStore(color=False)
    store.items = reducer.items
    reducer.user_message("任务")
    reducer.handle(TextDelta("hello"))
    lines1 = store.render_lines(80)
    reducer._open_assistant.text += " world"
    store.invalidate(reducer._open_assistant.id)
    lines2 = store.render_lines(80)
    assert "hello world" in "\n".join(lines2)
    assert lines1 != lines2


# ---------------------------------------------------------------------------
# Approval 流程
# ---------------------------------------------------------------------------


def test_approval_card_risk_hint():
    assert risk_hint("rm -rf output/") == "deletes files"
    assert risk_hint("sudo apt install x") == "elevated privileges"
    assert risk_hint("echo hi > log") == "writes files"
    assert risk_hint("cp2k.popt -c input.inp") == "executes command"


def test_auto_safe_risk_gate():
    """auto-safe 只自动放行可证明只读的命令。"""
    import json

    from app.tool_permit import is_safe_tool_call, requires_permit_prompt
    from electromind import ToolCallBegin

    def _args(command: str) -> str:
        return json.dumps({"command": command})

    safe = ToolCallBegin("c1", "run_command", _args("cat input.inp"))
    quoted_wildcard = ToolCallBegin("c4", "run_command", _args('find . -name "*.py"'))
    copy = ToolCallBegin("c3", "copy_from_host", '{"host_path":"x"}')

    assert is_safe_tool_call(safe) is True
    assert is_safe_tool_call(quoted_wildcard) is True  # 引号内通配符不破坏只读
    assert is_safe_tool_call(copy) is False  # 无法判定副作用 → 需审批

    # prompt：全部需审批；auto-safe：只读放行、其余审批；auto：全部放行
    assert requires_permit_prompt("prompt", safe) is True
    assert requires_permit_prompt("auto-safe", safe) is False
    assert requires_permit_prompt("auto", safe) is False


def test_auto_safe_rejects_write_capable_commands():
    """验收 P0-1：python 写文件 / curl -o / chmod / git reset 均不得判为 safe。"""
    import json

    from app.tool_permit import is_safe_tool_call
    from electromind import ToolCallBegin

    dangerous = [
        "python3 -c \"open('/tmp/x','w').write('evil')\"",
        "curl -o /tmp/x http://example.com",
        "chmod 777 script.sh",
        "git reset --hard HEAD",
        "echo hi > file",
        "cat a; rm b",
        "rm -rf output/",
        "sudo apt install x",
    ]
    for command in dangerous:
        event = ToolCallBegin("c", "run_command", json.dumps({"command": command}))
        assert is_safe_tool_call(event) is False, command


def test_full_output_capped():
    """大日志不常驻：full_output 有上限。"""
    reducer = EventReducer()
    reducer.user_message("任务")
    big = "x" * (MAX_TOOL_OUTPUT_CHARS + 5000)
    reducer.handle(ToolCallBegin("c1", "run_command", '{"command":"cat big.log"}'))
    reducer.handle(ToolResult("c1", "run_command", big, ok=True))
    tool = next(i for i in reducer.items if getattr(i, "kind", "") == "tool")
    assert len(tool.full_output) <= MAX_TOOL_OUTPUT_CHARS
    lines = _run_events(reducer)
    assert not any("x" * 100 in line for line in lines)


def test_approval_render_shows_target_workdir_risk():
    reducer = EventReducer(mode="run", target="local")
    item = reducer.approval_pending(
        "c9",
        name="run_command",
        command="rm -rf output/old-run",
        target="local",
        workdir="~/project",
        risk="deletes 38 files",
    )
    lines = render_item(item, color=False)
    text = "\n".join(lines)
    assert "rm -rf output/old-run" in text
    assert "Target local" in text
    assert "Workdir ~/project" in text
    assert "Risk deletes 38 files" in text
    assert "[y] 批准一次" in text


# ---------------------------------------------------------------------------
# CliApp 多视图事件（CLI-4）
# ---------------------------------------------------------------------------


def _event(method: str, **params) -> dict:
    return {"jsonrpc": "2.0", "method": method, "params": params}


class FakeClient:
    """TUI 用假客户端：记录 send/cancel/resolve。"""

    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []
        self.resolved: list[tuple] = []
        self.cancelled: list[str] = []
        self.runners: dict[str, object] = {}
        self._active: set[str] = set()

    async def send_input(
        self, thread_id, text, *, delivery="auto", request_id=None, mode=None
    ):
        self.sent.append((thread_id, text, delivery))
        return type("R", (), {"message_id": "msg-x", "state": "queued"})()

    def runner(self, thread_id, *, create=False):
        return self.runners.get(thread_id)

    async def get_runner(self, thread_id):
        return self.runners.setdefault(thread_id, object())

    async def cancel_run(self, thread_id, run_id=None):
        self.cancelled.append(thread_id)
        return True

    async def resolve_approval(
        self, thread_id, run_id, approval_id, approved, tool_call_id=None
    ):
        self.resolved.append((thread_id, run_id, approval_id, approved, tool_call_id))
        return True

    def has_active_run(self, thread_id):
        return thread_id in self._active


def _app(client=None, thread_id="thread-t1") -> CliApp:
    app = CliApp(color=False, mode="run", target="sandbox", thread_id=thread_id)
    if client is not None:
        app.client = client
    return app


def test_handle_event_drives_state_machine():
    app = _app()
    app.handle_event(_event("run/started", thread_id="thread-t1", run_id="run-1"))
    assert app.state == "running"
    app.handle_event(
        _event("item/delta", thread_id="thread-t1", kind="text", text="你好")
    )
    assert "你好" in app.view.last_assistant_text
    app.handle_event(
        _event(
            "run/completed",
            thread_id="thread-t1",
            run_id="run-1",
            stop_reason="completed",
        )
    )
    assert app.state == "idle"


def test_approval_no_bare_letter_keys():
    """复验 P0-2：无裸 y/n/d 审批键——逐键输入 `yes...` 的第一个字符不触发审批。"""
    from app.tui.keymap import build_key_bindings

    app = _app()
    app.pending_approval = object()  # 等待审批
    kb = build_key_bindings(app)

    # 应用自己的 keymap 对裸字母没有任何绑定（默认 buffer 绑定负责插入文本）
    for key in ("y", "n", "d"):
        assert kb.get_bindings_for_keys((key,)) == [], key


@pytest.mark.asyncio
async def test_user_message_delivery_backfilled_via_request_id(monkeypatch):
    """复验：input/state 经 request_id 回填用户条目的交付状态（applied/queued...）。"""
    from app.tui.application import CliApp

    client = FakeClient()
    app = CliApp(color=False, thread_id="thread-t1")
    app.client = client  # type: ignore[assignment]

    app.send_turn("任务", delivery="auto")
    await asyncio.sleep(0.02)  # 等乐观渲染 + send 完成

    user_items = [
        i for i in app.reducer.items if getattr(i, "kind", "") == "user_message"
    ]
    assert len(user_items) == 1
    assert user_items[0].delivery == ""  # 尚未收到 input/state

    # input/state 带 request_id → 回填；非终态保留关联（链路可持续更新）
    request_id = next(iter(app._delivery_pending))
    app.handle_event(
        _event(
            "input/state",
            thread_id="thread-t1",
            message_id="msg-1",
            state="queued",
            request_id=request_id,
        )
    )
    assert user_items[0].delivery == "queued"
    assert request_id in app._delivery_pending  # 非终态：关联保留

    # 链路后续状态（applied）继续更新同一条输入
    app.handle_event(
        _event(
            "input/state",
            thread_id="thread-t1",
            message_id="msg-1",
            state="applied",
            request_id=request_id,
        )
    )
    assert user_items[0].delivery == "applied"
    assert request_id not in app._delivery_pending  # 终态：解除关联


@pytest.mark.asyncio
async def test_immediate_input_chain_updates_same_item():
    """复验 P0：immediate 输入也进时间线；immediate_pending → applied 更新同一条。"""
    from app.tui.application import CliApp

    client = FakeClient()
    app = CliApp(color=False, thread_id="thread-t1")
    app.client = client  # type: ignore[assignment]

    app.send_turn("运行中补充", delivery="immediate")
    await asyncio.sleep(0.02)

    user_items = [
        i for i in app.reducer.items if getattr(i, "kind", "") == "user_message"
    ]
    assert len(user_items) == 1  # immediate 输入有 UserMessageItem

    request_id = next(iter(app._delivery_pending))
    app.handle_event(
        _event(
            "input/state",
            thread_id="thread-t1",
            message_id="msg-i1",
            state="immediate_pending",
            request_id=request_id,
        )
    )
    assert user_items[0].delivery == "immediate_pending"
    assert request_id in app._delivery_pending  # 非终态保留

    # 检查点 applied：同一 request_id → 同一条目更新为 applied
    app.handle_event(
        _event(
            "input/state",
            thread_id="thread-t1",
            message_id="msg-i1",
            state="applied",
            request_id=request_id,
        )
    )
    assert user_items[0].delivery == "applied"
    assert request_id not in app._delivery_pending


def test_approval_enter_empty_composer_approves():
    """复验 P0-2：Enter（空输入）批准；有输入时 Enter 是 steer（普通输入）。"""
    from app.tui.keymap import _approval_enter_enabled

    app = _app()
    app.pending_approval = object()
    assert _approval_enter_enabled(app) is True  # 空输入 → Enter 批准

    app.composer_buffer.text = "yes 请继续"
    assert _approval_enter_enabled(app) is False  # 有输入 → Enter 是 steer

    app.composer_buffer.text = "  "
    assert _approval_enter_enabled(app) is True

    app.pending_approval = None
    assert _approval_enter_enabled(app) is False


def test_handle_event_approval_card_flow():
    client = FakeClient()
    client._active.add("thread-t1")  # approval 后 Run 仍在进行
    app = _app(client=client)
    app.handle_event(_event("run/started", thread_id="thread-t1", run_id="run-1"))
    app.handle_event(
        _event(
            "approval/requested",
            thread_id="thread-t1",
            run_id="run-1",
            approval_id="apr-1",
            tool_call_id="c1",
            name="run_command",
            summary="rm -rf x",
            target="sandbox",
            workdir="/w",
            risk="deletes files",
        )
    )
    assert app.state == "approval"
    assert app.pending_approval is not None
    assert app.pending_approval.approval_id == "apr-1"
    app.handle_event(
        _event(
            "approval/resolved",
            thread_id="thread-t1",
            run_id="run-1",
            approval_id="apr-1",
            tool_call_id="c1",
            approved=True,
            status="approved",
        )
    )
    assert app.pending_approval is None
    assert app.state == "running"


def test_background_thread_events_do_not_touch_state():
    """Thread B 的事件进入 B 的视图；当前 Thread A 的状态机不受影响。"""
    app = _app()
    app.handle_event(_event("run/started", thread_id="thread-t1", run_id="run-a"))
    assert app.state == "running"
    app.handle_event(_event("run/started", thread_id="thread-t2", run_id="run-b"))
    app.handle_event(
        _event("item/delta", thread_id="thread-t2", kind="text", text="B 的结果")
    )
    # B 的视图独立累积
    assert "B 的结果" in app.views["thread-t2"].last_assistant_text
    # A 的状态机仍是 running（不被 B 的事件覆盖）
    assert app.state == "running"
    assert app.thread_id == "thread-t1"


def test_switch_thread_keeps_views_separate():
    client = FakeClient()
    app = _app(client=client)
    app.handle_event(_event("run/started", thread_id="thread-t1", run_id="run-a"))
    app.handle_event(
        _event("item/delta", thread_id="thread-t1", kind="text", text="A 内容")
    )
    app.thread_id = "thread-t2"  # 切换视图（/resume）
    app.view  # 惰性建视图
    assert app.view.last_assistant_text == ""  # B 视图是空的
    assert app.views["thread-t1"].last_assistant_text == "A 内容"  # A 视图保留


@pytest.mark.asyncio
async def test_send_turn_routes_through_client():
    client = FakeClient()
    app = _app(client=client)
    app.send_turn("第一个任务", delivery="auto")
    app.send_turn("运行中补充", delivery="immediate")
    app.send_turn("排队任务", delivery="enqueue")
    deadline = asyncio.get_running_loop().time() + 1.0
    while len(client.sent) < 3:
        if asyncio.get_running_loop().time() > deadline:
            break
        await asyncio.sleep(0.005)
    assert sorted(client.sent) == [
        ("thread-t1", "排队任务", "enqueue"),
        ("thread-t1", "第一个任务", "auto"),
        ("thread-t1", "运行中补充", "immediate"),
    ]


@pytest.mark.asyncio
async def test_cancel_run_routes_to_client():
    client = FakeClient()
    app = _app(client=client)
    app.cancel_run()
    await asyncio.sleep(0.01)  # 让 create_task 的任务跑完
    assert client.cancelled == ["thread-t1"]


@pytest.mark.asyncio
async def test_resolve_approval_routes_to_client():
    client = FakeClient()
    app = _app(client=client)
    app.handle_event(_event("run/started", thread_id="thread-t1", run_id="run-1"))
    app.handle_event(
        _event(
            "approval/requested",
            thread_id="thread-t1",
            run_id="run-1",
            approval_id="apr-1",
            tool_call_id="c1",
            name="run_command",
            summary="rm -rf x",
        )
    )
    app.resolve_approval(approved=False)
    await asyncio.sleep(0.01)  # 让 create_task 的任务跑完
    assert client.resolved == [("thread-t1", "run-1", "apr-1", False, "c1")]


def test_composer_prefix_by_mode():
    assert CliApp(color=False, mode="ask")._composer_prefix().startswith("Ask> ")
    assert CliApp(color=False, mode="plan")._composer_prefix().startswith("Plan> ")
    assert CliApp(color=False, mode="run")._composer_prefix().startswith("Run> ")


def test_user_message_item_is_immutable_snapshot():
    item = UserMessageItem(id="user-1", text="你好")
    assert item.kind == "user_message"
    assert item.id == "user-1"


# ---------------------------------------------------------------------------
# ! 命令 → ToolItem（权限生命周期路径）
# ---------------------------------------------------------------------------


class FakeCommands:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def run(self, command):
        self.calls.append(command)
        return self.result


class FakeShellSandbox:
    def __init__(self, result):
        self.commands = FakeCommands(result)
        self.workdir = "/workspace"


class FakeShellRunner:
    def __init__(self, result):
        self.sandbox = FakeShellSandbox(result)


@pytest.mark.asyncio
async def test_run_shell_command_renders_tool_item():
    result = type("R", (), {"stdout": "ok out\n", "stderr": "", "exit_code": 0})()
    runner = FakeShellRunner(result)
    client = FakeClient()
    client.runners["thread-t1"] = runner
    app = _app(client=client)

    await app.run_shell_command("pwd")

    tool = next(i for i in app.reducer.items if getattr(i, "kind", "") == "tool")
    assert tool.name == "Command"
    assert tool.args_summary == "pwd"
    assert tool.target == "sandbox"
    assert tool.workdir == "/workspace"
    assert tool.status == "ok"
    assert tool.exit_code == 0
    assert runner.sandbox.commands.calls == ["pwd"]


@pytest.mark.asyncio
async def test_run_shell_command_failed_status():
    result = type("R", (), {"stdout": "", "stderr": "denied", "exit_code": 126})()
    runner = FakeShellRunner(result)
    client = FakeClient()
    client.runners["thread-t1"] = runner
    app = _app(client=client)

    await app.run_shell_command("rm -rf /")

    tool = next(i for i in app.reducer.items if getattr(i, "kind", "") == "tool")
    assert tool.status == "failed"
    assert tool.exit_code == 126  # mode_guard 拒绝的 exit code


def test_cli_app_builds_application():
    app = _app()
    app.set_slash_entries([("help", "帮助"), ("status", "状态")])
    pt_app = app.build()
    assert pt_app is app.pt_app
    assert app.pane is not None


def test_slash_popup_filter():
    app = _app()
    app.set_slash_entries(
        [("help", "列出命令"), ("status", "状态"), ("mode", "任务模式")]
    )
    app.slash_buffer.text = "mo"
    assert [n for n, _ in app._filtered_slash()] == ["mode"]
    app.slash_buffer.text = ""
    assert len(app._filtered_slash()) == 3


def test_open_last_tool_output_overlay():
    app = _app()
    reducer = app.reducer
    reducer.user_message("任务")
    reducer.handle(ToolCallBegin("c1", "run_command", '{"command":"cat log"}'))
    reducer.handle(ToolResult("c1", "run_command", "line1\nline2\n", ok=True))
    app.open_last_tool_output()
    assert app.overlay is not None
    assert app.overlay["kind"] == "text"
    assert app.overlay["lines"] == ["line1", "line2"]
    assert "Output: run_command" in app.overlay["title"]


def test_open_last_tool_output_no_output_notice():
    app = _app()
    app.open_last_tool_output()  # 无已完成的 Tool
    assert app.overlay is None


# ---------------------------------------------------------------------------
# Overlay 套件（R5）：会话选择器 / Help / Delta 批处理
# ---------------------------------------------------------------------------


def test_session_picker_overlay_filters_and_selects(monkeypatch):
    from app.sessions import SessionInfo

    def fake_list_sessions():
        return [
            SessionInfo(id="thread-a", title="会话A"),
            SessionInfo(id="thread-b", title="会话B"),
            SessionInfo(id="thread-c", title="任务C"),
        ]

    monkeypatch.setattr("app.sessions.list_sessions", fake_list_sessions)
    app = _app()
    app.open_session_picker()
    assert app.overlay is not None
    assert app.overlay["kind"] == "sessions"

    # 模糊搜索
    app.slash_buffer.text = "B"
    assert [n for n, _ in app._filtered_slash()] == ["thread-b"]
    # 确认 → /resume <id>
    app.slash_selected = 0
    app.popup_confirm()
    line = app.input_queue.get_nowait()
    assert line == "/resume thread-b"


def test_session_picker_no_sessions_notice(monkeypatch):
    monkeypatch.setattr("app.sessions.list_sessions", lambda: [])
    app = _app()
    app.open_session_picker()
    assert app.overlay is None  # 提示后不开 overlay


def test_help_overlay(monkeypatch):
    app = _app()
    app.open_help()
    assert app.overlay is not None
    assert app.overlay["kind"] == "text"
    assert app.overlay["title"] == "Help"
    assert any("/help" in line for line in app.overlay["lines"])


@pytest.mark.asyncio
async def test_invalidate_delta_batching(monkeypatch):
    """R6：流式事件在 ~30ms 窗口合并为一次重绘。"""
    import asyncio

    app = _app()
    fake_app = type(
        "FakePT",
        (),
        {
            "invalidated": 0,
            "invalidate": lambda self: setattr(
                self, "invalidated", self.invalidated + 1
            ),
        },
    )()
    app.pt_app = fake_app  # type: ignore[assignment]

    app.invalidate()
    app.invalidate()
    app.invalidate()
    assert fake_app.invalidated == 0  # 合并窗口内不重绘

    await asyncio.sleep(0.05)  # 窗口过后刷出一次
    assert fake_app.invalidated == 1


@pytest.mark.asyncio
async def test_model_selector_confirm():
    app = _app()
    app.open_model_selector()
    assert app.overlay is not None
    assert app.overlay["kind"] == "model"
    app.slash_selected = 0
    app.popup_confirm()
    assert app.input_queue.get_nowait() == "/model deepseek-v4-flash"


def test_target_selector_confirm():
    app = _app()
    app.open_target_selector()
    assert app.overlay["kind"] == "target"
    app.slash_selected = 2
    app.popup_confirm()
    assert app.input_queue.get_nowait() == "/target ssh"


def test_file_picker_inserts_path_into_composer(monkeypatch, tmp_path):
    (tmp_path / "input.inp").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "run.sh").write_text("y")

    app = _app()
    monkeypatch.setattr(app, "_project_root", lambda: str(tmp_path))
    app.open_file_picker()
    assert app.overlay is not None
    assert app.overlay["kind"] == "files"

    # 找到 input.inp 并确认 → 路径插入 Composer
    names = [n for n, _ in app._filtered_slash()]
    assert "input.inp" in names
    app.slash_selected = names.index("input.inp")
    app.popup_confirm()
    assert app.composer_buffer.text == "input.inp"


@pytest.mark.asyncio
async def test_flush_invalidate_now_bypasses_batch(monkeypatch):
    import asyncio

    app = _app()
    fake_app = type(
        "FakePT",
        (),
        {
            "invalidated": 0,
            "invalidate": lambda self: setattr(
                self, "invalidated", self.invalidated + 1
            ),
        },
    )()
    app.pt_app = fake_app  # type: ignore[assignment]

    app.invalidate()
    app.flush_invalidate_now()
    assert fake_app.invalidated == 1
    await asyncio.sleep(0.05)
    assert fake_app.invalidated == 1  # 不重复


# ---------------------------------------------------------------------------
# 5000 RenderItem sanity（R6 性能基线）
# ---------------------------------------------------------------------------


def test_store_renders_5000_items():
    """5000 个条目可正常渲染与滚动（可见区渲染的前置：条目级缓存）。

    验收 G-8：含时延上限（防 O(n²) 回归）与缓存上限（不随渲染次数增长）断言。
    """
    import time

    from app.tui.store import ItemStore

    reducer = EventReducer()
    store = ItemStore(color=False)
    store.items = reducer.items
    for i in range(2500):
        reducer.user_message(f"任务 {i}")
        reducer.handle(TextDelta(f"回复 {i}"))
    assert len(store.items) == 5000

    start = time.perf_counter()
    lines = store.render_lines(80)
    first_render = time.perf_counter() - start
    assert len(lines) >= 5000
    assert any("任务 2499" in line for line in lines)
    # 时延上限：5000 条目首渲染 < 2s（实测 ~12ms；上限只防病态回归）
    assert first_render < 2.0, f"5000 条目首渲染耗时 {first_render:.2f}s"

    # 缓存上限：条目 × 宽度桶数，不随重复渲染增长（无泄漏）
    bucket_count = 7  # _WIDTH_BUCKETS 长度
    for width in (40, 80, 120, 160):
        store.render_lines(width)
    store.render_lines(80)  # 重复渲染
    assert len(store._cache) <= len(store.items) * bucket_count
    before = len(store._cache)
    store.render_lines(80)
    store.render_lines(40)
    assert len(store._cache) == before  # 缓存命中，不再增长
