from types import SimpleNamespace

from app.layout_terminal import LayoutTerminal
from app.render import format_status_label, sync_run_state_ui
from pagentv4 import RunState, ToolCallBegin


def test_format_status_label_uses_runner_phase():
    runner = SimpleNamespace(run_state=RunState(phase="generating"))
    assert format_status_label(runner, {}) == "正在生成"


def test_format_status_label_prefers_permit():
    runner = SimpleNamespace(run_state=RunState(phase="calling"))
    run_state = {"permit": ToolCallBegin("c1", "run_command", '{"command":"rm -rf /"}')}
    assert format_status_label(runner, run_state) == "等待工具审批"


def test_sync_run_state_ui_writes_status():
    runner = SimpleNamespace(run_state=RunState(phase="initializing"))
    run_state: dict = {}
    sync_run_state_ui(runner, run_state)
    assert run_state["status"] == "正在初始化"


def test_sync_run_state_ui_keeps_status_during_running():
    runner = SimpleNamespace(run_state=RunState(phase="running"))
    run_state = {"status": "正在生成", "active": True}
    sync_run_state_ui(runner, run_state)
    assert run_state["status"] == "正在生成"


def test_format_status_label_idle_after_run_end():
    runner = SimpleNamespace(run_state=RunState(phase="ended"))
    assert format_status_label(runner, {"active": False}) == "空闲"


def test_layout_terminal_status_fragments():
    terminal = LayoutTerminal(color=False)
    text = terminal.status_fragments({"status": "正在生成"})
    assert text == " 正在生成 "
