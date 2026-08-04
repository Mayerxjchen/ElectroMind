"""Plan-mode shell bypass regression tests (P0).

String commands execute via `sh -c` — the first word is not a reliable
boundary.  `echo owned > file`, `sed -i`, and `python -c "...write..."`
must ALL be rejected in Plan mode; only argv-list commands with a
known read-only first command are allowed.
"""

from __future__ import annotations

from electromind.sandbox.mode_guard import (
    SessionMode,
    check_command_exec,
)


def test_plan_rejects_string_echo_redirect():
    """echo owned > file must be rejected (shell redirect bypass)."""
    check = check_command_exec(SessionMode.PLAN, "echo owned > pwned.txt")
    assert not check.allowed


def test_plan_rejects_string_python_write():
    """python -c 'open(...).write(...)' must be rejected."""
    check = check_command_exec(
        SessionMode.PLAN,
        "python -c \"open('pwned.txt','w').write('owned')\"",
    )
    assert not check.allowed


def test_plan_rejects_string_sed_inplace():
    """sed -i (in-place edit) must be rejected."""
    check = check_command_exec(SessionMode.PLAN, "sed -i 's/a/b/' f.txt")
    assert not check.allowed


def test_plan_rejects_string_cat_redirect():
    """Even a 'safe' first word with a redirect must be rejected."""
    check = check_command_exec(SessionMode.PLAN, "cat f > g")
    assert not check.allowed


def test_plan_allows_argv_read_only():
    """argv-list cat remains allowed (no shell interpretation)."""
    check = check_command_exec(SessionMode.PLAN, ["cat", "f.txt"])
    assert check.allowed


def test_plan_rejects_argv_python_c_write():
    """python -c with a write is forbidden by argument-level checks."""
    check = check_command_exec(
        SessionMode.PLAN, ["python", "-c", "open('p','w').write('x')"]
    )
    assert not check.allowed


def test_plan_rejects_argv_sed_inplace():
    check = check_command_exec(SessionMode.PLAN, ["sed", "-i", "s/a/b/", "f"])
    assert not check.allowed


def test_plan_rejects_argv_sed_long_inplace():
    check = check_command_exec(SessionMode.PLAN, ["sed", "--in-place", "s/a/b/", "f"])
    assert not check.allowed


def test_plan_rejects_argv_find_delete():
    check = check_command_exec(SessionMode.PLAN, ["find", ".", "-delete"])
    assert not check.allowed


def test_plan_rejects_argv_find_exec():
    check = check_command_exec(
        SessionMode.PLAN, ["find", ".", "-exec", "rm", "{}", ";"]
    )
    assert not check.allowed


def test_plan_rejects_argv_redirect_metachar():
    """Even argv-form cat with a > token is rejected (shell metachar)."""
    check = check_command_exec(SessionMode.PLAN, ["cat", "f", ">", "g"])
    assert not check.allowed


def test_plan_rejects_sed_entirely():
    """sed is removed from the allowlist — even read-only use is denied."""
    check = check_command_exec(SessionMode.PLAN, ["sed", "s/a/b/", "f"])
    assert not check.allowed


def test_plan_rejects_find_entirely():
    """find is removed — even read-only use is denied."""
    check = check_command_exec(SessionMode.PLAN, ["find", ".", "-name", "*.log"])
    assert not check.allowed


def test_plan_rejects_python_script_file():
    """python script.py (no -c) is denied — scripts can write."""
    check = check_command_exec(SessionMode.PLAN, ["python", "script.py"])
    assert not check.allowed


def test_plan_rejects_sort_output():
    """sort -o writes a file — sort is removed entirely."""
    check = check_command_exec(SessionMode.PLAN, ["sort", "-o", "out.txt", "in.txt"])
    assert not check.allowed


def test_plan_rejects_env_interpreter():
    """env python -c spawns an interpreter — env is removed."""
    check = check_command_exec(SessionMode.PLAN, ["env", "python", "-c", "print(1)"])
    assert not check.allowed


def test_plan_rejects_awk_system():
    """awk system() spawns — awk is removed."""
    check = check_command_exec(
        SessionMode.PLAN, ["awk", 'BEGIN{system("touch pwned")}']
    )
    assert not check.allowed


def test_plan_rejects_echo():
    """echo is removed (redirection risk)."""
    check = check_command_exec(SessionMode.PLAN, ["echo", "hi"])
    assert not check.allowed


def test_plan_rejects_stream_transforms():
    """uniq/tr removed for minimalism."""
    assert not check_command_exec(SessionMode.PLAN, ["uniq", "f"]).allowed
    assert not check_command_exec(SessionMode.PLAN, ["tr", "a", "b"]).allowed


def test_plan_rejects_argv_unknown_command():
    check = check_command_exec(SessionMode.PLAN, ["rm", "-rf", "/"])
    assert not check.allowed


def test_ask_rejects_all_commands():
    check = check_command_exec(SessionMode.ASK, ["ls"])
    assert not check.allowed
    check2 = check_command_exec(SessionMode.ASK, "ls")
    assert not check2.allowed
