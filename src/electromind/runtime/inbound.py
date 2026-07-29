"""用户入站事件 —— 应用层 → Runner 的控制面（pagentv4）。

与 :mod:`electromind.core.events` 的出站 ``Event`` 分离：

- **出站**：RunBegin、TextDelta、ToolResult… —— agent 发生了什么
- **入站**：Steer、CancelRun、PermitTool、DenyTool —— 用户在 run 进行中要做什么

应用层 ``mailbox.steer(text)`` / ``mailbox.cancel()`` / ``mailbox.permit(id)`` /
``mailbox.deny(id)``；Runner 在出站 event 检查点 drain steer/cancel；
``wait_tool_permit`` 从同一邮箱消费 permit/deny。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TypeAlias

from ..core.events import (
    ReasoningDelta,
    RunBegin,
    TextDelta,
    ToolCallBegin,
    ToolResult,
    TurnBegin,
    TurnEnd,
)
from ..core.turn_result import TurnResult


@dataclass(frozen=True, slots=True)
class Steer:
    """中途插话：在下一检查点追加 ``Message.user(text)``，继续当前 run。"""

    text: str


@dataclass(frozen=True, slots=True)
class CancelRun:
    """中止当前 run；已写入 messages 的保留，未执行的工具不再跑。"""


@dataclass(frozen=True, slots=True)
class PermitTool:
    """批准执行 ``tool_call_id`` 对应的工具（供 ``wait_tool_permit`` 消费）。"""

    tool_call_id: str


@dataclass(frozen=True, slots=True)
class DenyTool:
    """拒绝执行工具；``reason`` 写入 tool result，让模型知道是用户拒绝。"""

    tool_call_id: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ToolPermitResult:
    approved: bool
    reason: str = ""


InboundEvent: TypeAlias = Steer | CancelRun | PermitTool | DenyTool


@dataclass
class CheckpointPolicy:
    """出站 event yield 之后，是否 drain 入站邮箱。"""

    poll_steer_after_run_begin: bool = True
    poll_steer_after_turn_begin: bool = True
    poll_steer_after_turn_end: bool = True

    poll_cancel_after_run_begin: bool = True
    poll_cancel_after_turn_begin: bool = True
    poll_cancel_after_turn_result: bool = True
    poll_cancel_after_turn_end: bool = True
    poll_cancel_after_tool_call_begin: bool = True
    poll_cancel_after_tool_result: bool = True
    poll_cancel_after_stream_delta: bool = False
    stream_poll_interval: float = 0.25

    _last_stream_poll: float | None = field(default=None, init=False, repr=False)

    def should_poll_steer(self, outbound_event: object) -> bool:
        if isinstance(outbound_event, RunBegin):
            return self.poll_steer_after_run_begin
        if isinstance(outbound_event, TurnBegin):
            return self.poll_steer_after_turn_begin
        if isinstance(outbound_event, TurnEnd):
            return self.poll_steer_after_turn_end
        return False

    def should_poll_cancel(
        self, outbound_event: object, *, now: float | None = None
    ) -> bool:
        if isinstance(outbound_event, RunBegin):
            return self.poll_cancel_after_run_begin
        if isinstance(outbound_event, TurnBegin):
            return self.poll_cancel_after_turn_begin
        if isinstance(outbound_event, TurnResult):
            return self.poll_cancel_after_turn_result
        if isinstance(outbound_event, TurnEnd):
            return self.poll_cancel_after_turn_end
        if isinstance(outbound_event, ToolCallBegin):
            return self.poll_cancel_after_tool_call_begin
        if isinstance(outbound_event, ToolResult):
            return self.poll_cancel_after_tool_result
        if isinstance(outbound_event, TextDelta | ReasoningDelta):
            if not self.poll_cancel_after_stream_delta:
                return False
            clock = time.monotonic() if now is None else now
            if (
                self._last_stream_poll is not None
                and clock - self._last_stream_poll < self.stream_poll_interval
            ):
                return False
            self._last_stream_poll = clock
            return True
        return False

    def should_poll(self, outbound_event: object, *, now: float | None = None) -> bool:
        return self.should_poll_steer(outbound_event) or self.should_poll_cancel(
            outbound_event, now=now
        )


class RunCancelled(Exception):
    """检查点消费到 :class:`CancelRun` 时由 Runner 抛出。"""

    def __init__(self, turn: int) -> None:
        self.turn = turn
        super().__init__(turn)


@dataclass(frozen=True, slots=True)
class DrainResult:
    steers: tuple[str, ...] = ()
    cancelled: bool = False

    @property
    def has_steer(self) -> bool:
        return bool(self.steers)


def fold_inbound(events: list[InboundEvent]) -> DrainResult:
    """FIFO 折叠。遇到 ``CancelRun`` 后不再收录后续 steer。"""
    steers: list[str] = []
    cancelled = False
    for event in events:
        if isinstance(event, Steer):
            if not cancelled:
                text = event.text.strip()
                if text:
                    steers.append(text)
        elif isinstance(event, CancelRun):
            cancelled = True
    return DrainResult(steers=tuple(steers), cancelled=cancelled)


class InboundMailbox:
    """Runner 持有的入站队列。"""

    def __init__(self, *, maxsize: int = 0) -> None:
        self._queue: asyncio.Queue[InboundEvent] = asyncio.Queue(maxsize=maxsize)

    def steer(self, text: str) -> None:
        self._queue.put_nowait(Steer(text))

    def cancel(self) -> None:
        self._queue.put_nowait(CancelRun())

    def permit(self, tool_call_id: str) -> None:
        self._queue.put_nowait(PermitTool(tool_call_id))

    def deny(self, tool_call_id: str, *, reason: str = "") -> None:
        self._queue.put_nowait(DenyTool(tool_call_id, reason))

    def push(self, event: InboundEvent) -> None:
        self._queue.put_nowait(event)

    async def wait(self) -> InboundEvent:
        return await self._queue.get()

    def pending(self) -> int:
        return self._queue.qsize()

    def drain(self) -> DrainResult:
        events: list[InboundEvent] = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return fold_inbound(events)

    def drain_for_checkpoint(
        self,
        outbound_event: object,
        policy: CheckpointPolicy,
        *,
        now: float | None = None,
    ) -> DrainResult | None:
        steer_ok = policy.should_poll_steer(outbound_event)
        cancel_ok = policy.should_poll_cancel(outbound_event, now=now)
        if not steer_ok and not cancel_ok:
            return None

        raw: list[InboundEvent] = []
        while True:
            try:
                raw.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if not raw:
            return DrainResult()

        steers_apply: list[str] = []
        steers_requeue: list[Steer] = []
        passthrough: list[InboundEvent] = []
        cancelled = False
        for event in raw:
            if isinstance(event, PermitTool | DenyTool):
                passthrough.append(event)
            elif isinstance(event, CancelRun):
                cancelled = True
            elif isinstance(event, Steer):
                text = event.text.strip()
                if not text or cancelled:
                    continue
                if steer_ok:
                    steers_apply.append(text)
                else:
                    steers_requeue.append(event)

        for event in passthrough:
            self._queue.put_nowait(event)
        for event in steers_requeue:
            self._queue.put_nowait(event)

        return DrainResult(steers=tuple(steers_apply), cancelled=cancelled)

    def drain_if_policy(
        self,
        outbound_event: object,
        policy: CheckpointPolicy,
        *,
        now: float | None = None,
    ) -> DrainResult | None:
        return self.drain_for_checkpoint(outbound_event, policy, now=now)
