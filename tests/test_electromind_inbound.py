import asyncio

import pytest

from electromind.core.events import (
    RunBegin,
    TextDelta,
    ToolCallBegin,
    ToolResult,
    TurnEnd,
)
from electromind.runtime.inbound import (
    CancelRun,
    CheckpointPolicy,
    DenyTool,
    DrainResult,
    InboundMailbox,
    PermitTool,
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
    assert result == DrainResult(steers=("one",), steer_ids=("",), cancelled=True)


def test_checkpoint_policy_turn_boundaries():
    policy = CheckpointPolicy()
    assert policy.should_poll_steer(RunBegin("hi"))
    assert policy.should_poll_steer(
        TurnEnd(0, stopped=True, stop_reason="no_tool_calls")
    )
    assert not policy.should_poll_steer(ToolResult("id", "run_command", "{}", ok=True))
    assert not policy.should_poll_steer(TextDelta("x"))
    assert policy.should_poll_cancel(ToolResult("id", "run_command", "{}", ok=True))


def test_checkpoint_policy_stream_throttle():
    policy = CheckpointPolicy(
        poll_cancel_after_stream_delta=True, stream_poll_interval=1.0
    )
    assert policy.should_poll_cancel(TextDelta("a"), now=0.0)
    assert not policy.should_poll_cancel(TextDelta("b"), now=0.1)
    assert policy.should_poll_cancel(TextDelta("c"), now=1.0)
    assert not policy.should_poll_steer(TextDelta("c"))


def test_drain_for_checkpoint_requeues_steer_until_safe():
    policy = CheckpointPolicy()
    box = InboundMailbox()
    box.steer("wait")
    result = box.drain_for_checkpoint(
        ToolCallBegin("id", "run_command", "{}"),
        policy,
    )
    assert result == DrainResult()
    assert box.pending() == 1
    result = box.drain_for_checkpoint(
        TurnEnd(0, stopped=False, stop_reason="continuing"),
        policy,
    )
    assert result == DrainResult(steers=("wait",), steer_ids=("",), cancelled=False)


@pytest.mark.asyncio
async def test_mailbox_async_put():
    box = InboundMailbox()
    await asyncio.to_thread(box.steer, "async")
    assert box.drain().steers == ("async",)


@pytest.mark.asyncio
async def test_drain_for_checkpoint_preserves_permit_events():
    policy = CheckpointPolicy()
    box = InboundMailbox()
    box.permit("call_1")
    box.steer("later")
    result = box.drain_for_checkpoint(
        ToolCallBegin("id", "run_command", "{}"),
        policy,
    )
    assert result == DrainResult()
    assert box.pending() == 2
    assert await box.wait() == PermitTool("call_1")


@pytest.mark.asyncio
async def test_mailbox_permit_and_deny():
    box = InboundMailbox()
    box.permit("a")
    box.deny("b", reason="nope")

    async def take():
        events = []
        while box.pending():
            events.append(await box.wait())
        return events

    events = await take()
    assert events[0] == PermitTool("a")
    assert events[1] == DenyTool("b", "nope")
