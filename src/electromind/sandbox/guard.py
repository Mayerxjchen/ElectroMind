"""BackendGuard —— sandbox 后端的自愈中间层。

每次对 backend 发起动作（exec / read_file / write_file / list_dir /
exists / remove）之前，先调 `inner.alive()` 探活；死了就重跑
`inner.start(spec, workdir)`。同一次调用最多重启 `restart_max_attempts`
次，重启失败就抛 `SandboxDeadError`。

设计要点：
- 命令执行本身不重试。exec 一次是一次；重启只在 exec **发起前** 触发，
  避免非幂等操作被重放。
- workdir 是持久化载体（宿主 fs bind mount 到容器同名路径），重启容器
  不丢文件；因此"自愈"在语义上是安全的。
- Local backend 的 `alive()` 恒为 True，套 Guard 是零成本 no-op，
  这样上层统一走 Guard，不用 backend 类型分叉。
"""

from __future__ import annotations

from .base import (
    BackendIdentity,
    CommandResult,
    DirEntry,
    SandboxError,
    SandboxLimits,
    SandboxSpec,
)


class SandboxDeadError(SandboxError):
    """backend 死了并且 Guard 也救不回来时抛出。"""


class BackendGuard:
    def __init__(self, inner, restart_max_attempts: int = 2) -> None:
        if restart_max_attempts < 0:
            raise ValueError("restart_max_attempts must be >= 0")
        self.inner = inner
        self.restart_max_attempts = restart_max_attempts
        self.spec: SandboxSpec | None = None
        self.workdir: str = ""
        self.restart_count = 0

    async def start(self, spec: SandboxSpec, workdir: str) -> None:
        self.spec = spec
        self.workdir = workdir
        await self.inner.start(spec, workdir)

    async def close(self) -> None:
        await self.inner.close()

    async def alive(self) -> bool:
        return await self.inner.alive()

    async def ensure_alive(self) -> None:
        if await self.inner.alive():
            return
        if self.spec is None:
            raise SandboxDeadError("guard has no spec; call start() first")

        last_error: BaseException | None = None
        for _ in range(self.restart_max_attempts):
            try:
                await self.inner.close()
            except Exception as error:
                last_error = error
            try:
                await self.inner.start(self.spec, self.workdir)
            except Exception as error:
                last_error = error
                continue
            self.restart_count += 1
            if await self.inner.alive():
                return

        raise SandboxDeadError(
            f"backend dead and restart failed after "
            f"{self.restart_max_attempts} attempt(s): {last_error!r}"
        )

    async def exec(
        self,
        command: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stdin: str | None = None,
        limits: SandboxLimits | None = None,
    ) -> CommandResult:
        await self.ensure_alive()
        return await self.inner.exec(
            command, cwd=cwd, env=env, stdin=stdin, limits=limits
        )

    async def read_file(self, path: str) -> bytes:
        await self.ensure_alive()
        return await self.inner.read_file(path)

    async def write_file(self, path: str, data: bytes) -> None:
        await self.ensure_alive()
        await self.inner.write_file(path, data)

    async def list_dir(self, path: str) -> list[DirEntry]:
        await self.ensure_alive()
        return await self.inner.list_dir(path)

    async def exists(self, path: str) -> bool:
        await self.ensure_alive()
        return await self.inner.exists(path)

    async def remove(self, path: str, *, recursive: bool = False) -> None:
        await self.ensure_alive()
        await self.inner.remove(path, recursive=recursive)

    def describe(self, spec: SandboxSpec, workdir: str) -> BackendIdentity:
        return self.inner.describe(spec, workdir)

    def effective_workdir(self) -> str | None:
        getter = getattr(self.inner, "effective_workdir", None)
        return getter() if callable(getter) else None
