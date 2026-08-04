"""SshBackend —— 远端 ssh backend；复用同一条 asyncssh 连接跑 exec + SFTP。

设计要点：
- 依赖 `asyncssh`；作为 optional extra `electromind[ssh]` 提供
- 一次 `start()` 建立一条长连接；`close()` 关掉；所有 exec / files 走同一个 conn
- 远端 workdir：`connection["workdir"]` 显式指定，或回退到 `~/.electromind`（会 mkdir -p）
- 连接带 `connect_timeout`（默认 10s）+ `login_timeout`（默认 15s），连不上尽快失败
- alive 走 `conn.is_closed()` + 一次极短 `true` 命令兜底，判断是否可用
- Guard 层会在自愈时重跑 start()，此时会重建连接 + 重新 mkdir workdir

connection 支持字段（也可以用 SshConnection 类构造再 .to_dict()）：
    host        必填
    port        int，默认 22
    user        必填
    password    可选（若没配 key）
    client_keys 可选，list[str]，本地私钥路径
    known_hosts str | None，默认 None（跳过 host key 校验）
    workdir     远端工作目录；缺省 "~/.electromind"（agent 只操作此目录）
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import asyncssh

from ..base import (
    BackendIdentity,
    CommandResult,
    DirEntry,
    SandboxError,
    SandboxLimits,
    SandboxNotStartedError,
    SandboxSpec,
)


class SshBackend:
    def __init__(self) -> None:
        self.workdir: str = ""
        self.remote_workdir: str = ""
        self.spec: SandboxSpec | None = None
        self.conn: asyncssh.SSHClientConnection | None = None
        self.sftp: asyncssh.SFTPClient | None = None
        self.execution_documents: tuple = ()

    async def start(self, spec: SandboxSpec, workdir: str) -> None:
        connection = spec.connection or {}
        host = connection.get("host")
        user = connection.get("user")
        if not host or not user:
            raise ValueError(
                "SshBackend requires connection={'host': ..., 'user': ...}"
            )

        self.spec = spec
        self.workdir = workdir

        connect_kwargs = {
            "host": host,
            "username": user,
            "port": int(connection.get("port", 22)),
            "known_hosts": connection.get("known_hosts"),
            "connect_timeout": float(
                connection.get("connect_timeout", DEFAULT_CONNECT_TIMEOUT)
            ),
            "login_timeout": float(
                connection.get("login_timeout", DEFAULT_LOGIN_TIMEOUT)
            ),
        }
        if password := connection.get("password"):
            connect_kwargs["password"] = password
        if keys := connection.get("client_keys"):
            connect_kwargs["client_keys"] = list(keys)

        self.conn = await asyncssh.connect(**connect_kwargs)
        self.sftp = await self.conn.start_sftp_client()

        # Fetch explicitly configured SSH context files (no scanning)
        self._context_diagnostics: tuple[dict, ...] = ()
        context_files = getattr(spec, "ssh_context_files", ()) or ()
        if context_files and self.sftp is not None:
            try:
                from electromind.execution.context import fetch_execution_context

                result = await fetch_execution_context(
                    self.sftp,
                    context_files,
                    profile_id=f"{user}@{host}",
                )
                self.execution_documents = result.documents
                self._context_diagnostics = result.diagnostics
            except Exception:
                self.execution_documents = ()
                self._context_diagnostics = ()

        remote = connection.get("workdir") or DEFAULT_REMOTE_WORKDIR
        expanded = await self.expand_remote_path(remote)
        await self.sftp_mkdirs(expanded)
        self.remote_workdir = expanded

    async def close(self) -> None:
        if self.sftp is not None:
            self.sftp.exit()
            self.sftp = None
        if self.conn is not None:
            self.conn.close()
            await self.conn.wait_closed()
            self.conn = None

    async def alive(self) -> bool:
        if self.conn is None or self.conn.is_closed():
            return False
        probe = await self.conn.run("true", check=False, timeout=5)
        return probe.exit_status == 0

    def effective_workdir(self) -> str | None:
        return self.remote_workdir or None

    async def exec(
        self,
        command: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stdin: str | None = None,
        limits: SandboxLimits | None = None,
    ) -> CommandResult:
        if self.conn is None:
            raise SandboxNotStartedError("SshBackend not started")
        applied = limits or (self.spec.default_limits if self.spec else SandboxLimits())
        run_cwd = cwd or self.remote_workdir

        env_prefix = "".join(
            f"export {shell_quote(k)}={shell_quote(v)}; "
            for k, v in (env or {}).items()
        )
        script = f"cd {shell_quote(run_cwd)} && {env_prefix}exec " + " ".join(
            shell_quote(part) for part in command
        )

        started = time.monotonic()
        try:
            result = await self.conn.run(
                script,
                input=stdin,
                check=False,
                timeout=applied.timeout,
            )
        except asyncssh.TimeoutError as error:
            return CommandResult(
                ok=False,
                exit_code=-1,
                stdout="",
                stderr=f"ssh timeout: {error}",
                duration_seconds=time.monotonic() - started,
                timed_out=True,
            )

        stdout = result.stdout if isinstance(result.stdout, str) else ""
        stderr = result.stderr if isinstance(result.stderr, str) else ""
        stdout, stdout_trunc = truncate_string(stdout, applied.stdout_bytes)
        stderr, stderr_trunc = truncate_string(stderr, applied.stderr_bytes)
        exit_code = result.exit_status if result.exit_status is not None else -1
        return CommandResult(
            ok=exit_code == 0,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=time.monotonic() - started,
            stdout_truncated=stdout_trunc,
            stderr_truncated=stderr_trunc,
        )

    async def read_file(self, path: str) -> bytes:
        if self.sftp is None:
            raise SandboxNotStartedError("SshBackend not started")
        async with self.sftp.open(path, "rb") as fp:
            data = await fp.read()
        return data if isinstance(data, bytes) else data.encode("utf-8")

    async def write_file(self, path: str, data: bytes) -> None:
        if self.sftp is None:
            raise SandboxNotStartedError("SshBackend not started")
        parent = os.path.dirname(path) or "."
        await self.sftp_mkdirs(parent)
        async with self.sftp.open(path, "wb") as fp:
            await fp.write(data)

    async def list_dir(self, path: str) -> list[DirEntry]:
        if self.sftp is None:
            raise SandboxNotStartedError("SshBackend not started")
        entries: list[DirEntry] = []
        names = await self.sftp.listdir(path)
        for name in sorted(names):
            if name in (".", ".."):
                continue
            full = os.path.join(path, name)
            attrs = await self.sftp.stat(full)
            is_dir = stat_is_dir(attrs)
            size = None if is_dir else int(attrs.size or 0)
            entries.append(DirEntry(name=name, is_dir=is_dir, size=size))
        return entries

    async def exists(self, path: str) -> bool:
        if self.sftp is None:
            raise SandboxNotStartedError("SshBackend not started")
        try:
            await self.sftp.stat(path)
        except (FileNotFoundError, OSError):
            return False
        except asyncssh.SFTPError:
            # asyncssh 的 SFTPNoSuchFile 等不是 OSError 子类 —— 远端
            # 文件不存在必须返回 False，不能冒泡（真实 loopback 测试发现）。
            return False
        return True

    async def remove(self, path: str, *, recursive: bool = False) -> None:
        if self.sftp is None:
            raise SandboxNotStartedError("SshBackend not started")
        if not await self.exists(path):
            return
        attrs = await self.sftp.stat(path)
        if stat_is_dir(attrs):
            if not recursive:
                raise IsADirectoryError(f"{path} is a directory; pass recursive=True")
            await self.conn.run(f"rm -rf {shell_quote(path)}", check=True, timeout=30)
            return
        await self.sftp.remove(path)

    def describe(self, spec: SandboxSpec, workdir: str) -> BackendIdentity:
        connection = spec.connection if spec else {}
        home = spec.home if spec else "/home/agent"
        host = connection.get("host", "")
        user = connection.get("user", "")
        target = f"{user}@{host}" if user and host else host or "(未配置)"
        lines: list[str] = [f"远程主机：{target}"]
        remote_workdir = self.remote_workdir or workdir
        if remote_workdir:
            lines.append(f"run_command 的远端 shell 工作目录：{remote_workdir}")
            lines.append(f"文件工具路径 {home} 会映射到这个远端目录。")
        return BackendIdentity(
            computer_name="远程 SSH 计算节点",
            extra="\n".join(lines) + "\n",
        )

    async def expand_remote_path(self, path: str) -> str:
        """把 ~ 展开为远端 $HOME 的真实路径。"""
        if not path.startswith("~"):
            return path
        if self.conn is None:
            raise SandboxNotStartedError("SshBackend not started")
        result = await self.conn.run("echo $HOME", check=True, timeout=5)
        home = result.stdout.strip() if isinstance(result.stdout, str) else ""
        if not home:
            raise SandboxError("failed to resolve remote $HOME")
        return home + path[1:]

    async def sftp_mkdirs(self, path: str) -> None:
        """远端 mkdir -p；已存在不报错。"""
        if self.conn is None or not path:
            return
        target = await self.expand_remote_path(path) if path.startswith("~") else path
        await self.conn.run(
            f"mkdir -p {shell_quote(target)}",
            check=True,
            timeout=30,
        )


# --------------------------------------------------------------------------
# SshConnection：类型化的连接配置 + 从 ~/.ssh/config 读取
# --------------------------------------------------------------------------


DEFAULT_SSH_CONFIG = "~/.ssh/config"
DEFAULT_REMOTE_WORKDIR = "~/.electromind"
# TCP+握手总上限；连不上时尽快失败，避免堵死 wire 命令循环。
DEFAULT_CONNECT_TIMEOUT = 10
# SSH 认证阶段上限（TCP 已通之后）。
DEFAULT_LOGIN_TIMEOUT = 15


@dataclass
class SshConnection:
    """SSH 连接配置。用 `.to_dict()` 传给 `Sandbox.create(connection=...)`。

    from_ssh_config(alias) 会读 ~/.ssh/config：把 Hostname / User / Port /
    IdentityFile 全套抠出来，用户只用记住 Host 别名，其它跟平时 `ssh <alias>`
    完全一致。
    """

    host: str
    user: str
    port: int = 22
    password: str | None = None
    client_keys: tuple[str, ...] = ()
    known_hosts: str | None = None
    workdir: str = DEFAULT_REMOTE_WORKDIR

    def to_dict(self) -> dict:
        result: dict = {
            "host": self.host,
            "user": self.user,
            "port": self.port,
            "known_hosts": self.known_hosts,
            "workdir": self.workdir,
        }
        if self.password is not None:
            result["password"] = self.password
        if self.client_keys:
            result["client_keys"] = list(self.client_keys)
        return result

    @classmethod
    def from_ssh_config(
        cls,
        alias: str,
        *,
        config_path: str = DEFAULT_SSH_CONFIG,
        workdir: str = DEFAULT_REMOTE_WORKDIR,
        password: str | None = None,
    ) -> SshConnection:
        path = Path(os.path.expanduser(config_path))
        if not path.exists():
            raise FileNotFoundError(f"ssh config not found: {path}")
        entry = resolve_ssh_alias(alias, parse_ssh_config(path))
        if not entry:
            raise KeyError(f"host alias {alias!r} not found in {path}")

        user = entry.get("user")
        if not user:
            raise ValueError(f"ssh config for {alias!r} has no User; specify manually")

        client_keys: tuple[str, ...] = ()
        if identity := entry.get("identityfile"):
            client_keys = (os.path.expanduser(identity),)

        return cls(
            host=entry.get("hostname", alias),
            user=user,
            port=int(entry.get("port", "22")),
            client_keys=client_keys,
            password=password,
            workdir=workdir,
        )


@dataclass
class SshConfigBlock:
    hosts: tuple[str, ...]
    options: dict[str, str] = field(default_factory=dict)


def parse_ssh_config(path: Path) -> list[SshConfigBlock]:
    """极简 ssh_config 解析器，够 Hostname / User / Port / IdentityFile 用。"""
    blocks: list[SshConfigBlock] = []
    current: SshConfigBlock | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition(" ")
        key = key.lower().strip()
        value = value.strip().strip('"')
        if key == "host":
            current = SshConfigBlock(hosts=tuple(value.split()))
            blocks.append(current)
            continue
        if current is None:
            continue
        current.options.setdefault(key, value)
    return blocks


def resolve_ssh_alias(alias: str, blocks: list[SshConfigBlock]) -> dict[str, str]:
    """按顺序合并所有匹配 alias 的 block；先精确匹配、后通配（跟 openssh 一致：first-match wins）。"""
    merged: dict[str, str] = {}
    for block in blocks:
        if any(host_matches(alias, pattern) for pattern in block.hosts):
            for k, v in block.options.items():
                merged.setdefault(k, v)
    return merged


def host_matches(alias: str, pattern: str) -> bool:
    """精确 alias 或 glob 通配。"""
    if pattern == alias:
        return True
    if "*" not in pattern and "?" not in pattern:
        return False
    import fnmatch

    return fnmatch.fnmatchcase(alias, pattern)


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------


def shell_quote(value: str) -> str:
    """POSIX 单引号安全转义。"""
    if value == "":
        return "''"
    if not any(ch in value for ch in " \t\n\"'\\$`|&;<>*?()[]{}"):
        return value
    escaped = value.replace("'", "'\\''")
    return f"'{escaped}'"


def truncate_string(text: str, limit: int | None) -> tuple[str, bool]:
    if limit is None or len(text.encode("utf-8", errors="replace")) <= limit:
        return text, False
    raw = text.encode("utf-8", errors="replace")[:limit]
    return raw.decode("utf-8", errors="replace"), True


def stat_is_dir(attrs) -> bool:
    permissions = getattr(attrs, "permissions", None) or 0
    return bool(permissions & 0o040000)
