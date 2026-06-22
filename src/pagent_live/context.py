"""Tool ``context`` and owire / iwire helpers."""

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pagent.events import Event

from .bus import DuplexBus
from .live_events import CancelRun, HumanInputRequired, HumanReply

if TYPE_CHECKING:
    from .agent import LiveAgent

_published_owire: set[int] = set()
_waiters: dict[str, asyncio.Future[str]] = {}


def publish_owire(bus: DuplexBus, event: Event) -> None:
    if id(event) not in _published_owire:
        bus.push_owire(event)
        _published_owire.add(id(event))


def drain_owire_yield(bus: DuplexBus) -> Iterator[Event]:
    seen: set[int] = set()
    while (event := bus.get_owire()) is not None:
        if id(event) in seen:
            continue
        seen.add(id(event))
        yield event


def flush_bus(bus: DuplexBus) -> None:
    while bus.get_owire() is not None:
        pass
    while bus.get_iwire() is not None:
        pass


def reset_live(bus: DuplexBus | None = None, *, flush: bool = True) -> None:
    _published_owire.clear()
    cancel_waits()
    if bus is not None and flush:
        flush_bus(bus)


def end_run(bus: DuplexBus | None = None) -> None:
    """End of ``arun_events``: cancel rendezvous waits, keep owire for UI drain."""
    _published_owire.clear()
    cancel_waits()


async def wait_reply(request_id: str) -> str:
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    _waiters[request_id] = fut
    try:
        return await fut
    except asyncio.CancelledError:
        _waiters.pop(request_id, None)
        raise


def push_iwire(bus: DuplexBus, event: Event) -> None:
    if isinstance(event, HumanReply):
        fut = _waiters.pop(event.tool_call_id, None)
        if fut is not None and not fut.done():
            fut.set_result(event.text)
            return
    bus.push_iwire(event)


def poll_iwire(bus: DuplexBus) -> None:
    """Agent-side checkpoint: drain iwire and dispatch (see spec.md)."""
    while (event := bus.get_iwire()) is not None:
        if isinstance(event, HumanReply):
            push_iwire(bus, event)
        elif isinstance(event, CancelRun):
            cancel_waits()
        else:
            bus.push_iwire(event)


def cancel_waits() -> None:
    for fut in _waiters.values():
        if not fut.done():
            fut.cancel()
    _waiters.clear()


@dataclass(slots=True)
class ToolContext:
    agent: "LiveAgent"
    tool_call_id: str

    def emit(self, event: Event) -> None:
        publish_owire(self.agent.bus, event)

    async def request_human(self, question: str) -> str:
        self.emit(HumanInputRequired(self.tool_call_id, question))
        await asyncio.sleep(0)
        return await wait_reply(self.tool_call_id)
