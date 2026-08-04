"""Shell 补全脚本生成（bash/zsh/fish）——从 parser 动态提取，无两处维护。"""

from __future__ import annotations

import pytest

from app.cli_parser import SUBCOMMANDS
from app.completion import _flag_list, completion_script


def test_flag_list_from_parser():
    flags = _flag_list()
    assert "--mode" in flags
    assert "--target" in flags
    assert "--output-format" in flags
    assert "-p" in flags
    assert "-r" in flags


def test_bash_script_contains_commands_and_flags():
    script = completion_script("bash")
    for command in SUBCOMMANDS:
        assert command in script
    assert "--mode" in script
    assert "complete -F _electromind_completions electromind" in script


def test_zsh_script_compdef():
    script = completion_script("zsh")
    assert script.startswith("#compdef electromind")
    assert "compdef _electromind electromind" in script
    assert "session" in script


def test_fish_script_complete_lines():
    script = completion_script("fish")
    for command in SUBCOMMANDS:
        assert (
            f"complete -c electromind -n '__fish_use_subcommand' -a {command}" in script
        )
    assert "complete -c electromind -l mode" in script


def test_unsupported_shell_raises():
    with pytest.raises(ValueError):
        completion_script("csh")


def test_scripts_are_syntactically_generatable_for_all_shells():
    for shell in ("bash", "zsh", "fish"):
        script = completion_script(shell)
        assert script.strip()  # 非空且可生成
