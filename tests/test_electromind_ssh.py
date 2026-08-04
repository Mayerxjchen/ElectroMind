"""SshBackend 单测。

- 单元测试：shell_quote / truncate / start 参数校验 —— 无依赖，一直跑
- 端到端：需要环境变量 `ELECTROMIND_SSH_HOST` 配置一个真实可用的 SSH 目标
  才会跑。这是因为 asyncssh 内嵌 server 支持 exec+SFTP 的成本太高，
  真在容器/远端跑更有意义。

环境变量约定（端到端测试）：
    ELECTROMIND_SSH_HOST        必填；host
    ELECTROMIND_SSH_USER        必填；user
    ELECTROMIND_SSH_PORT        选填；默认 22
    ELECTROMIND_SSH_PASSWORD    选填
    ELECTROMIND_SSH_KEY         选填；私钥路径
    ELECTROMIND_SSH_WORKDIR     选填；默认 ~/electromind-test
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest

from electromind.sandbox.backends.ssh import (
    SshConfigBlock,
    SshConnection,
    host_matches,
    parse_ssh_config,
    resolve_ssh_alias,
    shell_quote,
    stat_is_dir,
    truncate_string,
)


def build_connection() -> dict | None:
    host = os.environ.get("ELECTROMIND_SSH_HOST")
    user = os.environ.get("ELECTROMIND_SSH_USER")
    if not host or not user:
        return None
    connection: dict = {"host": host, "user": user, "known_hosts": None}
    if port := os.environ.get("ELECTROMIND_SSH_PORT"):
        connection["port"] = int(port)
    if password := os.environ.get("ELECTROMIND_SSH_PASSWORD"):
        connection["password"] = password
    if key := os.environ.get("ELECTROMIND_SSH_KEY"):
        connection["client_keys"] = [key]
    connection["workdir"] = os.environ.get(
        "ELECTROMIND_SSH_WORKDIR", "~/electromind-test"
    )
    return connection


needs_ssh = pytest.mark.skipif(
    build_connection() is None,
    reason="set ELECTROMIND_SSH_HOST + ELECTROMIND_SSH_USER to run",
)


@needs_ssh
@pytest.mark.asyncio
async def test_ssh_backend_end_to_end(tmp_path):
    from electromind import Sandbox

    connection = build_connection()
    async with await Sandbox.create(
        backend="ssh",
        workdir=str(tmp_path),
        connection=connection,
    ) as box:
        # workdir 已被 backend 覆盖成远端路径
        assert box.workdir.endswith("electromind-test") or box.workdir.startswith("/")

        result = await box.commands.run("echo hello ssh")
        assert result.ok is True
        assert result.stdout.strip() == "hello ssh"

        await box.files.write("note.txt", "greetings")
        assert await box.files.read_text("note.txt") == "greetings"

        entries = await box.files.list(".")
        names = {entry.name for entry in entries}
        assert "note.txt" in names

        await box.files.remove("note.txt")
        assert await box.files.exists("note.txt") is False


@needs_ssh
@pytest.mark.asyncio
async def test_ssh_backend_alive_check(tmp_path):
    from electromind import Sandbox

    connection = build_connection()
    box = await Sandbox.create(
        backend="ssh",
        workdir=str(tmp_path),
        connection=connection,
    )
    try:
        inner = box.backend.inner
        assert await inner.alive() is True
        await inner.close()
        assert await inner.alive() is False
    finally:
        await box.close()


@pytest.mark.asyncio
async def test_ssh_backend_start_passes_connect_timeout(monkeypatch):
    from electromind.sandbox.backends import ssh as ssh_mod
    from electromind.sandbox.backends.ssh import SshBackend
    from electromind.sandbox.base import SandboxSpec

    captured: dict = {}

    class FakeConn:
        async def start_sftp_client(self):
            return FakeSftp()

        def close(self):
            return None

        async def wait_closed(self):
            return None

    class FakeSftp:
        async def chdir(self, path):
            return None

        def exit(self):
            return None

    async def fake_connect(**kwargs):
        captured.update(kwargs)
        return FakeConn()

    monkeypatch.setattr(ssh_mod.asyncssh, "connect", fake_connect)

    backend = SshBackend()
    backend.expand_remote_path = AsyncMock(return_value="/home/u/electromind")
    backend.sftp_mkdirs = AsyncMock()
    await backend.start(
        SandboxSpec(connection={"host": "example.com", "user": "alice"}),
        "/local",
    )
    assert captured["host"] == "example.com"
    assert captured["username"] == "alice"
    assert captured["connect_timeout"] == ssh_mod.DEFAULT_CONNECT_TIMEOUT
    assert captured["login_timeout"] == ssh_mod.DEFAULT_LOGIN_TIMEOUT
    await backend.close()


@pytest.mark.asyncio
async def test_ssh_backend_requires_host_and_user():
    from electromind.sandbox.backends.ssh import SshBackend
    from electromind.sandbox.base import SandboxSpec

    backend = SshBackend()
    with pytest.raises(ValueError):
        await backend.start(SandboxSpec(connection={}), "/tmp/x")


def test_shell_quote_basic():
    assert shell_quote("abc") == "abc"
    assert shell_quote("") == "''"
    assert shell_quote("has space") == "'has space'"
    assert shell_quote("it's") == "'it'\\''s'"


def test_truncate_string():
    assert truncate_string("abc", None) == ("abc", False)
    assert truncate_string("abc", 10) == ("abc", False)
    assert truncate_string("abcdefgh", 3) == ("abc", True)


def test_stat_is_dir_uses_permissions_bit():
    class Attrs:
        permissions = 0o040755

    class FileAttrs:
        permissions = 0o100644

    assert stat_is_dir(Attrs()) is True
    assert stat_is_dir(FileAttrs()) is False


def test_host_matches_exact_and_glob():
    assert host_matches("prod", "prod") is True
    assert host_matches("prod-1", "prod") is False
    assert host_matches("prod-1", "prod-*") is True
    assert host_matches("prod-1", "prod-?") is True
    assert host_matches("staging", "prod-*") is False


def test_parse_ssh_config_reads_blocks(tmp_path):
    config = tmp_path / "config"
    config.write_text(
        "\n".join(
            [
                "# comment line",
                "Host prod",
                "  Hostname 10.0.0.1",
                "  User alice",
                "  Port 2222",
                "  IdentityFile ~/.ssh/id_prod",
                "",
                "Host stage-* backup",
                "  Hostname 10.0.0.2",
                "  User bob",
            ]
        ),
        encoding="utf-8",
    )

    blocks = parse_ssh_config(config)
    assert len(blocks) == 2
    assert isinstance(blocks[0], SshConfigBlock)
    assert blocks[0].hosts == ("prod",)
    assert blocks[0].options["hostname"] == "10.0.0.1"
    assert blocks[0].options["port"] == "2222"
    assert blocks[1].hosts == ("stage-*", "backup")


def test_resolve_ssh_alias_first_match_wins():
    blocks = [
        SshConfigBlock(hosts=("prod",), options={"hostname": "exact.example"}),
        SshConfigBlock(
            hosts=("prod-*",),
            options={"hostname": "glob.example", "port": "2200"},
        ),
        SshConfigBlock(hosts=("*",), options={"user": "fallback"}),
    ]

    resolved = resolve_ssh_alias("prod", blocks)
    assert resolved["hostname"] == "exact.example"
    assert resolved["user"] == "fallback"

    resolved_glob = resolve_ssh_alias("prod-42", blocks)
    assert resolved_glob["hostname"] == "glob.example"
    assert resolved_glob["port"] == "2200"


def test_ssh_connection_from_ssh_config_full(tmp_path):
    identity = tmp_path / "id_rsa"
    identity.write_text("dummy", encoding="utf-8")
    config = tmp_path / "config"
    config.write_text(
        "\n".join(
            [
                "Host demo",
                "  Hostname host.example",
                "  User alice",
                "  Port 2200",
                f"  IdentityFile {identity}",
            ]
        ),
        encoding="utf-8",
    )

    conn = SshConnection.from_ssh_config(
        "demo",
        config_path=str(config),
        workdir="~/custom",
    )
    assert conn.host == "host.example"
    assert conn.user == "alice"
    assert conn.port == 2200
    assert conn.client_keys == (str(identity),)
    assert conn.workdir == "~/custom"

    payload = conn.to_dict()
    assert payload["host"] == "host.example"
    assert payload["user"] == "alice"
    assert payload["port"] == 2200
    assert payload["client_keys"] == [str(identity)]
    assert payload["workdir"] == "~/custom"
    assert "password" not in payload


def test_ssh_connection_from_ssh_config_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        SshConnection.from_ssh_config("demo", config_path=str(tmp_path / "nope"))


def test_ssh_connection_from_ssh_config_missing_alias(tmp_path):
    config = tmp_path / "config"
    config.write_text("Host other\n  User bob\n", encoding="utf-8")
    with pytest.raises(KeyError):
        SshConnection.from_ssh_config("demo", config_path=str(config))


def test_ssh_connection_from_ssh_config_missing_user(tmp_path):
    config = tmp_path / "config"
    config.write_text(
        "Host demo\n  Hostname host.example\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        SshConnection.from_ssh_config("demo", config_path=str(config))


def test_ssh_connection_to_dict_includes_password_when_set():
    conn = SshConnection(host="h", user="u", password="secret")
    payload = conn.to_dict()
    assert payload["password"] == "secret"
    assert "client_keys" not in payload
