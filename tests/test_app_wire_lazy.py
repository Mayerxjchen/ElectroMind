"""wire 惰性 runner：resume 不必先 open 空会话。"""

from __future__ import annotations

import json
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
async def test_resume_with_no_runner_opens_target(monkeypatch):
    opened: list[str] = []
    fake = MagicMock()
    fake.thread.id = "thread-old"
    fake.messages.data = []

    async def fake_open_thread(_config, thread_id: str):
        opened.append(thread_id)
        return fake

    monkeypatch.setattr(wire, "open_thread_runner", fake_open_thread)
    monkeypatch.setattr(wire, "emit_history_replay", lambda _runner: None)

    result = await wire.handle_command(
        {"cmd": "resume", "thread_id": "thread-old"},
        None,
        ReplConfig(),
        {"turn": None},
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
async def test_resume_failure_emits_empty_replay(monkeypatch):
    emitted: list[str] = []

    async def boom(_config, _thread_id: str):
        raise RuntimeError("sandbox down")

    monkeypatch.setattr(wire, "open_thread_runner", boom)
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
