"""ContainerBackend —— docker / podman 共享的容器 backend 实现。

约定：宿主 workdir 通过 bind mount 挂到容器里同名路径，所以
- 文件 API 直接落到宿主机 workdir（跟 LocalBackend 等价）
- exec 通过 `<cli> exec -i -w <cwd> <cid> <argv>` 落到容器里

这样 backend 只需负责启容器 + 走 CLI exec，其它路径抽象由 Sandbox 门面处理。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time

from ..base import (
    BackendIdentity,
    CommandResult,
    DirEntry,
    SandboxError,
    SandboxLimits,
    SandboxNotStartedError,
    SandboxSpec,
)
from .local import decode_truncated, kill_and_drain


class ContainerBackend:
    def __init__(self, cli: str, computer_name: str) -> None:
        self.cli = cli
        self.computer_name = computer_name
        self.container_id: str | None = None
        self.workdir: str = ""
        self.spec: SandboxSpec | None = None

    async def start(self, spec: SandboxSpec, workdir: str) -> None:
        if not spec.image:
            raise ValueError(
                f"{self.cli} backend requires spec.image; "
                f"pass Sandbox.create(image=..., backend={self.cli!r})"
            )
        if shutil.which(self.cli) is None:
            raise SandboxError(f"{self.cli} CLI not found in PATH")

        os.makedirs(workdir, exist_ok=True)
        self.spec = spec
        self.workdir = workdir

        argv: list[str] = [
            self.cli,
            "run",
            "-d",
            "--rm",
            "-v",
            f"{workdir}:{workdir}",
            "-w",
            workdir,
        ]
        for key, value in spec.env.items():
            argv.extend(["--env", f"{key}={value}"])
        if spec.command:
            argv.append(spec.image)
            argv.extend(spec.command)
        else:
            ttl = spec.container_ttl_seconds
            sleep_arg = str(ttl) if ttl is not None else "infinity"
            argv.extend([spec.image, "sleep", sleep_arg])

        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise SandboxError(
                f"{self.cli} run failed: "
                f"{stderr.decode('utf-8', errors='replace').strip()}"
            )
        self.container_id = stdout.decode("utf-8", errors="replace").strip()

    async def close(self) -> None:
        if not self.container_id:
            return
        process = await asyncio.create_subprocess_exec(
            self.cli,
            "rm",
            "-f",
            self.container_id,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await process.wait()
        self.container_id = None

    async def alive(self) -> bool:
        if not self.container_id:
            return False
        process = await asyncio.create_subprocess_exec(
            self.cli,
            "inspect",
            "-f",
            "{{.State.Running}}",
            self.container_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await process.communicate()
        if process.returncode != 0:
            return False
        return stdout.decode("utf-8", errors="replace").strip() == "true"

    async def exec(
        self,
        command: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stdin: str | None = None,
        limits: SandboxLimits | None = None,
    ) -> CommandResult:
        if not self.container_id:
            raise SandboxNotStartedError(f"{self.cli} backend not started")
        applied = limits or (self.spec.default_limits if self.spec else SandboxLimits())
        run_cwd = cwd or self.workdir

        argv: list[str] = [self.cli, "exec", "-i", "-w", run_cwd]
        for key, value in (env or {}).items():
            argv.extend(["--env", f"{key}={value}"])
        argv.append(self.container_id)
        argv.extend(command)

        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
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
            size = None if is_dir else os.path.getsize(full)
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
        del workdir
        lines: list[str] = []
        if spec and spec.image:
            lines.append(f"镜像：{spec.image}")
        if self.container_id:
            lines.append(f"容器 ID：{self.container_id[:12]}")
        return BackendIdentity(
            computer_name=self.computer_name,
            extra=("\n".join(lines) + "\n") if lines else "",
        )
