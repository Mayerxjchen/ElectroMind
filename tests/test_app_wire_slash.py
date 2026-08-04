"""回归测试：未知斜杠命令和绝对路径不会被拦截为斜杠命令。
已知命令仍正常执行。
"""

from __future__ import annotations

import asyncio

import pytest

from app import wire
from app.config import ReplConfig


@pytest.fixture
def captured(monkeypatch):
    """返回一个 dict，记录 run_slash_command 被调用的参数。"""
    record: dict = {"name": None, "called": False}

    async def fake_run_slash_command(name: str, runner) -> None:
        record["name"] = name
        record["called"] = True

    monkeypatch.setattr(wire, "run_slash_command", fake_run_slash_command)
    return record


def _send_user(text: str):
    """发送一条 user 命令。runner 打开可能失败（测试环境），忽略异常。"""

    async def _do():
        try:
            await wire.handle_command(
                {"cmd": "user", "text": text},
                None,
                ReplConfig(),
                {"turn": None},
            )
        except Exception:
            pass

    asyncio.run(_do())


def test_absolute_path_unix_not_treated_as_slash(captured):
    """Unix 绝对路径 /Users/... 不触发斜杠命令。"""
    _send_user("/Users/chenxuanjie/agent/electromind")
    assert not captured["called"], (
        f"绝对路径不应触发斜杠命令，但 run_slash_command 被调用了: {captured['name']}"
    )


def test_absolute_path_linux_not_treated_as_slash(captured):
    """Linux 绝对路径 /home/... 不触发斜杠命令。"""
    _send_user("/home/username/project")
    assert not captured["called"], (
        f"绝对路径不应触发斜杠命令，但 run_slash_command 被调用了: {captured['name']}"
    )


def test_unknown_slash_not_treated_as_command(captured):
    """未知的 /unknown 不触发斜杠命令，交给 Agent 处理。"""
    _send_user("/unknown_command")
    assert not captured["called"], (
        f"未知命令应交给 Agent，但 run_slash_command 被调用了: {captured['name']}"
    )


def test_known_slash_help_still_works(captured, monkeypatch):
    """/help 仍正常被识别为斜杠命令。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    _send_user("/help")
    assert captured["called"], "已知命令 /help 应正常触发 run_slash_command"
    assert captured["name"] == "help", f"期望 name='help'，实际: {captured['name']}"


def test_known_slash_ls_still_works(captured, monkeypatch):
    """/ls 仍正常被识别为斜杠命令。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    _send_user("/ls")
    assert captured["called"], "已知命令 /ls 应正常触发 run_slash_command"
    assert captured["name"] == "ls", f"期望 name='ls'，实际: {captured['name']}"
