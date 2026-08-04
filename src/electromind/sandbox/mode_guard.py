"""Session mode enforcement — tool-level gating for Ask / Plan / Agent.

``SessionMode`` is the **only** source of truth for what an agent run
is allowed to do.  It is NOT derived from the system prompt — it is
enforced at the tool / sandbox layer, so a prompt injection cannot
escalate an Ask session into an Agent.

Rules:

=========== ======== ======== ========
Capability  Ask      Plan     Agent
=========== ======== ======== ========
Read files  ✓        ✓        ✓
List dirs   ✓        ✓        ✓
Search      ✓        ✓        ✓
Shell/cmds  ✗        ✗        ✓
Write files ✗        ✗        ✓
Delete      ✗        ✗        ✓
Submit jobs ✗        ✗        ✓
=========== ======== ======== ========

Plan mode blocks ALL command execution: the ``run_command`` tool accepts
only a string parameter (``sh -c``), which provides no reliable boundary
against writes, so ``check_command_exec`` rejects every string command.
Even if a argv-list command is provided, only strictly read-only commands
(``cat``, ``head``, ``ls``, ``grep``, …) would be permitted — but the
current tool protocol never produces argv lists, so this path is
presently unreachable.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class SessionMode(enum.StrEnum):
    ASK = "ask"
    PLAN = "plan"
    AGENT = "agent"
    REVIEW = "review"


class Autonomy(enum.StrEnum):
    PROMPT = "prompt"
    AUTO_SAFE = "auto-safe"
    FULL_ACCESS = "full-access"


# ── Plan-mode safe commands (read-only, no side effects) ──────────────

# ── Plan-mode safe commands (strictly read-only, no write or subprocess
# capability in ANY documented syntax) ───────────────────────────────────
#
# Commands with file-write or process-spawn capability are REMOVED
# entirely (blacklisting their flags is not sound):
#   python/python3 (-c, script args), env (launches interpreters),
#   awk (system()), sed (-i, `w` command), find (-delete/-exec/-fprint*),
#   sort (-o), echo/tee (redirection), uniq/tr (streaming transforms are
#   harmless, but kept out for minimalism).  File observation belongs to
#   the typed tools (read_file / list_dir / list_host_files).

_PLAN_SAFE_COMMANDS: frozenset[str] = frozenset(
    {
        "cat",
        "head",
        "tail",
        "less",
        "ls",
        "grep",
        "egrep",
        "fgrep",
        "which",
        "whereis",
        "uname",
        "hostname",
        "whoami",
        "id",
        "pwd",
        "date",
        "wc",
        "cut",
        "diff",
        "cmp",
        "file",
        "stat",
        "df",
        "du",
        "free",
        "uptime",
        "ps",
        "lscpu",
        "nproc",
        "true",
        "false",
        "test",
        "[",
        "printf",
        "md5sum",
        "sha1sum",
        "sha256sum",
        "realpath",
        "readlink",
        "basename",
        "dirname",
    }
)


# Shell metacharacters that can chain writes / redirect output — never
# allowed in Plan mode even inside argv.
_PLAN_FORBIDDEN_METACHARS = frozenset({">", ">>", "|", ";", "&", "$", "`", "<"})


def is_plan_safe_command(argv: list[str]) -> bool:
    """Return True if *argv* is a known read-only command for Plan mode.

    The allowlist itself is the enforcement: every listed command lacks
    write / subprocess capability in ANY documented syntax (write-capable
    commands were REMOVED, not flag-blocklisted).  Shell metacharacters
    (redirection / pipes / command chains) are forbidden regardless.
    """
    if not argv:
        return False
    base = argv[0].split("/")[-1]  # strip path prefix
    if base not in _PLAN_SAFE_COMMANDS:
        return False
    for token in argv[1:]:
        if any(ch in token for ch in _PLAN_FORBIDDEN_METACHARS):
            return False
    return True


# ── Mode guard result ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ModeCheck:
    allowed: bool
    reason: str = ""


def check_file_write(mode: SessionMode) -> ModeCheck:
    if mode == SessionMode.ASK:
        return ModeCheck(False, "Ask 模式不允许修改文件。请切换到 Agent 模式。")
    if mode == SessionMode.PLAN:
        return ModeCheck(
            False, "Plan 模式不允许修改文件。批准计划后切换到 Agent 执行。"
        )
    if mode == SessionMode.REVIEW:
        return ModeCheck(False, "Review 模式不允许修改文件。")
    return ModeCheck(True)


def check_file_delete(mode: SessionMode) -> ModeCheck:
    if mode == SessionMode.ASK:
        return ModeCheck(False, "Ask 模式不允许删除文件。请切换到 Agent 模式。")
    if mode == SessionMode.PLAN:
        return ModeCheck(False, "Plan 模式不允许删除文件。")
    if mode == SessionMode.REVIEW:
        return ModeCheck(False, "Review 模式不允许删除文件。")
    return ModeCheck(True)


def check_command_exec(mode: SessionMode, command: list[str] | str) -> ModeCheck:
    if mode == SessionMode.ASK:
        return ModeCheck(False, "Ask 模式不允许执行命令。请切换到 Agent 模式。")
    if mode == SessionMode.REVIEW:
        return ModeCheck(False, "Review 模式不允许执行命令。")
    if mode == SessionMode.PLAN:
        if isinstance(command, str):
            # String commands execute via `sh -c`: the first word is NOT
            # a reliable boundary (`echo owned > file`, `sed -i ...`,
            # `python -c "...write..."` all start with an allowed word).
            # Plan mode therefore rejects string shell entirely.
            return ModeCheck(
                False,
                "Plan 模式不允许字符串命令（经 sh -c 执行，可绕过只读限制）。"
                "请以 argv 形式调用，且首命令在只读清单内。",
            )
        argv = list(command)
        if not is_plan_safe_command(argv):
            return ModeCheck(
                False,
                f"Plan 模式只允许只读命令。'{argv[0] if argv else '?'}' 不在允许列表中。",
            )
    return ModeCheck(True)
