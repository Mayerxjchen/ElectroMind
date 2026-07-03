"""Sandbox 权限策略 —— 所有边界校验集中在这里。

三层区域：
- workspace（workdir）：文件工具 + run_command 的主要活动范围
- host（host_root）：list_host_files / copy_* 专用，只读或受控写入
- system：run_command 在 workdir 策略下仍可访问的常见系统路径（/usr、/bin 等），
  供 python/git/uv 等工具链使用；不能替代内核级隔离

run_command 的静态扫描是启发式的，拦 obvious escape（../、家目录其它路径），
拦不住 `python -c "open('/secret')"` 这类动态路径 —— 要硬隔离得靠 OS/容器。
"""

from __future__ import annotations

import os
import re

# shell 命令里冒出来的绝对路径（启发式，不保证完整）
ABS_PATH = re.compile(r"(?<![A-Za-z0-9_./~-])(/(?:[\w.@+-]+(?:/[\w.@+-]+)*)?/?)")
# .. 作为路径分量：cd ..、../x、..&& 等（原先只匹配 ../ 或行尾，漏了 cd .. &&）
DOTDOT = re.compile(r"(?<![\w.])\.\.(?![\w.])")
CD_TARGET = re.compile(
    r"\b(?:cd|pushd)\s+(\"([^\"\\]|\\.)*\"|'([^'\\]|\\.)*'|(\S+))",
    re.IGNORECASE,
)

# agent 跑工具链时通常需要读的系统目录（不含 /tmp/：workdir 常落在 /tmp 下，
# 整段放行会漏掉 workspace 外的 /tmp/... 路径）
SYSTEM_PREFIXES = (
    "/usr/",
    "/bin/",
    "/sbin/",
    "/lib/",
    "/lib64/",
    "/opt/",
    "/etc/",
    "/var/run/",
    "/var/tmp/",
    "/dev/",
    "/proc/",
    "/sys/",
)

SYSTEM_EXACT = frozenset(
    {
        "/usr",
        "/bin",
        "/sbin",
        "/lib",
        "/lib64",
        "/opt",
        "/etc",
        "/dev/null",
        "/dev/stdin",
        "/dev/stdout",
        "/dev/stderr",
    }
)

COMMAND_POLICIES = frozenset({"open", "workdir"})


def validate_command_policy(policy: str) -> str:
    if policy not in COMMAND_POLICIES:
        raise ValueError(
            f"unknown command_policy: {policy!r}; expected one of {sorted(COMMAND_POLICIES)}"
        )
    return policy


def under_root(path: str, root: str) -> bool:
    root_norm = os.path.normpath(root)
    path_norm = os.path.normpath(path)
    return path_norm == root_norm or path_norm.startswith(root_norm + os.sep)


def is_system_path(path: str) -> bool:
    path_norm = os.path.normpath(path)
    if path_norm in SYSTEM_EXACT:
        return True
    return any(path_norm.startswith(prefix) for prefix in SYSTEM_PREFIXES)


def cd_target_from_match(match: re.Match[str]) -> str:
    return match.group(2) or match.group(3) or match.group(4) or ""


def is_url_slash(command: str, start: int) -> bool:
    return start > 0 and command[start - 1] == ":" and command.startswith("//", start)


def check_cd_targets(command: str, *, workdir: str) -> None:
    workdir_norm = os.path.normpath(workdir)
    for match in CD_TARGET.finditer(command):
        raw = cd_target_from_match(match).strip()
        if raw in ("", ".", "./"):
            continue
        if raw == "-":
            raise PermissionError(
                "cd - is not allowed in workdir mode (may leave workspace)"
            )
        if raw.startswith("~"):
            raise PermissionError(
                "cd ~ is not allowed in workdir mode (may leave workspace)"
            )
        if any(token in raw for token in ("$", "`", "$(")):
            raise PermissionError(
                "cd with shell expansion is not allowed in workdir mode"
            )
        if raw.startswith("/"):
            resolved = os.path.normpath(raw)
        else:
            resolved = os.path.normpath(os.path.join(workdir_norm, raw))
        if under_root(resolved, workdir_norm):
            continue
        if is_system_path(resolved):
            continue
        raise PermissionError(
            f"cd target escapes workspace: {raw!r} -> {resolved!r} "
            f"(workspace is {workdir_norm!r})"
        )


def check_command(command: str, *, workdir: str, policy: str) -> None:
    """run_command 执行前的静态检查。越界抛 PermissionError。"""
    validate_command_policy(policy)
    if policy == "open":
        return

    if DOTDOT.search(command):
        raise PermissionError(
            "command references parent directory (..); "
            "only paths inside the workspace are allowed"
        )

    check_cd_targets(command, workdir=workdir)

    workdir_norm = os.path.normpath(workdir)
    for match in ABS_PATH.finditer(command):
        if is_url_slash(command, match.start()):
            continue
        path = os.path.normpath(match.group())
        if under_root(path, workdir_norm):
            continue
        if is_system_path(path):
            continue
        raise PermissionError(
            f"command references path outside workspace: {path!r} "
            f"(workspace is {workdir_norm!r})"
        )


def check_backend_path(path: str, *, workdir: str) -> None:
    """backend 文件 API 的第二道防线（SFTP 等绕过虚拟路径时兜底）。"""
    if not under_root(path, workdir):
        raise PermissionError(
            f"backend path escapes workspace: {path!r} "
            f"(workspace is {os.path.normpath(workdir)!r})"
        )
