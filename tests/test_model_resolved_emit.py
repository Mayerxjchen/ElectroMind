"""P3: model/resolved 事件广播测试 —— Run 开始时解析一次并广播。"""

from __future__ import annotations

import json

from app import wire
from app.config import ReplConfig


def _capture(monkeypatch) -> list[str]:
    lines: list[str] = []
    monkeypatch.setattr(wire, "emit_line", lambda line: lines.append(line))
    return lines


def _parsed(monkeypatch) -> list[dict]:
    lines = _capture(monkeypatch)
    wire._emit_model_resolved(ReplConfig(model="auto", session_mode="ask"), None, "t1")
    return [json.loads(line) for line in lines]


def test_model_resolved_auto_ask(monkeypatch):
    captured = _parsed(monkeypatch)
    payload = captured[0]["params"]
    assert captured[0]["method"] == "model/resolved"
    assert payload["thread_id"] == "t1"
    assert payload["model_policy"] == "Auto"
    assert payload["effective_model"] == "deepseek-v4-flash"
    assert payload["reason"] == "session-mode:ask:fast"
    assert payload["phase"] == "plan"


def test_model_resolved_auto_agent(monkeypatch):
    lines = _capture(monkeypatch)
    wire._emit_model_resolved(ReplConfig(model="auto", session_mode="run"), None, "t1")
    captured = [json.loads(line) for line in lines]
    assert captured[0]["params"]["effective_model"] == "deepseek-v4-pro"
    assert captured[0]["params"]["reason"] == "session-mode:agent:balanced"


def test_model_resolved_requested_mode_wins(monkeypatch):
    lines = _capture(monkeypatch)
    from electromind.harness.state import SessionMode

    wire._emit_model_resolved(
        ReplConfig(model="auto", session_mode="agent"),
        SessionMode.PLAN,
        "t1",
    )
    captured = [json.loads(line) for line in lines]
    assert captured[0]["params"]["reason"] == "session-mode:plan:best"


def test_model_resolved_named(monkeypatch):
    lines = _capture(monkeypatch)
    wire._emit_model_resolved(ReplConfig(model="deepseek-v4-flash"), None, "t1")
    captured = [json.loads(line) for line in lines]
    assert captured[0]["params"]["effective_model"] == "deepseek-v4-flash"
    assert captured[0]["params"]["reason"] == "policy:named"


def test_model_resolved_plan_execute_phase(monkeypatch):
    lines = _capture(monkeypatch)
    wire._emit_model_resolved(
        ReplConfig(model="plan-execute", session_mode="plan"),
        None,
        "t1",
        phase="execute",
    )
    captured = [json.loads(line) for line in lines]
    assert captured[0]["params"]["reason"] == "policy:hybrid:phase:execute:balanced"


def test_model_resolved_failure_degrades_gracefully(monkeypatch):
    """解析异常不得阻断本轮 —— 降级为 resolved_model() 结果。"""
    import electromind.model_resolver as mr

    monkeypatch.setattr(
        mr,
        "resolve_model",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    # 降级路径走 resolved_model()（named 不经过解析器，避免二次触发被打爆的 resolve）
    lines = _capture(monkeypatch)
    wire._emit_model_resolved(ReplConfig(model="deepseek-v4-flash"), None, "t1")
    captured = [json.loads(line) for line in lines]
    assert captured[0]["params"]["effective_model"] == "deepseek-v4-flash"
    assert captured[0]["params"]["reason"] == "resolve-failed"
