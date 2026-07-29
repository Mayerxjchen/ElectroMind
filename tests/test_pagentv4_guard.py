"""BackendGuard 单测 —— 用 fake backend 覆盖 alive / restart / 死透。"""

from __future__ import annotations

import pytest

from electromind.sandbox import BackendGuard, SandboxDeadError, SandboxSpec


def make_spec(tmp_path) -> SandboxSpec:
    workdir = str(tmp_path)
    return SandboxSpec(
        workspace_id="guard-test",
        workdir=workdir,
        home="/home/agent",
        host_root=workdir,
    )


class FakeBackend:
    """按脚本回答 alive 的假 backend。"""

    def __init__(self, alive_script: list[bool], start_should_fail: int = 0) -> None:
        self.alive_script = list(alive_script)
        self.start_should_fail = start_should_fail
        self.start_calls = 0
        self.close_calls = 0
        self.exec_calls = 0
        self.spec: SandboxSpec | None = None
        self.workdir: str = ""

    async def start(self, spec, workdir):
        self.start_calls += 1
        if self.start_should_fail > 0:
            self.start_should_fail -= 1
            raise RuntimeError("start failed")
        self.spec = spec
        self.workdir = workdir

    async def close(self):
        self.close_calls += 1

    async def alive(self):
        if not self.alive_script:
            return True
        return self.alive_script.pop(0)

    async def exec(self, command, *, cwd=None, env=None, stdin=None, limits=None):
        self.exec_calls += 1
        return {"ok": True, "command": command}

    async def read_file(self, path):
        return b"payload"

    async def write_file(self, path, data):
        return None

    async def list_dir(self, path):
        return []

    async def exists(self, path):
        return True

    async def remove(self, path, *, recursive=False):
        return None

    def describe(self, spec, workdir):
        return None


@pytest.mark.asyncio
async def test_guard_passes_through_when_alive(tmp_path):
    inner = FakeBackend(alive_script=[True])
    guard = BackendGuard(inner)
    await guard.start(make_spec(tmp_path), str(tmp_path))
    result = await guard.exec(["echo", "hi"])
    assert result["ok"] is True
    assert inner.exec_calls == 1
    # 只 start 过一次；alive 是 True 所以没有 restart
    assert inner.start_calls == 1
    assert inner.close_calls == 0


@pytest.mark.asyncio
async def test_guard_restarts_when_dead(tmp_path):
    inner = FakeBackend(alive_script=[False, True])
    guard = BackendGuard(inner)
    await guard.start(make_spec(tmp_path), str(tmp_path))
    # 第一次 alive 说死了 → close + start；第二次 alive 说活了 → 放行 exec
    await guard.exec(["ls"])
    assert inner.start_calls == 2
    assert inner.close_calls == 1
    assert guard.restart_count == 1


@pytest.mark.asyncio
async def test_guard_raises_when_restart_fails(tmp_path):
    # alive 永远 False；start 首次通过（Guard.start 走过一次），之后全失败
    inner = FakeBackend(alive_script=[False] * 10, start_should_fail=10)
    guard = BackendGuard(inner, restart_max_attempts=2)
    # 手动装配 spec/workdir，绕开首次 start 失败
    guard.spec = make_spec(tmp_path)
    guard.workdir = str(tmp_path)
    with pytest.raises(SandboxDeadError):
        await guard.exec(["ls"])


@pytest.mark.asyncio
async def test_guard_ensure_alive_before_file_ops(tmp_path):
    inner = FakeBackend(alive_script=[False, True, True, True])
    guard = BackendGuard(inner)
    await guard.start(make_spec(tmp_path), str(tmp_path))
    # 第一次 alive=False 触发 restart；后续 alive=True
    await guard.read_file("/tmp/x")
    await guard.write_file("/tmp/x", b"hi")
    await guard.list_dir("/tmp")
    assert inner.start_calls == 2
    assert guard.restart_count == 1


@pytest.mark.asyncio
async def test_guard_rejects_negative_attempts():
    with pytest.raises(ValueError):
        BackendGuard(FakeBackend([True]), restart_max_attempts=-1)


@pytest.mark.asyncio
async def test_guard_can_be_disabled_via_sandbox_create(tmp_path):
    """auto_restart=False 时 Sandbox 应该直接用原始 backend，不套 Guard。"""
    from electromind import Sandbox

    async with await Sandbox.create(
        backend="local",
        workdir=str(tmp_path),
        auto_restart=False,
    ) as box:
        # 原始 backend 就是 LocalBackend；套了 Guard 类型会变
        assert not isinstance(box.backend, BackendGuard)


@pytest.mark.asyncio
async def test_guard_default_wraps_backend(tmp_path):
    from electromind import Sandbox

    async with await Sandbox.create(backend="local", workdir=str(tmp_path)) as box:
        assert isinstance(box.backend, BackendGuard)
