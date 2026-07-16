"""LocalBackend —— 直接在宿主机运行子进程 + 走本地文件系统。

- exec: `asyncio.create_subprocess_exec` + `wait_for` 超时，POSIX 下用 `resource.setrlimit` 落地 memory / cpu 限制。
- 文件 API 直接操作宿主 workdir。
- start/close 是 no-op，因为宿主进程本身就是「电脑」。
"""

from __future__ import annotations

import asyncio
import os
import resource
import shutil
import sys
import time
from typing import Any

from ..base import BackendIdentity, CommandResult, DirEntry, SandboxLimits, SandboxSpec


def apply_rlimits(limits: SandboxLimits) -> None:
    if limits.memory_bytes is not None:
        resource.setrlimit(
            resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes)
        )
    if limits.cpu_seconds is not None:
        resource.setrlimit(
            resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds)
        )


def decode_truncated(data: bytes, cap: int | None) -> tuple[str, bool]:
    if cap is None or len(data) <= cap:
        return data.decode("utf-8", errors="replace"), False
    return data[:cap].decode("utf-8", errors="replace"), True


async def kill_and_drain(process: asyncio.subprocess.Process) -> tuple[bytes, bytes]:
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    return await process.communicate()


class LocalBackend:
    def __init__(self) -> None:
        self.workdir: str = ""
        self.spec: SandboxSpec | None = None

    async def start(self, spec: SandboxSpec, workdir: str) -> None:
        self.spec = spec
        self.workdir = workdir

    async def close(self) -> None:
        return

    async def alive(self) -> bool:
        return True

    async def exec(
        self,
        command: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stdin: str | None = None,
        limits: SandboxLimits | None = None,
    ) -> CommandResult:
        applied = limits or (self.spec.default_limits if self.spec else SandboxLimits())
        run_env = {**os.environ, **(self.spec.env if self.spec else {}), **(env or {})}
        run_cwd = cwd or self.workdir

        preexec: Any = None
        if sys.platform != "win32" and (
            applied.memory_bytes is not None or applied.cpu_seconds is not None
        ):

            def preexec() -> None:
                apply_rlimits(applied)

        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=run_cwd,
            env=run_env,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=preexec,
        )

        stdin_bytes = stdin.encode("utf-8") if stdin is not None else None
        timed_out = False
        try:
            stdout_raw, stderr_raw = await asyncio.wait_for(
                process.communicate(stdin_bytes), timeout=applied.timeout
            )
        except asyncio.TimeoutError:
            timed_out = True
            stdout_raw, stderr_raw = await kill_and_drain(process)

        stdout, stdout_trunc = decode_truncated(stdout_raw, applied.stdout_bytes)
        stderr, stderr_trunc = decode_truncated(stderr_raw, applied.stderr_bytes)
        exit_code = process.returncode if process.returncode is not None else -1
        return CommandResult(
            ok=(exit_code == 0 and not timed_out),
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=time.monotonic() - started,
            stdout_truncated=stdout_trunc,
            stderr_truncated=stderr_trunc,
            timed_out=timed_out,
        )

    async def read_file(self, path: str) -> bytes:
        with open(path, "rb") as fp:
            return fp.read()

    async def write_file(self, path: str, data: bytes) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as fp:
            fp.write(data)

    async def list_dir(self, path: str) -> list[DirEntry]:
        entries: list[DirEntry] = []
        for name in sorted(os.listdir(path)):
            full = os.path.join(path, name)
            is_dir = os.path.isdir(full)
            try:
                size = None if is_dir else os.path.getsize(full)
            except FileNotFoundError:
                continue
            entries.append(DirEntry(name=name, is_dir=is_dir, size=size))
        return entries

    async def exists(self, path: str) -> bool:
        return os.path.exists(path)

    async def remove(self, path: str, *, recursive: bool = False) -> None:
        if not os.path.exists(path):
            return
        if os.path.isdir(path) and not os.path.islink(path):
            if not recursive:
                raise IsADirectoryError(f"{path} is a directory; pass recursive=True")
            shutil.rmtree(path)
            return
        os.remove(path)

    def describe(self, spec: SandboxSpec, workdir: str) -> BackendIdentity:
        home = spec.home if spec else "/home/agent"
        return BackendIdentity(
            computer_name="本地计算节点",
            extra=(
                f"run_command 的 shell 工作目录：{workdir}\n"
                f"文件工具路径 {home} 会映射到这个本机目录。\n"
            ),
        )
