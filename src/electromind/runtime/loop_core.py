from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Protocol

from ..core.agent import Agent
from ..core.events import RunBegin, RunEnd, StopReason, TurnBegin, TurnEnd
from ..core.message import Message, Messages, ToolCall
from ..core.turn_result import TurnResult
from ..harness.checkpoints import (
    CheckpointDrain,
    CheckpointKind,
)
from .helper import append_message
from .inbound import RunCancelled
from .run_state import RunState


class LoopCoreAdapter(Protocol):
    agent: Agent
    messages: Messages
    run_state: RunState

    def emit(self, event, *, turn_id: int, turn: int) -> AsyncGenerator: ...

    def stream_agent_events(self, turn_id: int, **run_kwargs) -> AsyncGenerator: ...

    def emit_tool_events(
        self,
        tool_calls: list[ToolCall],
        turn_id: int,
        turn: int,
    ) -> AsyncGenerator: ...

    async def after_continuing(self, *, turn: int) -> None: ...

    async def after_run_end(self, *, turn: int) -> None: ...

    async def checkpoint(
        self, kind: CheckpointKind, tool_call_ids: list[str] | None = None
    ) -> CheckpointDrain | None: ...


async def _apply_checkpoint_drain(
    adapter: LoopCoreAdapter,
    drain: CheckpointDrain | None,
    *,
    turn_id: int,
    turn: int,
) -> None:
    """应用检查点 drain：立即输入注入 + 取消。

    - 立即输入追加为用户消息（永不插入 tool batch 中间）。
    - 取消抛 ``RunCancelled``（由 ``_event_source`` 捕获产出取消终态）。
    """
    if drain is None:
        return
    for text in drain.applied_immediate:
        append_message(adapter.messages, Message.user(text), turn_id=turn_id)
    if drain.cancelled:
        raise RunCancelled(turn)


async def emit_run_end(
    adapter: LoopCoreAdapter,
    *,
    turn_id: int,
    turn: int,
    stop_reason: StopReason,
) -> AsyncGenerator:
    async for event in adapter.emit(
        TurnEnd(turn, stopped=True, stop_reason=stop_reason),
        turn_id=turn_id,
        turn=turn,
    ):
        yield event
    adapter.run_state.turn = turn
    adapter.run_state.stop_reason = stop_reason
    adapter.run_state.phase = "ended"
    async for event in adapter.emit(
        RunEnd(turn, stop_reason=stop_reason),
        turn_id=turn_id,
        turn=turn,
    ):
        yield event
    adapter.run_state.phase = "tearing_down"
    await adapter.after_run_end(turn=turn)
    adapter.run_state.phase = "ended"


async def run_synthesis_turn(
    adapter: LoopCoreAdapter,
    *,
    previous_turn: int,
    turn_id: int,
    **run_kwargs,
) -> AsyncGenerator:
    turn = previous_turn + 1
    adapter.run_state.turn = turn
    async for event in adapter.emit(TurnBegin(turn), turn_id=turn_id, turn=turn):
        yield event
    turn_start = len(adapter.messages.data)

    adapter.run_state.phase = "generating"
    drain = await adapter.checkpoint(CheckpointKind.BEFORE_MODEL)
    await _apply_checkpoint_drain(adapter, drain, turn_id=turn_id, turn=turn)
    async for event in adapter.stream_agent_events(turn_id, **run_kwargs):
        async for emitted in adapter.emit(event, turn_id=turn_id, turn=turn):
            yield emitted
    drain = await adapter.checkpoint(CheckpointKind.AFTER_MODEL)
    await _apply_checkpoint_drain(adapter, drain, turn_id=turn_id, turn=turn)
    adapter.run_state.phase = "running"

    final = TurnResult.from_slice(adapter.messages.data, turn_start).with_usage(
        adapter.agent.last_usage
    )
    async for event in adapter.emit(final, turn_id=turn_id, turn=turn):
        yield event

    if turn_start >= len(adapter.messages.data):
        async for event in emit_run_end(
            adapter,
            turn_id=turn_id,
            turn=turn,
            stop_reason="empty_response",
        ):
            yield event
        return

    if final.has_tool_calls:
        async for event in emit_run_end(
            adapter,
            turn_id=turn_id,
            turn=turn,
            stop_reason="max_turns",
        ):
            yield event
        return

    async for event in emit_run_end(
        adapter,
        turn_id=turn_id,
        turn=turn,
        stop_reason="no_tool_calls",
    ):
        yield event


