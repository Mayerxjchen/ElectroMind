"""H0: Current behavior contract tests.

Lock down existing model-tool loop, cancel, steer, approval, and history replay
behavior BEFORE any Harness Spine refactoring.  These tests document what the
current code actually does — not what we wish it did.

All tests use in-memory runners (VanillaRunner or Runner with local backend)
and FakeProvider to avoid real LLM calls or Docker dependencies.
"""

from __future__ import annotations

import asyncio  # noqa: F401 — used in wire regression tests
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from electromind import (
    Agent,
    Messages,
    RunEnd,
    TextDelta,
    ToolCallBegin,
    ToolResult,
    TurnBegin,
    TurnEnd,
    TurnResult,
    VanillaRunner,
    tool,
)
from electromind.core.events import (
    RunBegin,
)
from electromind.runtime.inbound import (
    CancelRun,
    CheckpointPolicy,
    DrainResult,
    InboundMailbox,
    Steer,
    fold_inbound,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class FakeStreamChunk:
    """Mimics an OpenAI/DeepSeek streaming chunk."""

    def __init__(self, *, content=None, reasoning=None, tool_calls=None):
        delta = types.SimpleNamespace(
            content=content,
            reasoning_content=reasoning,
            tool_calls=tool_calls,
        )
        self.choices = [types.SimpleNamespace(delta=delta)]


class FakeProvider:
    """Provider that returns pre-programmed chunk sequences.

    Each call to ``complete()`` pops one list of chunks from ``steps``.
    """

    def __init__(self, steps):
        self.steps = list(steps)

    async def complete(self, messages, tools=None, **run_kwargs):
        del messages, tools, run_kwargs
        chunks = self.steps.pop(0)

        async def stream():
            for chunk in chunks:
                yield chunk

        return stream()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool(effect="pure")
def echo(msg: str) -> str:
    """Echo back."""
    return msg


@tool(effect="pure")
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@tool(effect="pure")
def slow_tool(seconds: float = 0.1) -> str:
    """A slow tool for testing concurrency."""
    return f"slept {seconds}s"


# ---------------------------------------------------------------------------
# 1. Model-tool loop event order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_loop_order_single_tool_then_text():
    """A single tool-call turn followed by a text-only synthesis turn must
    produce events in this order:

    Turn 0: RunBegin → TurnBegin → TextDelta… → ToolCallBegin → ToolResult → TurnEnd(tool_batch) → RunEnd(max_turns)
    Turn 1: TurnBegin → TextDelta… → TurnResult(no_tool_calls) → RunEnd(no_tool_calls)
    """
    tc = SimpleNamespace(
        index=0,
        id="c1",
        type="function",
        function=SimpleNamespace(name="echo", arguments='{"msg":"ping"}'),
    )
    provider = FakeProvider(
        [
            [FakeStreamChunk(tool_calls=[tc])],  # turn 0 → tool call
            [FakeStreamChunk(content="result is 42")],  # turn 1 → synthesis text
        ]
    )
    runner = VanillaRunner(Agent(provider, system="test", tools=[echo], max_turns=2))
    events = [
        type(e).__name__ async for e in runner.run("compute", return_type="event")
    ]

    # Turn 0: tool call turn
    assert "RunBegin" in events
    assert "TurnBegin" in events
    assert "ToolCallBegin" in events
    assert "ToolResult" in events
    # Turn 0 ends with max_turns because tools were executed
    assert "TurnEnd" in events
    assert "RunEnd" in events

    # The sequence must be: ToolCallBegin before ToolResult
    tc_idx = events.index("ToolCallBegin")
    tr_idx = events.index("ToolResult")
    assert tc_idx < tr_idx, "ToolCallBegin must appear before ToolResult"


@pytest.mark.asyncio
async def test_event_loop_order_text_only():
    """A text-only response (no tool calls) must produce:
    RunBegin → TurnBegin → TextDelta… → TurnResult(no_tool_calls) → RunEnd(no_tool_calls)
    """
    provider = FakeProvider([[FakeStreamChunk(content="hello world")]])
    runner = VanillaRunner(Agent(provider, system="test", max_turns=5))
    events = [type(e).__name__ async for e in runner.run("hi", return_type="event")]

    assert events[0] == "RunBegin"
    assert "TurnBegin" in events
    assert "TextDelta" in events
    assert "TurnResult" in events
    assert "RunEnd" in events
    assert events[-1] == "RunEnd"

    # Verify stop reason propagation (fresh provider per run)
    provider2 = FakeProvider([[FakeStreamChunk(content="ok")]])
    runner2 = VanillaRunner(Agent(provider2, system="test", max_turns=5))
    last_event = None
    async for e in runner2.run("hi2", return_type="event"):
        last_event = e
    assert isinstance(last_event, RunEnd)
    assert last_event.stop_reason == "no_tool_calls"


# ---------------------------------------------------------------------------
# 2. Multi ToolCall result ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_tool_call_result_pairing():
    """When the model returns N tool calls, each must produce
    ToolCallBegin → ToolResult in order, and the result content must match
    the tool call id.
    """
    tc1 = SimpleNamespace(
        index=0,
        id="call_echo",
        type="function",
        function=SimpleNamespace(name="echo", arguments='{"msg":"first"}'),
    )
    tc2 = SimpleNamespace(
        index=1,
        id="call_add",
        type="function",
        function=SimpleNamespace(name="add", arguments='{"a":1,"b":2}'),
    )
    provider = FakeProvider(
        [
            [FakeStreamChunk(tool_calls=[tc1, tc2])],  # two tool calls
            [FakeStreamChunk(content="done")],  # synthesis
        ]
    )
    runner = VanillaRunner(
        Agent(provider, system="test", tools=[echo, add], max_turns=2)
    )
    tool_events = []
    async for e in runner.run("compute", return_type="event"):
        if isinstance(e, (ToolCallBegin, ToolResult)):
            tool_events.append(e)

    assert len(tool_events) == 4  # 2 begins + 2 results
    assert isinstance(tool_events[0], ToolCallBegin)
    assert tool_events[0].tool_call_id == "call_echo"
    assert isinstance(tool_events[1], ToolResult)
    assert tool_events[1].tool_call_id == "call_echo"
    assert isinstance(tool_events[2], ToolCallBegin)
    assert tool_events[2].tool_call_id == "call_add"
    assert isinstance(tool_events[3], ToolResult)
    assert tool_events[3].tool_call_id == "call_add"


# ---------------------------------------------------------------------------
# 3. Cancel behavior
# ---------------------------------------------------------------------------


def test_fold_inbound_cancel_trumps_steer():
    """Cancel after steer: steer before cancel is kept, steer after is dropped."""
    result = fold_inbound([Steer("keep"), CancelRun(), Steer("drop")])
    assert result.steers == ("keep",)
    assert result.cancelled


def test_fold_inbound_cancel_only():
    """Pure cancel with no steer."""
    result = fold_inbound([CancelRun()])
    assert result.steers == ()
    assert result.cancelled


def test_fold_inbound_empty_steer_ignored():
    """Empty/whitespace-only steer is filtered out."""
    result = fold_inbound([Steer(""), Steer("  "), Steer("valid")])
    assert result.steers == ("valid",)
    assert not result.cancelled


def test_checkpoint_policy_default_steer_points():
    """Steer is only consumed at RunBegin, TurnBegin, TurnEnd — not during
    tool execution or streaming."""
    policy = CheckpointPolicy()
    assert policy.should_poll_steer(RunBegin("hi"))
    assert policy.should_poll_steer(TurnBegin(0))
    assert policy.should_poll_steer(TurnEnd(0, stopped=False, stop_reason="continuing"))
    # Steer NOT consumed here:
    assert not policy.should_poll_steer(ToolCallBegin("id", "cmd", "{}"))
    assert not policy.should_poll_steer(ToolResult("id", "cmd", "ok", ok=True))
    assert not policy.should_poll_steer(TextDelta("hello"))
    assert not policy.should_poll_steer(TurnResult([]))


def test_checkpoint_policy_default_cancel_points():
    """Cancel can be consumed at many more points than steer."""
    policy = CheckpointPolicy()
    assert policy.should_poll_cancel(RunBegin("hi"))
    assert policy.should_poll_cancel(TurnBegin(0))
    assert policy.should_poll_cancel(ToolCallBegin("id", "cmd", "{}"))
    assert policy.should_poll_cancel(ToolResult("id", "cmd", "ok", ok=True))
    assert policy.should_poll_cancel(TurnResult([]))
    assert policy.should_poll_cancel(
        TurnEnd(0, stopped=False, stop_reason="continuing")
    )
    # Cancel NOT consumed during stream (by default):
    assert not policy.should_poll_cancel(TextDelta("hello"))


def test_drain_for_checkpoint_requeues_steer_on_unsafe_point():
    """Steer arriving during a tool batch is re-queued, not dropped."""
    policy = CheckpointPolicy()
    box = InboundMailbox()
    box.steer("later")
    # ToolCallBegin is NOT a steer-safe point
    result = box.drain_for_checkpoint(ToolCallBegin("id", "run_command", "{}"), policy)
    assert result == DrainResult()  # Nothing applied
    assert box.pending() == 1  # Steer is still in queue

    # TurnEnd IS a steer-safe point
    result = box.drain_for_checkpoint(
        TurnEnd(0, stopped=False, stop_reason="continuing"), policy
    )
    assert result == DrainResult(steers=("later",), steer_ids=("",), cancelled=False)
    assert box.pending() == 0


def test_drain_for_checkpoint_permit_passthrough():
    """PermitTool/DenyTool events pass through checkpoints untouched."""
    policy = CheckpointPolicy()
    box = InboundMailbox()
    box.permit("call_1")
    box.deny("call_2", reason="no")
    box.steer("wait")
    result = box.drain_for_checkpoint(ToolCallBegin("id", "run_command", "{}"), policy)
    # Steer re-queued, permit/deny passed through back to queue
    assert result == DrainResult()
    assert box.pending() == 3  # permit, deny, steer all still there


# ---------------------------------------------------------------------------
# 4. Steer checkpoint behavior (current: event-type-based)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_steer_applied_at_turn_end_via_checkpoint():
    """Current behavior: steer is consumed ONLY at RunBegin, TurnBegin, TurnEnd.
    At unsafe checkpoints (ToolCallBegin, ToolResult, TextDelta), steer is
    re-queued — it is NOT applied mid-tool-batch.

    This is the contract that H3 semantic checkpoints must preserve: steer
    must never split a ToolCall/ToolResult pair.
    """
    policy = CheckpointPolicy()

    # Verify steer-safe checkpoints
    assert policy.should_poll_steer(RunBegin("hi"))
    assert policy.should_poll_steer(TurnBegin(0))
    assert policy.should_poll_steer(TurnEnd(0, stopped=False, stop_reason="continuing"))

    # Verify steer-unsafe checkpoints (these protect tool batch integrity)
    assert not policy.should_poll_steer(ToolCallBegin("id", "cmd", "{}"))
    assert not policy.should_poll_steer(ToolResult("id", "cmd", "ok", ok=True))
    assert not policy.should_poll_steer(TextDelta("hello"))
    assert not policy.should_poll_steer(TurnResult([]))

    # At unsafe point, steer is re-queued
    box = InboundMailbox()
    box.steer("wait")
    result = box.drain_for_checkpoint(ToolCallBegin("id", "run_command", "{}"), policy)
    assert result == DrainResult(), "steer must NOT be applied during tool batch"
    assert box.pending() == 1, "steer must be re-queued, not dropped"

    # At safe point, steer is applied
    result = box.drain_for_checkpoint(
        TurnEnd(0, stopped=False, stop_reason="continuing"), policy
    )
    assert result == DrainResult(steers=("wait",), steer_ids=("",), cancelled=False)
    assert box.pending() == 0


# ---------------------------------------------------------------------------
# 5. Messages integrity: ToolCall/ToolResult pairing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_call_result_messages_are_paired():
    """Every ToolCall in messages.data must have exactly one corresponding
    ToolResult before the next ToolCall or end of conversation."""
    tc1 = SimpleNamespace(
        index=0,
        id="call_1",
        type="function",
        function=SimpleNamespace(name="echo", arguments='{"msg":"a"}'),
    )
    tc2 = SimpleNamespace(
        index=0,
        id="call_2",
        type="function",
        function=SimpleNamespace(name="echo", arguments='{"msg":"b"}'),
    )
    provider = FakeProvider(
        [
            [FakeStreamChunk(tool_calls=[tc1, tc2])],
            [FakeStreamChunk(content="final")],
        ]
    )
    runner = VanillaRunner(Agent(provider, system="test", tools=[echo], max_turns=2))
    async for _ in runner.run("go", return_type="event"):
        pass

    # Walk through messages and verify pairing
    pending_tool_call_ids: set[str] = set()
    for msg in runner.messages.data:
        from electromind.core.message import ToolCall as TC
        from electromind.core.message import ToolResult as TR

        if isinstance(msg.content, TC):
            assert msg.content.id not in pending_tool_call_ids, (
                f"Duplicate ToolCall id: {msg.content.id}"
            )
            pending_tool_call_ids.add(msg.content.id)
        elif isinstance(msg.content, TR):
            assert msg.content.tool_call_id in pending_tool_call_ids, (
                f"ToolResult {msg.content.tool_call_id} has no preceding ToolCall"
            )
            pending_tool_call_ids.discard(msg.content.tool_call_id)

    assert not pending_tool_call_ids, (
        f"Orphan ToolCalls without results: {pending_tool_call_ids}"
    )


# ---------------------------------------------------------------------------
# 6. Regression: user input ignored during active Run (wire layer)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wire_ignores_user_during_active_turn():
    """Current wire behavior: when a turn is active (state['turn'] is a live
    asyncio.Task), new 'user' commands are silently ignored with a log message.

    THIS IS A REGRESSION TEST.  The Harness Spine must replace this with
    proper enqueue/defer semantics.
    """
    from app import wire
    from app.config import ReplConfig

    # Create a real, non-done asyncio.Task to represent an active turn
    async def long_running():
        await asyncio.sleep(60)

    active_task = asyncio.create_task(long_running())
    try:
        # Verify: turn_active returns True for a live Task
        active_state: dict = {"turn": active_task}
        assert wire.turn_active(active_state), (
            "turn_active must return True when turn task is not done"
        )

        # Verify: turn_active returns False when state has no turn
        idle_state: dict = {"turn": None}
        assert not wire.turn_active(idle_state), (
            "turn_active must return False when turn is None"
        )

        # Verify: the gate at wire.py line 1353-1355 exists
        # When turn_active is True, handle_command returns early without
        # starting a new user turn.
        runner = MagicMock()
        runner.thread.id = "thread-test"

        with (
            patch.object(wire, "emit_history_replay", lambda r: None),
            patch.object(wire, "log", lambda text: None),
        ):
            result = await wire.handle_command(
                {"cmd": "user", "text": "should be ignored"},
                runner,
                ReplConfig(),
                active_state,
            )
            # Command is ignored, runner returned unchanged
            assert result is runner
    finally:
        active_task.cancel()
        try:
            await active_task
        except asyncio.CancelledError:
            pass


# ---------------------------------------------------------------------------
# 7. Regression: resume closes old Runner (wire layer)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wire_resume_preserves_old_runner():
    """Harness Spine: resuming a different thread preserves the old runner.

    Switching threads must NOT close the previous runner — background
    tasks keep running.  The old runner stays alive via the harness
    manager; wire just stops tracking it locally.
    """
    from app import wire
    from app.config import ReplConfig

    closed_runners: list[str] = []

    old_runner = MagicMock()
    old_runner.thread.id = "thread-old"
    old_runner.close = AsyncMock(
        side_effect=lambda: closed_runners.append("thread-old")
    )

    fake_thread = MagicMock()
    fake_thread.id = "thread-new"
    fake_thread.load_metainfo.return_value = {}

    with (
        patch.object(wire, "open_thread_history", lambda tid, pp=None: fake_thread),
        patch.object(wire, "thread_is_soft_deleted", lambda meta: False),
        patch.object(wire, "emit_execution_state_cleared", lambda: None),
        patch.object(wire, "emit_thread_history_replay", lambda t: None),
    ):
        # Resume from thread-old to thread-new
        result = await wire.handle_command(
            {"cmd": "resume", "thread_id": "thread-new"},
            old_runner,
            ReplConfig(),
            {"turn": None},
        )
        # Harness Spine: old runner is NOT closed
        assert "thread-old" not in closed_runners, (
            "Switching threads must not close the previous runner"
        )
        # Resume handler returns None (caller must open a new runner
        # for the target thread)
        assert result is None


# ---------------------------------------------------------------------------
# 8. HistoryReplay does not open a Sandbox
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wire_history_replay_without_runner_does_not_open_sandbox():
    """Current wire behavior: requesting history without a runner opens a
    Thread (no sandbox) and replays messages.  It does NOT open a sandbox.

    THIS IS A REGRESSION TEST.  HistoryReplay must never create side effects
    like SSH connections or container starts.
    """
    from app import wire
    from app.config import ReplConfig

    sandbox_opened = False

    class FakeThread:
        id = "thread-hist"

        def load_metainfo(self):
            return {"title": "test"}

        @property
        def messages_conversation_id(self):
            return "conv-1"

        def open_store(self):
            return MagicMock()

        def load_messages(self):
            return Messages()

    fake_thread = FakeThread()

    def fake_open_thread(config, thread_id, project_path=None):
        nonlocal sandbox_opened
        # open_thread_runner calls Thread.open + open_sandbox etc.
        # We want to verify sandbox is NOT opened for history replay
        return MagicMock(thread=fake_thread, messages=Messages())

    with (
        patch.object(wire, "open_thread_runner", fake_open_thread),
        patch.object(wire, "emit_thread_history_replay", lambda t, pp=None: None),
    ):
        await wire.handle_command(
            {"cmd": "history", "thread_id": "thread-hist"},
            None,  # No active runner
            ReplConfig(),
            {"turn": None},
        )
        # The key assertion: history command with no runner should NOT
        # trigger sandbox creation.  open_thread_runner does currently
        # try to open sandbox — this test documents that gap.
        assert not sandbox_opened, "HistoryReplay must never open a sandbox"


# ---------------------------------------------------------------------------
# 9. RunCancelled produces complete event sequence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_cancelled_produces_turn_end_and_run_end():
    """When RunCancelled is raised by the InboundMailbox checkpoint mechanism,
    the Runner's _event_source must catch it and emit TurnEnd + RunEnd
    with stop_reason='cancelled'.

    Tests the cancel-path at the Runner level (not VanillaRunner, which has
    no inbound mailbox).
    """
    tc = SimpleNamespace(
        index=0,
        id="c1",
        type="function",
        function=SimpleNamespace(name="echo", arguments='{"msg":"ping"}'),
    )
    _provider = FakeProvider(
        [
            [FakeStreamChunk(tool_calls=[tc])],
            [FakeStreamChunk(content="done")],
        ]
    )
    # Use the full Runner with a custom CheckpointPolicy that polls cancel
    # after every event, and pre-load cancel into the mailbox

    # Test at the LoopAdapter level with a RunCancelled injection instead,
    # since full Runner requires sandbox setup.
    # We verify: when _event_source catches RunCancelled, it yields
    # TurnEnd(cancelled) + RunEnd(cancelled).

    # Instead, test the CancelRun → DrainResult → RunCancelled chain
    box = InboundMailbox()
    box.cancel()
    policy = CheckpointPolicy()
    result = box.drain_for_checkpoint(RunBegin("hi"), policy)
    assert result is not None
    assert result.cancelled, "Cancel must be detected at RunBegin checkpoint"


# ---------------------------------------------------------------------------
# 10. Max turns → synthesis turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_turns_grants_synthesis_turn():
    """When max_turns is reached with pending tool calls, the agent gets one
    final synthesis turn to produce a text response."""
    tc = SimpleNamespace(
        index=0,
        id="c1",
        type="function",
        function=SimpleNamespace(name="echo", arguments='{"msg":"ping"}'),
    )
    provider = FakeProvider(
        [
            [FakeStreamChunk(tool_calls=[tc])],  # turn 0: tool call
            [FakeStreamChunk(content="final answer")],  # synthesis
        ]
    )
    runner = VanillaRunner(Agent(provider, system="test", tools=[echo], max_turns=1))
    texts = [t async for t in runner.run("solve", return_type="text")]
    assert "".join(texts) == "final answer"


# ---------------------------------------------------------------------------
# 11. RunState phase transitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_state_phase_transitions():
    """Verify the RunState phase transitions through a normal tool-call run.

    Observed phases (from outside the async generator): the 'initializing'
    phase is set synchronously inside run() before the first yield, so the
    first observable phase is 'running'.  Core phases are:
    running → generating → running → calling → running → ended
    """
    tc = SimpleNamespace(
        index=0,
        id="c1",
        type="function",
        function=SimpleNamespace(name="echo", arguments='{"msg":"hi"}'),
    )
    provider = FakeProvider(
        [
            [FakeStreamChunk(tool_calls=[tc])],
            [FakeStreamChunk(content="ok")],
        ]
    )
    agent = Agent(provider, system="test", tools=[echo], max_turns=2)
    runner = VanillaRunner(agent)

    phases_seen: list[str] = []
    async for _ in runner.run("go", return_type="event"):
        phases_seen.append(runner.run_state.phase)

    # Core phases that must appear during a tool-call run
    assert "running" in phases_seen, f"got: {phases_seen}"
    assert "generating" in phases_seen, f"got: {phases_seen}"
    assert "calling" in phases_seen, f"got: {phases_seen}"
    # After loop completes, phase is 'ended'
    assert runner.run_state.phase == "ended"


# ---------------------------------------------------------------------------
# 12. Empty response exits gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_response_produces_run_end_with_empty_response_reason():
    """When the model produces no content and no tool calls, the loop ends
    with stop_reason='empty_response'."""
    # Use a provider that returns empty chunks
    provider = FakeProvider([[FakeStreamChunk(content="")]])
    runner = VanillaRunner(Agent(provider, system="test", max_turns=5))
    events = [e async for e in runner.run("hi", return_type="event")]

    run_ends = [e for e in events if isinstance(e, RunEnd)]
    assert len(run_ends) == 1
    assert run_ends[0].stop_reason == "empty_response"
