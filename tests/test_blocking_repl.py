"""阻塞 REPL（非 TTY / --blocking）经 AgentClient 的事件接收器（验收 G-1）。"""

from __future__ import annotations

import asyncio

import pytest

from app.config import ReplConfig
from app.render import RenderState


def _sink(state, done, config=None, thread_id="t1"):
    from app.repl import _blocking_sink

    sink = _blocking_sink(
        state, done, config or ReplConfig(api_key="k"), thread_id, False, None
    )
    return sink


def test_sink_translates_text_delta(capsys):
    state = RenderState(color=False)
    done = asyncio.Event()
    sink = _sink(state, done)
    sink({"method": "item/delta", "params": {"kind": "text", "text": "你好"}})
    assert "你好" in capsys.readouterr().out
    assert not done.is_set()


def test_sink_translates_tool_events(capsys):
    state = RenderState(color=False)
    done = asyncio.Event()
    sink = _sink(state, done)
    sink(
        {
            "method": "item/started",
            "params": {
                "kind": "tool",
                "tool_call_id": "c1",
                "name": "run_command",
                "arguments": '{"command":"pwd"}',
            },
        }
    )
    sink(
        {
            "method": "item/completed",
            "params": {
                "kind": "tool",
                "tool_call_id": "c1",
                "name": "run_command",
                "content": "ok",
                "ok": True,
            },
        }
    )
    out = capsys.readouterr().out
    assert "tool → run_command" in out
    assert "ok" in out


def test_sink_sets_done_on_run_completed(capsys):
    state = RenderState(color=False)
    done = asyncio.Event()
    sink = _sink(state, done)
    sink({"method": "run/completed", "params": {"stop_reason": "completed"}})
    assert done.is_set()


def test_sink_reasoning_delta(capsys):
    state = RenderState(color=False)
    done = asyncio.Event()
    sink = _sink(state, done)
    sink({"method": "item/delta", "params": {"kind": "reasoning", "text": "想"}})
    assert "想" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_blocking_approval_resolves_via_client(capsys, monkeypatch):
    """阻塞模式审批：y/N 经 client.resolve_approval（绑定 thread+run）。"""
    from app.repl import _blocking_approval

    resolved: list[tuple] = []

    class FakeClient:
        async def resolve_approval(
            self, thread_id, run_id, approval_id, approved, tool_call_id=None
        ):
            resolved.append((thread_id, run_id, approval_id, approved, tool_call_id))
            return True

    params = {
        "thread_id": "t1",
        "run_id": "run-1",
        "approval_id": "apr-1",
        "tool_call_id": "c1",
        "name": "run_command",
        "summary": "rm -rf x",
    }

    def fake_prompt(message):  # to_thread 需要同步可调用
        return "y"

    import app.repl as repl

    monkeypatch.setattr(repl, "emit_prompt", fake_prompt)
    await _blocking_approval(
        {"client": FakeClient()},
        params,
        print,
        fake_prompt,
        lambda line: True if line == "y" else None,
        lambda t, code, on: t,
        "",
        "",
    )
    assert resolved == [("t1", "run-1", "apr-1", True, "c1")]