async def run_event_loop(
    adapter: LoopCoreAdapter,
    *,
    user_input: str,
    turn_id: int,
    **run_kwargs,
) -> AsyncGenerator:
    adapter.run_state.phase = "running"
    async for event in adapter.emit(RunBegin(user_input), turn_id=turn_id, turn=0):
        yield event
    drain = await adapter.checkpoint(CheckpointKind.RUN_STARTED)
    await _apply_checkpoint_drain(adapter, drain, turn_id=turn_id, turn=0)

    for turn in range(adapter.agent.max_turns):
        adapter.run_state.turn = turn
        async for event in adapter.emit(TurnBegin(turn), turn_id=turn_id, turn=turn):
            yield event
        turn_start = len(adapter.messages.data)

        adapter.run_state.phase = "generating"
        drain = await adapter.checkpoint(CheckpointKind.BEFORE_MODEL)
        await _apply_checkpoint_drain(adapter, drain, turn_id=turn_id, turn=turn)
        async for event in adapter.stream_agent_events(turn_id, **run_kwargs):
            async for emitted in adapter.emit(event, turn_id=turn_id, turn=turn):
                yield emitted
        drain = await adapter.checkpoint(CheckpointKind.AFTER_MODEL)
        await _apply_checkpoint_drain(adapter, drain, turn_id=turn_id, turn=turn)
        adapter.run_state.phase = "running"

        result = TurnResult.from_slice(adapter.messages.data, turn_start).with_usage(
            adapter.agent.last_usage
        )
        async for event in adapter.emit(result, turn_id=turn_id, turn=turn):
            yield event

        if turn_start >= len(adapter.messages.data):
            async for event in emit_run_end(
                adapter,
                turn_id=turn_id,
                turn=turn,
                stop_reason="empty_response",
            ):
                yield event
            return

        if not result.has_tool_calls:
            async for event in emit_run_end(
                adapter,
                turn_id=turn_id,
                turn=turn,
                stop_reason="no_tool_calls",
            ):
                yield event
            return

        adapter.run_state.phase = "calling"
        tool_call_ids = [tc.id for tc in result.tool_calls]
        drain = await adapter.checkpoint(
            CheckpointKind.BEFORE_TOOL_BATCH, tool_call_ids=tool_call_ids
        )
        await _apply_checkpoint_drain(adapter, drain, turn_id=turn_id, turn=turn)
        async for event in adapter.emit_tool_events(result.tool_calls, turn_id, turn):
            async for emitted in adapter.emit(event, turn_id=turn_id, turn=turn):
                yield emitted
        drain = await adapter.checkpoint(CheckpointKind.AFTER_TOOL_BATCH)
        await _apply_checkpoint_drain(adapter, drain, turn_id=turn_id, turn=turn)
        adapter.run_state.phase = "running"

        if turn + 1 >= adapter.agent.max_turns:
            async for event in run_synthesis_turn(
                adapter,
                previous_turn=turn,
                turn_id=turn_id,
                **run_kwargs,
            ):
                yield event
            return

        async for event in adapter.emit(
            TurnEnd(turn, stopped=False, stop_reason="continuing"),
            turn_id=turn_id,
            turn=turn,
        ):
            yield event
        await adapter.after_continuing(turn=turn)

    assert False, "unreachable"
