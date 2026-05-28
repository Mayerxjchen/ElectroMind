"""Duplex transport: ``push_owire`` / ``get_owire`` / ``push_iwire`` / ``get_iwire``."""

import asyncio

from .live_events import Event


class DuplexBus:
    def __init__(self, maxsize: int = 0):
        """``maxsize=0`` means unbounded (asyncio default)."""
        self.owire: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self.iwire: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self._owire_ready = asyncio.Event()

    def push_owire(self, event: Event) -> None:
        self.owire.put_nowait(event)
        self._owire_ready.set()

    def get_owire(self) -> Event | None:
        try:
            event = self.owire.get_nowait()
        except asyncio.QueueEmpty:
            return None
        if self.owire.empty():
            self._owire_ready.clear()
        return event

    async def wait_owire(self, timeout: float | None = None) -> Event | None:
        event = self.get_owire()
        if event is not None:
            return event
        try:
            if timeout is None:
                await self._owire_ready.wait()
            else:
                await asyncio.wait_for(self._owire_ready.wait(), timeout)
        except asyncio.TimeoutError:
            return None
        return self.get_owire()

    def push_iwire(self, event: Event) -> None:
        self.iwire.put_nowait(event)

    def get_iwire(self) -> Event | None:
        try:
            return self.iwire.get_nowait()
        except asyncio.QueueEmpty:
            return None
