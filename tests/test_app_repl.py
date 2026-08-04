import pytest

from app import render
from app.render import (
    RenderState,
    emit_user_line,
    format_tool_call,
    format_tool_result,
    render_event,
    render_turn,
)
from app.repl import (
    format_fatal_error,
    handle_command,
    handle_prefixed_command,
    read_prompt_line,
    say_goodbye,
    split_prefixed_command,
)
from electromind import TextDelta, ToolCallBegin, ToolResult, TurnEnd


class FakeRunner:
    sandbox = None


class FakeSandboxCommands:
    def __init__(self):
        self.calls = []

    async def run(self, command):
        self.calls.append(command)
        return type(
            "Result",
            (),
            {
                "stdout": "sandbox output\n",
                "stderr": "",
                "exit_code": 0,
            },
        )()


class FakeBackend:
    pass


class FakeSandbox:
    def __init__(self):
        self.commands = FakeSandboxCommands()
        self.backend = FakeBackend()


class FakeCommandRunner:
    def __init__(self):
        self.sandbox = FakeSandbox()


@pytest.mark.asyncio
async def test_handle_command_quit():
    assert await handle_command("/quit", FakeRunner(), color=False) is True
    assert await handle_command("/exit", FakeRunner(), color=False) is True


def test_format_fatal_error_ssh():
    class SFTPFailure(Exception):
        pass

    text = format_fatal_error(SFTPFailure("Failure"), phase="start")
    assert "SSH 沙箱" in text
    assert "workdir" in text


def test_format_fatal_error_close_phase():
    text = format_fatal_error(RuntimeError("gone"), phase="close")
    assert "关闭失败" in text


def test_say_goodbye(capsys):
    say_goodbye(color=False)
    assert "bye" in capsys.readouterr().out


def test_split_prefixed_command():
    # 隐式语义已删除：! 与 !! 都在当前 Execution Target 执行
    assert split_prefixed_command("!pwd") == ("target", "pwd")
    assert split_prefixed_command("!! pwd") == ("target", "pwd")
    assert split_prefixed_command("hello") is None


def test_read_prompt_line_uses_prompt_toolkit(monkeypatch):
    captured: dict[str, object] = {}

    class FakeSession:
        def prompt(self, message, **kwargs):
            captured["message"] = message
            return "你好"

    monkeypatch.setattr("app.terminal.prompt_session", lambda: FakeSession())

    assert read_prompt_line(color=True) == "你好"
    assert captured["message"] is not None


def test_read_prompt_line_plain_prompt_when_no_color(monkeypatch):
    captured: dict[str, object] = {}

    class FakeSession:
        def prompt(self, message, **kwargs):
            captured["message"] = message
            return "ok"

    monkeypatch.setattr("app.terminal.prompt_session", lambda: FakeSession())

    assert read_prompt_line(color=False) == "ok"
    assert captured["message"] == "you> "


def test_format_tool_call_elides_long_arguments():
    line = format_tool_call(
        "write_file",
        '{"path":"test_net.py","content":"import urllib.request\\nprint(1)"}',
    )
    assert line.startswith("tool → write_file(")
    assert "path='test_net.py'" in line
    assert "content='import urllib.request print(1)'" in line
    assert "\n" not in line


def test_format_tool_result_single_line():
    line = format_tool_result("ok:\nline1\nline2", ok=True)
    assert line == "ok: ok: line1 line2"


def test_format_tool_result_elides_visual_lines(monkeypatch):
    monkeypatch.setattr(render, "terminal_width", lambda: 20)
    line = format_tool_result("1234567890abcdefghij\nline2\nline3\nline4", ok=True)
    assert line.startswith("ok: ")
    assert "line3" in line
    assert "…(+1 lines)" in line


class FakeStreamRunner:
    def __init__(self, events):
        self.events = events

    async def run(self, user_input):
        del user_input
        for event in self.events:
            yield event


