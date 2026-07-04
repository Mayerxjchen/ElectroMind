"""用户入站事件 —— 应用层 → Runner 的控制面（pagentv4）。

与 :mod:`pagentv4.core.events` 的出站 ``Event`` 分离：

- **出站**：RunBegin、TextDelta、ToolResult… —— agent 发生了什么
- **入站**：Steer、CancelRun —— 用户在 run 进行中要做什么

应用层 ``mailbox.steer(text)`` / ``mailbox.cancel()``；
Runner 在 ``_events`` 每个出站 event 之后按 :class:`CheckpointPolicy` 调用
``mailbox.drain_if_policy(...)``。
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


InboundEvent: TypeAlias = Steer | CancelRun


@dataclass
class CheckpointPolicy:
    """出站 event yield 之后，是否 drain 入站邮箱。"""

    poll_after_run_begin: bool = True
    poll_after_turn_begin: bool = True
    poll_after_turn_result: bool = True
    poll_after_turn_end: bool = True
    poll_after_tool_call_begin: bool = True
    poll_after_tool_result: bool = True
    poll_after_stream_delta: bool = False
    stream_poll_interval: float = 0.25

    _last_stream_poll: float | None = field(default=None, init=False, repr=False)

    def should_poll(self, outbound_event: object, *, now: float | None = None) -> bool:
        if isinstance(outbound_event, RunBegin):
            return self.poll_after_run_begin
        if isinstance(outbound_event, TurnBegin):
            return self.poll_after_turn_begin
        if isinstance(outbound_event, TurnResult):
            return self.poll_after_turn_result
        if isinstance(outbound_event, TurnEnd):
            return self.poll_after_turn_end
        if isinstance(outbound_event, ToolCallBegin):
            return self.poll_after_tool_call_begin
        if isinstance(outbound_event, ToolResult):
            return self.poll_after_tool_result
        if isinstance(outbound_event, TextDelta | ReasoningDelta):
            if not self.poll_after_stream_delta:
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


class RunCancelled(Exception):
    """检查点消费到 :class:`CancelRun` 时由 Runner 抛出。"""


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

    def push(self, event: InboundEvent) -> None:
        self._queue.put_nowait(event)

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

    def drain_if_policy(
        self,
        outbound_event: object,
        policy: CheckpointPolicy,
        *,
        now: float | None = None,
    ) -> DrainResult | None:
        if not policy.should_poll(outbound_event, now=now):
            return None
        return self.drain()
