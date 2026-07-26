"""EventSink 传输层：stdout / fanout 出口与进程级切换。"""

from __future__ import annotations

import asyncio

import pytest

from app import transport
from app.transport import FanoutSink, StdoutSink, active_sink, set_active_sink


@pytest.fixture(autouse=True)
def restore_sink():
    original = transport.active_sink()
    yield
    set_active_sink(original)


def test_default_sink_is_stdout():
    assert isinstance(active_sink(), StdoutSink)


def test_stdout_sink_writes(capsys):
    StdoutSink().emit("hello\n")
    assert capsys.readouterr().out == "hello\n"


def test_set_active_sink_switches_target():
    sink = FanoutSink()
    set_active_sink(sink)
    assert active_sink() is sink


def test_fanout_broadcasts_to_all_subscribers():
    sink = FanoutSink()
    a = sink.subscribe()
    b = sink.subscribe()
    sink.emit("line\n")
    assert a.get_nowait() == "line\n"
    assert b.get_nowait() == "line\n"


def test_fanout_unsubscribe_stops_delivery():
    sink = FanoutSink()
    queue = sink.subscribe()
    sink.unsubscribe(queue)
    sink.emit("line\n")
    assert queue.empty()


def test_fanout_close_sends_sentinel():
    sink = FanoutSink()
    queue = sink.subscribe()
    sink.close()
    assert queue.get_nowait() is None


def test_emit_line_delegates_to_active_sink():
    """wire.emit_line 走当前活跃 sink，切到 FanoutSink 后事件不再进 stdout。"""
    from app import wire

    sink = FanoutSink()
    queue = sink.subscribe()
    set_active_sink(sink)
    wire.emit_line("event\n")
    assert queue.get_nowait() == "event\n"


def test_fanout_delivery_across_queue_await():
    async def scenario():
        sink = FanoutSink()
        queue = sink.subscribe()
        sink.emit("a\n")
        got = await queue.get()
        return got

    assert asyncio.run(scenario()) == "a\n"
