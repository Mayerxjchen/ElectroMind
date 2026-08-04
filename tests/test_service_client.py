"""ServiceAgentClient — HTTP Service 客户端（与 EmbeddedAgentClient 同一方法面）。

传输注入（_post / _sse_lines），不依赖真实 HTTP 服务。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.service_client import ServiceAgentClient


def _frame(method: str, **params) -> bytes:
    line = {"jsonrpc": "2.0", "method": method, "params": params}
    return f"data: {json.dumps(line, ensure_ascii=False)}\n\n".encode("utf-8")


def _client(
    monkeypatch,
    posted: list,
    frame_builders: list,
    *,
    event_sink=None,
    gate: bool = True,
):
    """frame_builders: [(posted) -> bytes]；gate=True 时等首个 POST 再放帧。"""
    posted_event = asyncio.Event()

    async def fake_post(payload):
        posted.append(payload)
        posted_event.set()
        return {"ok": True}

    async def fake_sse():
        if gate:
            await posted_event.wait()  # 等 POST 发出（pending 已注册）再给帧
        for build in frame_builders:
            yield build(posted)
        yield None

    client = ServiceAgentClient(event_sink=event_sink)
    monkeypatch.setattr(client, "_post", fake_post)
    monkeypatch.setattr(client, "_sse_lines", fake_sse)
    return client


@pytest.mark.asyncio
async def test_send_input_correlates_ack(monkeypatch):
    posted: list[dict] = []
    client = _client(
        monkeypatch,
        posted,
        [
            lambda p: _frame(
                "input/state",
                thread_id="t1",
                message_id="msg-1",
                state="queued",
                request_id="req-1",
            )
        ],
    )
    await client.start()

    receipt = await client.send_input("t1", "任务", request_id="req-1")

    assert receipt.message_id == "msg-1"
    assert str(receipt.state) == "queued"
    assert posted[0]["cmd"] == "input/send"
    assert posted[0]["request_id"] == "req-1"
    await client.close()


@pytest.mark.asyncio
async def test_send_input_timeout_without_ack(monkeypatch):
    posted: list[dict] = []
    client = _client(monkeypatch, posted, [])  # 无 ACK 帧（流立即结束）
    await client.start()

    # 流结束 → ConnectionError（服务不可达语义）；超时 → TimeoutError
    with pytest.raises((asyncio.TimeoutError, ConnectionError)):
        await client.send_input("t1", "任务", timeout=0.2)
    await client.close()


@pytest.mark.asyncio
async def test_cancel_run_posts_resume_then_cancel(monkeypatch):
    posted: list[dict] = []
    client = _client(monkeypatch, posted, [])
    await client.start()

    await client.cancel_run("t1")

    assert [p["cmd"] for p in posted] == ["resume", "cancel"]
    assert posted[0]["thread_id"] == "t1"
    await client.close()


@pytest.mark.asyncio
async def test_resolve_approval_permit_deny(monkeypatch):
    posted: list[dict] = []
    client = _client(monkeypatch, posted, [])
    await client.start()

    await client.resolve_approval("t1", "run-1", "apr-1", True, tool_call_id="c1")
    await client.resolve_approval("t1", "run-1", "apr-2", False, tool_call_id="c2")

    assert [p["cmd"] for p in posted] == ["permit", "deny"]
    assert posted[0]["approval_id"] == "apr-1"
    assert posted[0]["run_id"] == "run-1"
    await client.close()


@pytest.mark.asyncio
async def test_snapshot_correlates_response(monkeypatch):
    posted: list[dict] = []
    client = _client(
        monkeypatch,
        posted,
        [
            lambda p: _frame(
                "thread/snapshot",
                thread_id="t1",
                exists=True,
                active_run_phase="idle",
                request_id=p[0]["request_id"],  # 服务端回显客户端 request_id
            )
        ],
    )
    await client.start()

    snap = await client.snapshot("t1")

    assert snap["exists"] is True
    assert snap["thread_id"] == "t1"
    await client.close()


@pytest.mark.asyncio
async def test_events_buffer_and_after_seq(monkeypatch):
    posted: list[dict] = []
    client = _client(
        monkeypatch,
        posted,
        [
            lambda p: _frame("input/state", thread_id="t1", state="queued", seq=1),
            lambda p: _frame("run/started", thread_id="t1", run_id="run-1", seq=2),
        ],
        gate=False,  # 纯观察测试：帧直接流入
    )
    await client.start()
    await asyncio.sleep(0.05)  # 等帧被消费

    assert [e["params"]["seq"] for e in client.events("t1")] == [1, 2]
    assert [e["params"]["seq"] for e in client.events("t1", after_seq=1)] == [2]
    await client.close()


@pytest.mark.asyncio
async def test_event_sink_receives_all_lines(monkeypatch):
    posted: list[dict] = []
    seen: list[str] = []
    client = _client(
        monkeypatch,
        posted,
        [
            lambda p: _frame("input/state", thread_id="t1", state="queued", seq=1),
            lambda p: _frame("run/started", thread_id="t1", run_id="run-1", seq=2),
        ],
        event_sink=lambda line: seen.append(line["method"]),
        gate=False,
    )
    await client.start()
    await asyncio.sleep(0.05)

    assert seen == ["input/state", "run/started"]
    await client.close()
