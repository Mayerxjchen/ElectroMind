"""wire 惰性 runner：resume 不必先 open 空会话。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import wire
from app.config import ReplConfig
from electromind.core.events import TextDelta
from electromind.core.message import ToolCall
from electromind.core.turn_result import TurnResult


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


def test_emit_subagent_event_wire_shape(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(wire, "emit_line", lambda line: lines.append(line))
    wire.emit_subagent_event("coder", "messages.sub.coder.0", TextDelta("hello"))
    payload = json.loads(lines[0])
    assert payload["method"] == "SubagentEvent"
    assert payload["params"]["name"] == "coder"
    assert payload["params"]["conversation_id"] == "messages.sub.coder.0"
    assert payload["params"]["event"]["method"] == "TextDelta"
    assert payload["params"]["event"]["params"]["text"] == "hello"


def test_emit_subagent_event_serializes_turn_result_tool_calls(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(wire, "emit_line", lambda line: lines.append(line))
    event = TurnResult(
        content="done",
        tool_calls=[
            ToolCall(
                type="function",
                id="call_1",
                name="delegate_to_subagent",
                arguments='{"type":"coder","task":"hello"}',
            )
        ],
        reasoning_content="thinking",
    )
    wire.emit_subagent_event("coder", "messages.sub.coder.0", event)
    payload = json.loads(lines[0])
    assert payload["params"]["event"]["method"] == "TurnResult"
    tool_calls = payload["params"]["event"]["params"]["tool_calls"]
    assert tool_calls == [
        {
            "type": "function",
            "id": "call_1",
            "name": "delegate_to_subagent",
            "arguments": '{"type":"coder","task":"hello"}',
        }
    ]


@pytest.mark.asyncio
async def test_client_features_without_runner_does_not_open(monkeypatch):
    monkeypatch.setattr(
        wire,
        "open_fresh_runner",
        AsyncMock(side_effect=AssertionError("should not open")),
    )

    state = {"turn": None}
    result = await wire.handle_command(
        {"cmd": "client_features", "features": {"subagent_events": True}},
        None,
        ReplConfig(),
        state,
    )
    assert result is None
    assert state["client_features"] == {"subagent_events": True}


@pytest.mark.asyncio
async def test_resume_with_no_runner_replays_history_without_sandbox(monkeypatch):
    fake_thread = SimpleNamespace(
        id="thread-old",
        load_metainfo=lambda: {"title": "old"},
    )
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
    monkeypatch.setattr(wire, "emit_execution_state", lambda _runner: None)
    monkeypatch.setattr(wire, "emit_execution_context", lambda _runner: None)
    monkeypatch.setattr(wire, "emit_history_replay", lambda _runner: None)
    monkeypatch.setattr(wire, "run_slash_command", AsyncMock())

    result = await wire.handle_command(
        {"cmd": "user", "text": "普通任务消息"},
        None,
        ReplConfig(),
        {"turn": None, "thread_id": "thread-old"},
    )
    assert result is fake
    assert opened == ["thread-old"]


@pytest.mark.asyncio
async def test_slash_before_runner_does_not_open_runner(monkeypatch):
    """Known slash commands are intercepted BEFORE opening a runner."""
    opened: list[str] = []

    async def fake_open_thread(_config, thread_id: str, project_path=None):
        opened.append(thread_id)
        return MagicMock()

    monkeypatch.setattr(wire, "open_thread_runner", fake_open_thread)
    monkeypatch.setattr(wire, "run_slash_command", AsyncMock())

    result = await wire.handle_command(
        {"cmd": "user", "text": "/skills"},
        None,
        ReplConfig(),
        {"turn": None, "thread_id": "thread-old"},
    )
    # Slash consumed; runner NOT opened
    assert opened == []
    assert result is None


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
async def test_list_threads_uses_electromind_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)

    thread_dir = home / ".electromind" / "threads" / "thread-demo"
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
    assert payload["params"]["home"] == str((home / ".electromind").resolve())
    assert payload["params"]["threads"] == [
        {
            "id": "thread-demo",
            "title": "demo title",
            "project_path": "",
            "backend": "local",
        }
    ]


@pytest.mark.asyncio
async def test_list_threads_uses_project_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    project = tmp_path / "proj"
    (project / ".electromind" / "threads" / "thread-proj").mkdir(parents=True)
    (project / ".electromind" / "threads" / "thread-proj" / "thread.toml").write_text(
        '[sandbox]\nbackend = "local"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(project)
    from electromind.paths import activate_home

    activate_home("dev", project)

    lines: list[str] = []
    monkeypatch.setattr(wire, "emit_line", lambda line: lines.append(line))

    await wire.handle_command(
        {"cmd": "list_threads"},
        None,
        ReplConfig(),
        {"turn": None},
    )
    payload = json.loads(lines[0])
    assert payload["params"]["home"] == str((project / ".electromind").resolve())
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
    monkeypatch.setattr(
        wire,
        "open_thread_runner",
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
async def test_sandbox_status_with_thread_id_does_not_open_runner(monkeypatch):
    """状态轮询带 thread_id 时也不能唤醒沙箱（SSH 连不上会堵死 wire）。"""
    monkeypatch.setattr(
        wire,
        "ensure_runner",
        AsyncMock(side_effect=AssertionError("should not open")),
    )
    monkeypatch.setattr(
        wire,
        "open_thread_history",
        lambda thread_id, project_path=None: SimpleNamespace(
            spec=SimpleNamespace(backend="ssh")
        ),
    )
    lines: list[str] = []
    monkeypatch.setattr(wire, "emit_line", lambda line: lines.append(line))

    result = await wire.handle_command(
        {"cmd": "sandbox_status"},
        None,
        ReplConfig(),
        {"turn": None, "thread_id": "thread-ssh"},
    )

    assert result is None
    payload = json.loads(lines[0])
    assert payload["method"] == "SandboxStatus"
    assert payload["params"] == {
        "thread_id": "thread-ssh",
        "backend": "ssh",
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


@pytest.mark.asyncio
async def test_reset_cleans_previous_empty_thread(monkeypatch):
    closed: list[str] = []
    cleaned: list[set[str] | frozenset[str]] = []
    previous = MagicMock()
    previous.thread.id = "thread-empty"
    previous.close = AsyncMock(side_effect=lambda: closed.append("thread-empty"))
    fresh = MagicMock()
    fresh.thread.id = "thread-new"

    async def fake_open_fresh(_config, project_path=None):
        assert project_path is None
        return fresh

    monkeypatch.setattr(wire, "open_fresh_runner", fake_open_fresh)
    monkeypatch.setattr(wire, "emit_history_replay", lambda _runner: None)
    monkeypatch.setattr(
        wire,
        "clean_empty_threads",
        lambda *, keep_thread_ids=frozenset(): cleaned.append(keep_thread_ids),
    )

    result = await wire.handle_command(
        {"cmd": "reset"},
        previous,
        ReplConfig(),
        {"turn": None, "thread_id": "thread-empty"},
    )

    assert result is fresh
    assert closed == ["thread-empty"]
    assert cleaned == [frozenset()]


def test_list_thread_entries_hides_soft_deleted(monkeypatch):
    """list_sessions 已过滤软删除；wire 层正确映射 SessionInfo → dict。"""
    from app.sessions import SessionInfo

    alive = SessionInfo(
        id="thread-alive",
        title="可见",
        project_path="/tmp/test",
        backend="local",
    )

    monkeypatch.setattr(
        "app.sessions.list_sessions",
        lambda home=None: [alive],
    )

    entries = wire.list_thread_entries()
    assert [item["id"] for item in entries] == ["thread-alive"]
    assert entries[0]["title"] == "可见"


@pytest.mark.asyncio
async def test_delete_thread_marks_deleted_at(monkeypatch):
    saved: dict = {}

    class FakeThread:
        id = "thread-x"

        def load_metainfo(self):
            return {"title": "demo"}

        def save_metainfo(self, meta):
            saved.update(meta)

    monkeypatch.setattr(wire.Thread, "open", staticmethod(lambda _id: FakeThread()))
    monkeypatch.setattr(wire, "emit_thread_list", lambda _project=None: None)

    result = await wire.handle_command(
        {"cmd": "delete_thread", "thread_id": "thread-x"},
        None,
        ReplConfig(),
        {"turn": None},
    )
    assert result is None
    assert saved.get("title") == "demo"
    assert isinstance(saved.get("deleted_at"), str) and saved["deleted_at"]


@pytest.mark.asyncio
async def test_reset_applies_backend_and_project_overrides(monkeypatch):
    """新建会话可经 wire reset 指定 backend / project_path。"""
    seen: dict[str, object] = {}
    fresh = MagicMock()
    fresh.thread.id = "thread-new"

    async def fake_open_fresh(config, project_path=None):
        seen["backend"] = config.backend
        seen["project_path"] = project_path
        seen["ssh_host"] = config.ssh_host
        seen["ssh_workdir"] = config.ssh_workdir
        return fresh

    monkeypatch.setattr(wire, "open_fresh_runner", fake_open_fresh)
    monkeypatch.setattr(wire, "emit_history_replay", lambda _runner: None)
    monkeypatch.setattr(wire, "clean_empty_threads", lambda **_kwargs: None)

    result = await wire.handle_command(
        {
            "cmd": "reset",
            "backend": "ssh",
            "project_path": "/tmp/demo",
            "ssh_host": "box",
            "ssh_workdir": "~/work",
        },
        None,
        ReplConfig(backend="local"),
        {"turn": None},
    )

    assert result is fresh
    assert seen == {
        "backend": "ssh",
        "project_path": "/tmp/demo",
        "ssh_host": "box",
        "ssh_workdir": "~/work",
    }


@pytest.mark.asyncio
async def test_ensure_runner_preserves_pending_config_on_retry_failure(monkeypatch):
    """两次连续的 open_fresh_runner 失败，pending_config 不应被消费。

    第一次 ensure_runner 读到 state["pending_config"]，open_fresh_runner 失败；
    第二次 ensure_runner 仍应读到同一个 pending_config，不能回退到原始 config。
    """
    call_count = 0
    seen_configs: list[str] = []

    async def fake_open_fresh(config):
        nonlocal call_count
        call_count += 1
        seen_configs.append(config.backend or "default")
        raise RuntimeError(f"sandbox down #{call_count}")

    monkeypatch.setattr(wire, "open_fresh_runner", fake_open_fresh)

    state: dict = {"pending_config": ReplConfig(backend="ssh")}

    # 第一次尝试 —— 应使用 pending_config（backend="ssh"）
    with pytest.raises(RuntimeError, match="sandbox down #1"):
        await wire.ensure_runner(None, ReplConfig(backend="local"), state)
    assert "pending_config" in state, "失败后 pending_config 应保留供重试"
    assert seen_configs == ["ssh"]

    # 第二次尝试 —— 仍应使用 pending_config，不能回退到传入的 config
    with pytest.raises(RuntimeError, match="sandbox down #2"):
        await wire.ensure_runner(None, ReplConfig(backend="local"), state)
    assert "pending_config" in state, "二次失败后 pending_config 仍应保留"
    assert seen_configs == ["ssh", "ssh"]


@pytest.mark.asyncio
async def test_ensure_runner_clears_pending_config_on_success(monkeypatch):
    """open_fresh_runner 成功后应清除 pending_config，避免后续调用读到脏状态。"""
    fake = MagicMock()
    fake.thread.id = "thread-new"

    async def fake_open_fresh(config):
        return fake

    monkeypatch.setattr(wire, "open_fresh_runner", fake_open_fresh)

    state: dict = {"pending_config": ReplConfig(backend="ssh")}

    runner = await wire.ensure_runner(None, ReplConfig(backend="local"), state)
    assert runner is fake
    assert "pending_config" not in state, "成功后 pending_config 应被清除"


@pytest.mark.asyncio
async def test_ensure_runner_uses_original_config_when_no_pending(monkeypatch):
    """没有 pending_config 时，应使用传入的原始 config。"""
    seen: list[str] = []

    async def fake_open_fresh(config):
        seen.append(config.backend or "default")
        fake = MagicMock()
        fake.thread.id = "thread-new"
        return fake

    monkeypatch.setattr(wire, "open_fresh_runner", fake_open_fresh)

    state: dict = {}
    await wire.ensure_runner(None, ReplConfig(backend="container"), state)
    assert seen == ["container"]
