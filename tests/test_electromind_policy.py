"""Sandbox 权限策略单测。"""

from __future__ import annotations

import os

import pytest

from electromind.sandbox.policy import (
    check_backend_path,
    check_command,
    is_system_path,
    under_root,
    validate_command_policy,
)


def test_under_root():
    root = "/tmp/workspace"
    assert under_root("/tmp/workspace", root)
    assert under_root("/tmp/workspace/foo", root)
    assert not under_root("/tmp/other", root)
    assert not under_root("/tmp/workspace/../escape", root)


def test_is_system_path():
    assert is_system_path("/usr/bin/python3")
    assert is_system_path("/etc/hosts")
    assert not is_system_path("/home/dev/.ssh/id_rsa")


def test_check_command_open_allows_escape():
    check_command("cat /home/dev/secret", workdir="/home/dev/agent", policy="open")


def test_check_command_workdir_blocks_parent():
    with pytest.raises(PermissionError, match="parent directory"):
        check_command("ls ..", workdir="/tmp/ws", policy="workdir")


def test_check_command_workdir_blocks_cd_chain():
    with pytest.raises(PermissionError, match="parent directory"):
        check_command(
            "cd .. && cd .. && ls -la", workdir="/home/dev/agent", policy="workdir"
        )


def test_check_command_workdir_blocks_cd_absolute_escape():
    workdir = "/home/dev/agent"
    with pytest.raises(PermissionError, match="cd target escapes"):
        check_command("cd /home/dev && ls", workdir=workdir, policy="workdir")


def test_check_command_workdir_blocks_cd_tilde():
    with pytest.raises(PermissionError, match="cd ~"):
        check_command("cd ~ && ls", workdir="/home/dev/agent", policy="workdir")


def test_check_command_workdir_allows_cd_subdir():
    check_command("cd src && ls", workdir="/tmp/ws", policy="workdir")


def test_check_command_workdir_blocks_outside_home():
    workdir = "/home/dev/agent"
    with pytest.raises(PermissionError, match="outside workspace"):
        check_command("cat /home/dev/.bashrc", workdir=workdir, policy="workdir")


def test_check_command_workdir_allows_workspace_paths():
    workdir = "/tmp/ws"
    check_command(f"cat {workdir}/foo.txt", workdir=workdir, policy="workdir")
    check_command("cat foo.txt", workdir=workdir, policy="workdir")


def test_check_command_workdir_allows_system_paths():
    check_command("python3 --version", workdir="/tmp/ws", policy="workdir")
    check_command("/usr/bin/git status", workdir="/tmp/ws", policy="workdir")


def test_check_command_workdir_allows_urls():
    check_command(
        "curl -s -o /dev/null --connect-timeout 5 https://www.baidu.com",
        workdir="/tmp/ws",
        policy="workdir",
    )


def test_check_command_workdir_still_blocks_real_path_after_url():
    with pytest.raises(PermissionError, match="outside workspace"):
        check_command(
            "curl https://www.baidu.com && cat /home/dev/.bashrc",
            workdir="/home/dev/agent",
            policy="workdir",
        )


def test_check_backend_path():
    workdir = "/tmp/ws"
    check_backend_path(os.path.join(workdir, "a.txt"), workdir=workdir)
    with pytest.raises(PermissionError):
        check_backend_path("/etc/passwd", workdir=workdir)


def test_validate_command_policy():
    assert validate_command_policy("open") == "open"
    with pytest.raises(ValueError):
        validate_command_policy("strict")


@pytest.mark.asyncio
async def test_sandbox_workdir_policy_blocks_cd_chain(tmp_path):
    from electromind import Sandbox

    async with await Sandbox.create(
        backend="local",
        workdir=str(tmp_path),
        command_policy="workdir",
    ) as box:
        result = await box.commands.run("cd .. && ls -la")
        assert not result.ok
        assert result.exit_code == 126
        assert "parent directory" in result.stderr


@pytest.mark.asyncio
async def test_sandbox_workdir_policy_blocks_escape(tmp_path):
    from electromind import Sandbox

    secret = tmp_path.parent / "secret.txt"
    secret.write_text("nope", encoding="utf-8")

    async with await Sandbox.create(
        backend="local",
        workdir=str(tmp_path),
        command_policy="workdir",
    ) as box:
        result = await box.commands.run(f"cat {secret}")
        assert not result.ok
        assert result.exit_code == 126
        assert "outside workspace" in result.stderr


@pytest.mark.asyncio
async def test_sandbox_workdir_policy_allows_mapped_home(tmp_path):
    from electromind import Sandbox

    (tmp_path / "target.txt").write_text("payload", encoding="utf-8")

    async with await Sandbox.create(
        backend="local",
        workdir=str(tmp_path),
        command_policy="workdir",
    ) as box:
        result = await box.commands.run("cat /home/agent/target.txt")
        assert result.ok
        assert result.stdout.strip() == "payload"


@pytest.mark.asyncio
async def test_sandbox_workdir_policy_allows_curl_url(tmp_path):
    from electromind import Sandbox

    async with await Sandbox.create(
        backend="local",
        workdir=str(tmp_path),
        command_policy="workdir",
    ) as box:
        result = await box.commands.run(
            "printf '%s\\n' https://www.baidu.com >/dev/null"
        )
        assert result.ok
        assert result.exit_code == 0


@pytest.mark.asyncio
async def test_sandbox_trusted_bypasses_policy(tmp_path):
    from electromind import Sandbox

    outside = tmp_path.parent / "outside.txt"
    outside.write_text("ok", encoding="utf-8")

    async with await Sandbox.create(
        backend="local",
        workdir=str(tmp_path),
        command_policy="workdir",
    ) as box:
        result = await box.commands.run(f"cat {outside}", trusted=True)
        assert result.ok
        assert result.stdout.strip() == "ok"
