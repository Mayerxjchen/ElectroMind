"""wire 惰性 runner：resume 不必先 open 空会话。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import wire
from app.config import ReplConfig


def test_format_exc_system_exit_message():
    assert wire.format_exc(SystemExit("需要 API Key")) == "需要 API Key"


def test_emit_error_wire_shape(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(wire, "emit_line", lambda line: lines.append(line))
    wire.emit_error("boom", where="turn")
    payload = json.loads(lines[0])
    assert payload["method"] == "Error"
    assert payload["params"]["message"] == "boom"
    assert payload["params"]["where"] == "turn"


@pytest.mark.asyncio
async def test_resume_with_no_runner_replays_history_without_sandbox(monkeypatch):
    fake_thread = SimpleNamespace(id="thread-old")
    emitted: list[str] = []

    def fail_open_runner(*_args):
        raise AssertionError("should not open sandbox runner")

    monkeypatch.setattr(wire, "open_thread_runner", fail_open_runner)

    def fake_open_history(thread_id: str, project_path: str | None = None):
        assert thread_id == "thread-old"
        assert project_path is None
        return fake_thread

    monkeypatch.setattr(wire, "open_thread_history", fake_open_history)
    monkeypatch.setattr(
        wire,
        "emit_thread_history_replay",
        lambda thread: emitted.append(thread.id),
    )

    state = {"turn": None}
    result = await wire.handle_command(
        {"cmd": "resume", "thread_id": "thread-old"},
        None,
        ReplConfig(),
        state,
    )
    assert result is None
    assert state["thread_id"] == "thread-old"
    assert emitted == ["thread-old"]


@pytest.mark.asyncio
async def test_user_after_light_resume_opens_target_runner(monkeypatch):
    opened: list[str] = []
    fake = MagicMock()
    fake.thread.id = "thread-old"

    async def fake_open_thread(_config, thread_id: str, project_path=None):
        assert project_path is None
        opened.append(thread_id)
        return fake

    monkeypatch.setattr(wire, "open_thread_runner", fake_open_thread)
    monkeypatch.setattr(wire, "emit_current_thread", lambda _runner: None)
    monkeypatch.setattr(wire, "run_slash_command", AsyncMock())

    result = await wire.handle_command(
        {"cmd": "user", "text": "/skills"},
        None,
        ReplConfig(),
        {"turn": None, "thread_id": "thread-old"},
    )
    assert result is fake
    assert opened == ["thread-old"]


@pytest.mark.asyncio
async def test_commands_without_runner_does_not_open(monkeypatch):
    monkeypatch.setattr(
        wire,
        "open_fresh_runner",
        AsyncMock(side_effect=AssertionError("should not open")),
    )
    monkeypatch.setattr(wire, "emit_slash_commands", lambda: None)

    result = await wire.handle_command(
        {"cmd": "commands"},
        None,
        ReplConfig(),
        {"turn": None},
    )
    assert result is None


@pytest.mark.asyncio
async def test_history_without_runner_does_not_open(monkeypatch):
    monkeypatch.setattr(
        wire,
        "open_fresh_runner",
        AsyncMock(side_effect=AssertionError("should not open")),
    )
    emitted: list[str] = []
    monkeypatch.setattr(
        wire,
        "emit_history_replay",
        lambda runner: emitted.append("history"),
    )

    result = await wire.handle_command(
        {"cmd": "history"},
        None,
        ReplConfig(),
        {"turn": None},
    )
    assert result is None
    assert emitted == []


@pytest.mark.asyncio
async def test_list_threads_uses_pagent_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)

    thread_dir = home / ".pagent" / "threads" / "thread-demo"
    thread_dir.mkdir(parents=True)
    (thread_dir / "thread.toml").write_text('[sandbox]\nbackend = "local"\n')
    (thread_dir / "metainfo.json").write_text(
        '{"title": "demo title"}\n', encoding="utf-8"
    )

    lines: list[str] = []
    monkeypatch.setattr(wire, "emit_line", lambda line: lines.append(line))
    monkeypatch.setattr(
        wire,
        "open_fresh_runner",
        AsyncMock(side_effect=AssertionError("should not open")),
    )

    result = await wire.handle_command(
        {"cmd": "list_threads"},
        None,
        ReplConfig(),
        {"turn": None},
    )
    assert result is None
    payload = json.loads(lines[0])
    assert payload["method"] == "ThreadList"
    assert payload["params"]["home"] == str((home / ".pagent").resolve())
    assert payload["params"]["threads"] == [
        {"id": "thread-demo", "title": "demo title", "project_path": ""}
    ]


@pytest.mark.asyncio
async def test_list_threads_uses_project_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    project = tmp_path / "proj"
    (project / ".pagent" / "threads" / "thread-proj").mkdir(parents=True)
    (project / ".pagent" / "threads" / "thread-proj" / "thread.toml").write_text(
        '[sandbox]\nbackend = "local"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(project)

    lines: list[str] = []
    monkeypatch.setattr(wire, "emit_line", lambda line: lines.append(line))

    await wire.handle_command(
        {"cmd": "list_threads"},
        None,
        ReplConfig(),
        {"turn": None},
    )
    payload = json.loads(lines[0])
    assert payload["params"]["home"] == str((project / ".pagent").resolve())
    assert payload["params"]["threads"][0]["id"] == "thread-proj"


@pytest.mark.asyncio
async def test_history_with_runner_replays_current_thread(monkeypatch):
    fake = MagicMock()
    fake.thread.id = "thread-live"
    fake.messages.data = []
    emitted: list[object] = []
    monkeypatch.setattr(
        wire,
        "emit_history_replay",
        lambda runner: emitted.append(runner),
    )

    result = await wire.handle_command(
        {"cmd": "history"},
        fake,
        ReplConfig(),
        {"turn": None},
    )
    assert result is fake
    assert emitted == [fake]


@pytest.mark.asyncio
async def test_sandbox_tree_with_runner_uses_live_sandbox(monkeypatch):
    fake = MagicMock()
    fake.thread.id = "thread-live"
    fake.sandbox.workdir = "/remote/workdir"
    fake.sandbox.home = "/home/agent"
    fake.sandbox.files.list = AsyncMock(
        side_effect=[
            [
                SimpleNamespace(name="src", is_dir=True),
                SimpleNamespace(name="README.md", is_dir=False),
            ],
            [
                SimpleNamespace(name="main.ts", is_dir=False),
            ],
        ]
    )
    lines: list[str] = []
    monkeypatch.setattr(wire, "emit_line", lambda line: lines.append(line))

    result = await wire.handle_command(
        {"cmd": "sandbox_tree"},
        fake,
        ReplConfig(),
        {"turn": None},
    )

    assert result is fake
    payload = json.loads(lines[0])
    assert payload["method"] == "SandboxTree"
    assert payload["params"]["thread_id"] == "thread-live"
    assert payload["params"]["workdir"] == "/remote/workdir"
    assert payload["params"]["nodes"] == [
        {
            "id": "src",
            "label": "src",
            "kind": "dir",
            "count": 1,
            "children": [
                {
                    "id": "src/main.ts",
                    "label": "main.ts",
                    "kind": "file",
                }
            ],
        },
        {
            "id": "README.md",
            "label": "README.md",
            "kind": "file",
        },
    ]


@pytest.mark.asyncio
async def test_sandbox_tree_skips_unreadable_child(monkeypatch):
    fake = MagicMock()
    fake.thread.id = "thread-live"
    fake.sandbox.workdir = "/remote/workdir"
    fake.sandbox.home = "/home/agent"
    fake.sandbox.files.list = AsyncMock(
        side_effect=[
            [
                SimpleNamespace(name="src", is_dir=True),
                SimpleNamespace(name="README.md", is_dir=False),
            ],
            FileNotFoundError("/home/agent/src/.venv/bin/python"),
        ]
    )
    lines: list[str] = []
    monkeypatch.setattr(wire, "emit_line", lambda line: lines.append(line))

    result = await wire.handle_command(
        {"cmd": "sandbox_tree"},
        fake,
        ReplConfig(),
        {"turn": None},
    )

    assert result is fake
    payload = json.loads(lines[0])
    assert payload["method"] == "SandboxTree"
    assert payload["params"]["nodes"] == [
        {
            "id": "src",
            "label": "src",
            "kind": "dir",
            "count": 0,
            "children": [],
        },
        {
            "id": "README.md",
            "label": "README.md",
            "kind": "file",
        },
    ]


@pytest.mark.asyncio
async def test_sandbox_tree_without_runner_does_not_open(monkeypatch):
    monkeypatch.setattr(
        wire,
        "open_fresh_runner",
        AsyncMock(side_effect=AssertionError("should not open")),
    )
    lines: list[str] = []
    monkeypatch.setattr(wire, "emit_line", lambda line: lines.append(line))

    result = await wire.handle_command(
        {"cmd": "sandbox_tree"},
        None,
        ReplConfig(),
        {"turn": None},
    )

    assert result is None
    payload = json.loads(lines[0])
    assert payload["method"] == "SandboxTree"
    assert payload["params"] == {"thread_id": "", "workdir": "", "nodes": []}


@pytest.mark.asyncio
async def test_sandbox_status_with_runner_uses_live_sandbox(monkeypatch):
    fake = MagicMock()
    fake.thread.id = "thread-live"
    fake.sandbox.workdir = "/remote/workdir"
    fake.sandbox.backend.alive = AsyncMock(return_value=True)
    fake.thread.spec.backend = "local"
    fake.sandbox.backend.inner = type("LocalBackend", (), {})()
    lines: list[str] = []
    monkeypatch.setattr(wire, "emit_line", lambda line: lines.append(line))

    result = await wire.handle_command(
        {"cmd": "sandbox_status"},
        fake,
        ReplConfig(),
        {"turn": None},
    )

    assert result is fake
    payload = json.loads(lines[0])
    assert payload["method"] == "SandboxStatus"
    assert payload["params"] == {
        "thread_id": "thread-live",
        "backend": "local",
        "alive": True,
        "workdir": "/remote/workdir",
    }


@pytest.mark.asyncio
async def test_sandbox_status_without_runner_does_not_open(monkeypatch):
    monkeypatch.setattr(
        wire,
        "open_fresh_runner",
        AsyncMock(side_effect=AssertionError("should not open")),
    )
    lines: list[str] = []
    monkeypatch.setattr(wire, "emit_line", lambda line: lines.append(line))

    result = await wire.handle_command(
        {"cmd": "sandbox_status"},
        None,
        ReplConfig(),
        {"turn": None},
    )

    assert result is None
    payload = json.loads(lines[0])
    assert payload["method"] == "SandboxStatus"
    assert payload["params"] == {
        "thread_id": "",
        "backend": "",
        "alive": False,
        "workdir": "",
    }


@pytest.mark.asyncio
async def test_sandbox_status_probe_failure_falls_back_to_offline(monkeypatch):
    fake = MagicMock()
    fake.thread.id = "thread-live"
    fake.sandbox.workdir = "/remote/workdir"
    fake.sandbox.backend.alive = AsyncMock(side_effect=RuntimeError("probe failed"))
    fake.thread.spec.backend = "ssh"
    fake.sandbox.backend.inner = type("SshBackend", (), {})()
    lines: list[str] = []
    monkeypatch.setattr(wire, "emit_line", lambda line: lines.append(line))

    result = await wire.handle_command(
        {"cmd": "sandbox_status"},
        fake,
        ReplConfig(),
        {"turn": None},
    )

    assert result is fake
    payload = json.loads(lines[0])
    assert payload["method"] == "SandboxStatus"
    assert payload["params"] == {
        "thread_id": "thread-live",
        "backend": "ssh",
        "alive": False,
        "workdir": "/remote/workdir",
    }


@pytest.mark.asyncio
async def test_resume_failure_emits_empty_replay(monkeypatch):
    emitted: list[str] = []

    def boom(*args):
        assert args
        raise RuntimeError("sandbox down")

    monkeypatch.setattr(wire, "open_thread_history", boom)
    monkeypatch.setattr(
        wire, "emit_empty_history_replay", lambda: emitted.append("empty")
    )

    result = await wire.handle_command(
        {"cmd": "resume", "thread_id": "thread-missing"},
        None,
        ReplConfig(),
        {"turn": None},
    )
    assert result is None
    assert emitted == ["empty"]


@pytest.mark.asyncio
async def test_reset_failure_keeps_process_alive(monkeypatch):
    """沙箱打不开时 reset 应发 Error，不能把 wire 进程打崩。"""
    lines: list[str] = []
    monkeypatch.setattr(wire, "emit_line", lambda line: lines.append(line))
    monkeypatch.setattr(
        wire,
        "open_fresh_runner",
        AsyncMock(side_effect=RuntimeError("docker daemon down")),
    )

    result = await wire.handle_command(
        {"cmd": "reset"},
        None,
        ReplConfig(),
        {"turn": None},
    )
    assert result is None
    methods = [json.loads(line)["method"] for line in lines]
    assert "HistoryReplay" in methods
    assert "Error" in methods
    error = next(json.loads(line) for line in lines if "Error" in line)
    assert error["params"]["where"] == "reset"
