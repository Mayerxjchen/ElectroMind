import pytest

from app.tool_permit import (
    PERMIT_TOOLS,
    USER_DENIED_TOOL_MESSAGE,
    build_app_tool_hooks,
    format_permit_prompt,
    needs_tool_permit,
    parse_permit_answer,
    summarize_tool_args,
)
from electromind import ToolCallBegin


def test_permit_tools():
    assert needs_tool_permit("run_command")
    assert needs_tool_permit("copy_from_host")
    assert not needs_tool_permit("read_file")
    assert PERMIT_TOOLS == frozenset({"run_command", "copy_from_host"})


def test_summarize_tool_args():
    assert summarize_tool_args("run_command", '{"command": "ls -la"}') == "ls -la"
    assert (
        summarize_tool_args(
            "copy_from_host",
            '{"host_path": "/tmp/a", "dest": "work/"}',
        )
        == "/tmp/a → work/"
    )


def test_format_permit_prompt():
    event = ToolCallBegin("id", "run_command", '{"command": "rm -rf /"}')
    assert "run_command" in format_permit_prompt(event)
    assert "rm -rf /" in format_permit_prompt(event)


def test_build_app_tool_hooks_auto_returns_none():
    assert build_app_tool_hooks(auto=True) is None
    assert build_app_tool_hooks(auto=False) is not None


def test_user_denied_message_is_explicit():
    assert "用户" in USER_DENIED_TOOL_MESSAGE
    assert "拒绝" in USER_DENIED_TOOL_MESSAGE


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("y", True),
        ("yes", True),
        ("是", True),
        ("n", False),
        ("no", False),
        ("拒绝", False),
        ("maybe", None),
    ],
)
def test_parse_permit_answer(text, expected):
    assert parse_permit_answer(text) is expected
