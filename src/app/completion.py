"""Shell 补全脚本生成：bash / zsh / fish。

从顶层 parser 动态提取子命令与 flag 清单，避免两处维护漂移。
"""

from __future__ import annotations

import argparse

from .cli_parser import SUBCOMMANDS, build_parser

# 带参数的 flag（补全时提示 <value>）
_VALUE_FLAGS = (
    "--mode",
    "--target",
    "--permission-mode",
    "--project",
    "--add-dir",
    "--model",
    "--max-iterations",
    "--max-turns",
    "--input-format",
    "--output-format",
    "--allowed-tools",
    "--disallowed-tools",
    "--log-file",
    "--config",
    "--thread-id",
    "--host",
    "--port",
    "--execution-mode",
    "--backend",
    "--dev",
    "--ssh-host",
    "--ssh-config",
)


def _flag_list() -> list[str]:
    parser = build_parser()
    flags: list[str] = []
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        for option in getattr(action, "option_strings", ()):
            flags.append(option)
    return flags


def _subcommand_flags() -> str:
    return " ".join(sorted(SUBCOMMANDS))


def _main_flags() -> str:
    return " ".join(sorted(_flag_list()))


def completion_script(shell: str) -> str:
    if shell == "bash":
        return _bash_script()
    if shell == "zsh":
        return _zsh_script()
    if shell == "fish":
        return _fish_script()
    raise ValueError(f"unsupported shell: {shell}")


def _bash_script() -> str:
    commands = _subcommand_flags()
    flags = _main_flags()
    value_flags = " ".join(_VALUE_FLAGS)
    return f"""# electromind bash completion
_electromind_completions() {{
    local cur prev
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"

    # 子命令后的位置参数补全
    case "${{COMP_WORDS[1]}}" in
        session|config|skills) COMPREPLY=( $(compgen -W "{commands}" -- "$cur") ); return ;;
    esac

    # flag 值补全
    case "$prev" in
        {value_flags.replace(" ", "|")})
            COMPREPLY=( $(compgen -W "" -- "$cur") ); return ;;
        --mode) COMPREPLY=( $(compgen -W "ask plan run" -- "$cur") ); return ;;
        --target|--execution-mode) COMPREPLY=( $(compgen -W "sandbox local ssh" -- "$cur") ); return ;;
        --permission-mode) COMPREPLY=( $(compgen -W "prompt auto-safe auto" -- "$cur") ); return ;;
        --input-format) COMPREPLY=( $(compgen -W "text stream-json" -- "$cur") ); return ;;
        --output-format) COMPREPLY=( $(compgen -W "text json stream-json" -- "$cur") ); return ;;
        --backend) COMPREPLY=( $(compgen -W "local container docker podman ssh" -- "$cur") ); return ;;
        --dev) COMPREPLY=( $(compgen -d -- "$cur") ); return ;;
    esac

    COMPREPLY=( $(compgen -W "{flags} {commands}" -- "$cur") )
    return 0
}}
complete -F _electromind_completions electromind
"""


def _zsh_script() -> str:
    commands = _subcommand_flags()
    flags = _main_flags()
    arguments = flags.replace(" ", " \\\n        ")
    return f"""#compdef electromind
# electromind zsh completion
_electromind() {{
    local -a commands
    commands=({commands})
    if (( CURRENT == 2 )); then
        _describe 'command' commands
        return
    fi
    _arguments -s {arguments}
}}
compdef _electromind electromind
"""


def _fish_script() -> str:
    lines = ["# electromind fish completion", "complete -c electromind -f"]
    for flag in _flag_list():
        if flag in ("-c", "-r", "-p"):
            continue  # 顶层短 flag 由下面明确补
        lines.append(
            f"complete -c electromind -l {flag[2:]}"
            if flag.startswith("--")
            else f"complete -c electromind -s {flag[1:]}"
        )
    for command in SUBCOMMANDS:
        lines.append(f"complete -c electromind -n '__fish_use_subcommand' -a {command}")
    return "\n".join(lines) + "\n"
