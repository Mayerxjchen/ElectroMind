"""事件出口（EventSink）：把"emit 一行事件"与"写到哪"解耦。

wire 与 http 两套后端共用同一套命令处理核（``handle_command`` / ``run_user_turn``），
它们产出的事件行只经过 ``emit_line`` 这一个出口。这里把出口抽象成 sink：

- ``StdoutSink``：写 stdout（wire 模式，逐字节等价于旧实现）。
- ``FanoutSink``：广播给所有订阅队列（http 模式，每个 SSE 连接一个队列）。

进程级单一活跃 sink（单会话模型：一个进程一个会话）。wire 默认用 StdoutSink，
http 启动时换成 FanoutSink，所有 ``/events`` 连接订阅同一个 sink。
"""

from __future__ import annotations

import asyncio
import sys
from typing import Protocol


class EventSink(Protocol):
    def emit(self, line: str) -> None: ...


class StdoutSink:
    """写 stdout。line 已自带换行（encode_event_line 的约定）。"""

    def emit(self, line: str) -> None:
        sys.stdout.write(line)
        sys.stdout.flush()


class FanoutSink:
    """广播给所有订阅队列。每个 SSE 连接 subscribe 一个队列，断开时 unsubscribe。"""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str | None]] = set()

    def subscribe(self) -> asyncio.Queue[str | None]:
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str | None]) -> None:
        self._subscribers.discard(queue)

    def emit(self, line: str) -> None:
        for queue in self._subscribers:
            queue.put_nowait(line)

    def close(self) -> None:
        """给所有订阅者投递结束哨兵（None），让 SSE 生成器收尾。"""
        for queue in self._subscribers:
            queue.put_nowait(None)
        self._subscribers.clear()


_active_sink: EventSink = StdoutSink()


def active_sink() -> EventSink:
    return _active_sink


def set_active_sink(sink: EventSink) -> None:
    global _active_sink
    _active_sink = sink
