import asyncio

import pytest

from pagentv4.core.events import RunBegin, TextDelta, ToolResult, TurnEnd
from pagentv4.runtime.inbound import (
    CancelRun,
    CheckpointPolicy,
    DrainResult,
    InboundMailbox,
    Steer,
    fold_inbound,
)


def test_fold_steer_in_order():
    result = fold_inbound([Steer("a"), Steer("  b  "), Steer("")])
    assert result.steers == ("a", "b")
    assert not result.cancelled


def test_fold_cancel_stops_later_steer():
    result = fold_inbound([Steer("keep"), CancelRun(), Steer("drop")])
    assert result.steers == ("keep",)
    assert result.cancelled


def test_mailbox_drain_fifo():
    box = InboundMailbox()
    box.steer("one")
    box.cancel()
    result = box.drain()
    assert result == DrainResult(steers=("one",), cancelled=True)


def test_checkpoint_policy_turn_boundaries():
    policy = CheckpointPolicy()
    assert policy.should_poll(RunBegin("hi"))
    assert policy.should_poll(TurnEnd(0, stopped=True, stop_reason="no_tool_calls"))
    assert policy.should_poll(ToolResult("id", "run_command", "{}", ok=True))
    assert not policy.should_poll(TextDelta("x"))


def test_checkpoint_policy_stream_throttle():
    policy = CheckpointPolicy(poll_after_stream_delta=True, stream_poll_interval=1.0)
    assert policy.should_poll(TextDelta("a"), now=0.0)
    assert not policy.should_poll(TextDelta("b"), now=0.1)
    assert policy.should_poll(TextDelta("c"), now=1.0)


@pytest.mark.asyncio
async def test_mailbox_async_put():
    box = InboundMailbox()
    await asyncio.to_thread(box.steer, "async")
    assert box.drain().steers == ("async",)
