"""Coverage：app/tool_permit.py 纯函数（危险工具审批判定）。

覆盖 needs_tool_permit / risk_hint / _has_unquoted_metachar / _command_safe /
requires_permit_prompt / summarize_tool_args，补足 A+ v1.0 真实覆盖率。
"""

from __future__ import annotations

from app.tool_permit import (
    _command_safe,
    _has_unquoted_metachar,
    is_safe_tool_call,
    needs_tool_permit,
    requires_permit_prompt,
    risk_hint,
    summarize_tool_args,
)


class _Event:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class TestNeedsPermit:
    def test_permit_tools(self):
        assert needs_tool_permit("run_command") is True
        assert needs_tool_permit("copy_from_host") is True

    def test_other_tools_not_permitted(self):
        assert needs_tool_permit("list_dir") is False
        assert needs_tool_permit("read_file") is False


class TestRiskHint:
    def test_rm(self):
        assert risk_hint("rm -rf x") == "deletes files"
        assert risk_hint("rm file") == "deletes files"

    def test_sudo(self):
        assert risk_hint("sudo apt install x") == "elevated privileges"

    def test_write(self):
        assert risk_hint("echo x > f") == "writes files"
        assert risk_hint("tee out.txt") == "writes files"

    def test_default(self):
        assert risk_hint("ls -la") == "executes command"


class TestMetachar:
    def test_no_metachar(self):
        assert _has_unquoted_metachar("ls -la /tmp") is False

    def test_pipe(self):
        assert _has_unquoted_metachar("a | b") is True

    def test_redirect(self):
        assert _has_unquoted_metachar("a > f") is True
        assert _has_unquoted_metachar("a < f") is True

    def test_semicolon_and_backtick(self):
        assert _has_unquoted_metachar("a; b") is True
        assert _has_unquoted_metachar("`ls`") is True

    def test_quoted_metachar_safe(self):
        # 引号内的元字符不算（find -name "*.py"）
        assert _has_unquoted_metachar('find . -name "*.py"') is False

    def test_single_quote_safe(self):
        assert _has_unquoted_metachar("echo 'a|b'") is False

    def test_brace_expansion(self):
        assert _has_unquoted_metachar("echo {a,b}") is True


class TestCommandSafe:
    def test_safe_cat(self):
        assert _command_safe("run_command", '{"command": "cat file.txt"}') is True

    def test_not_run_command(self):
        assert _command_safe("copy_from_host", "{}") is False

    def test_bad_json(self):
        assert _command_safe("run_command", "{oops") is False

    def test_not_dict_payload(self):
        assert _command_safe("run_command", '"just-string"') is False

    def test_empty_command(self):
        assert _command_safe("run_command", '{"command": "  "}') is False

    def test_metachar_rejected(self):
        assert _command_safe("run_command", '{"command": "cat a | grep x"}') is False

    def test_non_whitelist_command(self):
        assert _command_safe("run_command", '{"command": "python script.py"}') is False

    def test_find_delete_rejected(self):
        assert _command_safe("run_command", '{"command": "find . -delete"}') is False

    def test_sort_o_rejected(self):
        assert (
            _command_safe("run_command", '{"command": "sort -o out.txt in.txt"}')
            is False
        )

    def test_xxd_r_rejected(self):
        assert (
            _command_safe("run_command", '{"command": "xxd -r in.bin out.bin"}')
            is False
        )

    def test_safe_ls(self):
        assert _command_safe("run_command", '{"command": "ls /tmp"}') is True

    def test_shlex_bad_command(self):
        assert _command_safe("run_command", '{"command": "echo \'unclosed"}') is False


class TestRequiresPermit:
    def test_auto_mode_never_prompts(self):
        assert requires_permit_prompt("auto", _Event("run_command", "{}")) is False

    def test_non_permit_tool_no_prompt(self):
        assert requires_permit_prompt("prompt", _Event("list_dir", "{}")) is False

    def test_auto_safe_safe_command_no_prompt(self):
        assert (
            requires_permit_prompt(
                "auto-safe", _Event("run_command", '{"command": "ls"}')
            )
            is False
        )

    def test_auto_safe_unsafe_prompts(self):
        assert (
            requires_permit_prompt(
                "auto-safe", _Event("run_command", '{"command": "rm x"}')
            )
            is True
        )

    def test_prompt_mode_prompts(self):
        assert (
            requires_permit_prompt("prompt", _Event("run_command", '{"command": "ls"}'))
            is True
        )


class TestSummarize:
    def test_bad_json_returns_raw(self):
        assert summarize_tool_args("run_command", "{oops") == "{oops"

    def test_run_command_extracts(self):
        assert summarize_tool_args("run_command", '{"command": "ls -la"}') == "ls -la"

    def test_copy_from_host(self):
        assert (
            summarize_tool_args(
                "copy_from_host", '{"host_path": "/a/b", "dest": "./out"}'
            )
            == "/a/b → ./out"
        )

    def test_unknown_tool_returns_arguments(self):
        assert summarize_tool_args("other", '{"x": 1}') == '{"x": 1}'


class TestIsSafeToolCall:
    def test_safe_event(self):
        assert is_safe_tool_call(_Event("run_command", '{"command": "cat x"}')) is True

    def test_unsafe_event(self):
        assert (
            is_safe_tool_call(_Event("run_command", '{"command": "python x"}')) is False
        )
