"""HTTP 后端：与 wire 共享命令核，POST /command + GET /events (SSE) + Bearer 鉴权。

传输壳的验证分两层：
- 用 fastapi TestClient 打有限响应端点（POST /command、鉴权、非法命令）。
- 事件经 sink 到达订阅流：直接驱动 WireHttpSession + FanoutSink（避开 TestClient
  对无限 SSE 流的单线程门户死锁）。
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import http_server, wire
from app.config import ReplConfig
from app.transport import FanoutSink, StdoutSink, set_active_sink


@pytest.fixture(autouse=True)
def restore_sink():
    yield
    set_active_sink(StdoutSink())


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv(http_server.AUTH_ENV, raising=False)
    app = http_server.build_app(ReplConfig())
    return TestClient(app)


def test_command_rejects_invalid_json(client):
    assert client.post("/command", content=b"not json").status_code == 400


def test_command_dispatches_get_config(client):
    resp = client.post("/command", json={"cmd": "get_config"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_events_stream_replays_slash_menu():
    """新连接的事件生成器先回放 slash 菜单，收到结束哨兵后收尾。"""

    async def scenario():
        sink = FanoutSink()
        gen = http_server.event_stream(sink)
        first = await gen.__anext__()
        sink.close()
        rest = [frame async for frame in gen]
        return first, rest

    first, rest = asyncio.run(scenario())
    assert first.startswith("data: ")
    event = json.loads(first[len("data: ") :].strip())
    assert event["method"] == "SlashCommands"
    assert rest == []  # 哨兵后不再产出


def test_sse_frame_format():
    assert http_server.sse_frame("x\n") == "data: x\n\n"


def test_auth_required_when_token_set(monkeypatch):
    monkeypatch.setenv(http_server.AUTH_ENV, "secret")
    client = TestClient(http_server.build_app(ReplConfig()))
    assert client.post("/command", json={"cmd": "get_config"}).status_code == 401
    ok = client.post(
        "/command",
        json={"cmd": "get_config"},
        headers={"Authorization": "Bearer secret"},
    )
    assert ok.status_code == 200


def test_check_auth_logic(monkeypatch):
    monkeypatch.delenv(http_server.AUTH_ENV, raising=False)
    assert http_server.check_auth(None) is True  # 未设 token 放行
    monkeypatch.setenv(http_server.AUTH_ENV, "tok")
    assert http_server.check_auth(None) is False
    assert http_server.check_auth("Bearer tok") is True
    assert http_server.check_auth("Bearer wrong") is False
    assert http_server.check_auth("tok") is False


def test_slash_commands_line_matches_wire():
    event = json.loads(wire.slash_commands_line())
    assert event["method"] == "SlashCommands"
    assert event["jsonrpc"] == "2.0"


@pytest.mark.asyncio
async def test_dispatch_delivers_event_to_subscriber():
    """核心对齐：一条命令经共享 handle_command 处理，事件落到订阅队列。"""
    sink = FanoutSink()
    set_active_sink(sink)
    queue = sink.subscribe()
    session = http_server.WireHttpSession(ReplConfig(), sink)
    await session.dispatch({"cmd": "get_config"})
    event = json.loads(await queue.get())
    assert event["method"] == "ConfigSnapshot"


def test_health_is_public_and_side_effect_free(monkeypatch):
    """GET /health 不需要鉴权，始终返回 ok，无副作用。"""
    monkeypatch.setenv(http_server.AUTH_ENV, "secret")
    app = http_server.build_app(ReplConfig())
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "service": "electromind"}


@pytest.mark.asyncio
async def test_session_close_without_runner_is_safe():
    sink = FanoutSink()
    session = http_server.WireHttpSession(ReplConfig(), sink)
    await session.close()  # 没开 runner，也不应抛错
