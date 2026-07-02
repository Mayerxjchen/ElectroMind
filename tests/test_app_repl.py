import pytest

from app.repl import format_fatal_error, handle_command, say_goodbye


class FakeRunner:
    sandbox = None


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