@pytest.mark.asyncio
async def test_render_turn_separates_tool_block_from_text(capsys):
    runner = FakeStreamRunner(
        [
            TextDelta("先试一下。"),
            ToolCallBegin(
                "call-1",
                "run_command",
                '{"command":"curl -s -o /dev/null https://www.baidu.com"}',
            ),
            ToolResult(
                "call-1", "run_command", '{"ok": true, "exit_code": 0}', ok=True
            ),
            TextDelta("上到网。"),
        ]
    )

    await render_turn(runner, "test", color=False)

    out = capsys.readouterr().out
    assert "electromind> 先试一下。\ntool → run_command(" in out
    assert "curl -s -o /dev/null https://www.baidu.com" in out
    assert '\n  ok: {"ok": true, "exit_code": 0}\n\nelectromind> 上到网。\n' in out


@pytest.mark.asyncio
async def test_render_turn_collects_tool_blocks(capsys):
    runner = FakeStreamRunner(
        [
            ToolCallBegin("call-1", "run_command", '{"command":"pwd"}'),
            ToolResult("call-1", "run_command", '{"ok": true}', ok=True),
        ]
    )
    state = RenderState(color=False)

    returned = await render_turn(runner, "test", color=False, state=state)

    assert returned is state
    assert len(state.tool_blocks) == 1
    block = state.tool_blocks[0]
    assert block.tool_call_id == "call-1"
    assert block.name == "run_command"
    assert block.call_preview == "tool → run_command(command='pwd')"
    assert block.result_preview == 'ok: {"ok": true}'
    assert block.ok is True
    assert "tool → run_command(command='pwd')" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_render_turn_merges_text_deltas(capsys):
    runner = FakeStreamRunner([TextDelta("A"), TextDelta("B"), TextDelta("C")])

    await render_turn(runner, "test", color=False)

    assert capsys.readouterr().out == "electromind> ABC\n"


@pytest.mark.asyncio
async def test_render_turn_merges_reasoning_deltas(capsys):
    runner = FakeStreamRunner(
        [render.ReasoningDelta("想"), render.ReasoningDelta("一下"), TextDelta("答复")]
    )

    await render_turn(runner, "test", color=False)

    assert capsys.readouterr().out == "reasoning: 想一下\nelectromind> 答复\n"


def test_emit_user_line(capsys):
    emit_user_line("你好", color=False)
    assert capsys.readouterr().out == "you> 你好\n"


@pytest.mark.asyncio
async def test_render_event_cancelled(capsys):
    state = RenderState(color=False)
    render_event(TurnEnd(1, stopped=True, stop_reason="cancelled"), state)
    assert capsys.readouterr().out == "[cancelled]\n"


@pytest.mark.asyncio
async def test_cli_app_send_turn_during_run():
    """运行中输入经客户端 immediate 投递（不再直接调 runner.steer）。"""
    import asyncio

    from app.tui.application import CliApp

    class FakeClient:
        def __init__(self):
            self.sent: list[tuple[str, str, str]] = []

        async def send_input(
            self, thread_id, text, *, delivery="auto", request_id=None, mode=None
        ):
            self.sent.append((thread_id, text, delivery))

    client = FakeClient()
    app = CliApp(color=False, thread_id="thread-t1")
    app.client = client  # type: ignore[assignment]

    app.send_turn("follow up", delivery="immediate")
    await asyncio.sleep(0.01)

    assert client.sent == [("thread-t1", "follow up", "immediate")]


@pytest.mark.asyncio
async def test_handle_prefixed_command_runs_on_current_target(capsys):
    """! 命令经 runner.sandbox.commands.run（权限生命周期），不再直接开子进程。"""
    runner = FakeCommandRunner()

    handled = await handle_prefixed_command("!pwd", runner, color=False)
    out = capsys.readouterr().out

    assert handled is True
    assert runner.sandbox.commands.calls == ["pwd"]
    assert "sandbox output" in out


@pytest.mark.asyncio
async def test_handle_prefixed_command_double_bang_is_alias(capsys):
    runner = FakeCommandRunner()

    handled = await handle_prefixed_command("!!pwd", runner, color=False)

    assert handled is True
    assert runner.sandbox.commands.calls == ["pwd"]
