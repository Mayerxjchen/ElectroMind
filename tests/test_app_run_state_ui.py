"""TUI 状态行与语义条目渲染（替代旧 LayoutTerminal/format_status_label）。"""

from types import SimpleNamespace

from app.tui.components import status_line_text
from app.tui.reducer import EventReducer
from app.tui.render import render_activity, render_tool
from app.tui.store import ItemStore
from app.tui.view_model import StatusLineState
from electromind import RunState, ToolCallBegin


def test_status_line_segments_hide_on_narrow_width():
    status = StatusLineState(
        run_status="generating",
        mode="run",
        target="sandbox",
        permission="prompt",
        model="deepseek-v4-pro",
        project="water",
        context_pct=31,
    )
    segments = status.segments()
    assert segments[0] == "RUN"
    assert "sandbox" in segments
    assert "deepseek-v4-pro" in segments
    assert "ctx 31%" in segments


def test_status_line_priority_order():
    status = StatusLineState(run_status="idle", mode="ask", target="ssh")
    text = status_line_text(status, color=False)
    assert text.startswith("ASK · ssh · idle")


def test_status_line_approval_yellow():
    status = StatusLineState(run_status="approval", mode="run", target="local")
    text = status_line_text(status, color=True)
    assert "\033[33m" in text  # yellow


def test_reducer_creates_tool_item_and_status():
    reducer = EventReducer(mode="run", target="sandbox", permission="prompt")
    reducer.handle(
        ToolCallBegin("call-1", "run_command", '{"command":"cp2k.popt -c input.inp"}')
    )
    reducer.run_status("running_tool")
    assert reducer.status.run_status == "running_tool"
    tool = next(item for item in reducer.items if getattr(item, "kind", "") == "tool")
    assert tool.name == "run_command"
    assert tool.status == "running"


def test_tool_render_uses_semantic_symbols():
    item = SimpleNamespace(
        kind="tool",
        id="call-1",
        name="Command",
        args_summary="cp2k.popt -c input.inp",
        target="sandbox",
        workdir="/workspace",
        status="ok",
        exit_code=0,
        duration_s=2.8,
        output_lines=24,
        output_preview="",
        full_output="",
    )
    lines = render_tool(item, color=False)
    assert lines[0].startswith("✓ Command")
    assert "/workspace" in lines[0]
    assert "cp2k.popt -c input.inp" in lines[1]
    assert "exit 0" in lines[2]
    assert "2.8s" in lines[2]


def test_tool_render_failed_symbol():
    item = SimpleNamespace(
        kind="tool",
        id="call-1",
        name="Command",
        args_summary="cp2k.popt -c input.inp",
        target="sandbox",
        workdir="/workspace",
        status="failed",
        exit_code=1,
        duration_s=0.8,
        output_lines=3,
        output_preview="",
        full_output="",
    )
    lines = render_tool(item, color=False)
    assert lines[0].startswith("× Command")


def test_activity_render_suppressed_when_done():
    lines = render_activity(
        SimpleNamespace(kind="activity", text="思考中…", running=True, done=False),
        color=False,
    )
    assert lines == ["● 思考中…"]
    lines = render_activity(
        SimpleNamespace(kind="activity", text="思考中…", running=True, done=True),
        color=False,
    )
    assert lines == []


def test_store_shares_timeline_with_reducer():
    reducer = EventReducer(mode="run", target="sandbox")
    store = ItemStore(color=False)
    store.items = reducer.items
    reducer.system_notice("Type /help for commands")
    lines = store.render_lines(80)
    assert any("Type /help" in line for line in lines)


def test_status_phase_label_mapping():
    runner = SimpleNamespace(run_state=RunState(phase="generating"))
    status = StatusLineState(run_status="generating")
    assert runner.run_state.phase == "generating"
    assert status.run_status == "generating"
