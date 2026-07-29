from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from .helper import ArunReturnType, EventHandler


@runtime_checkable
class AgentRunner(Protocol):
    """Structural protocol for runner implementations."""

    def run(
        self,
        user_input: str,
        *,
        return_type: ArunReturnType = "event",
        event_handler: EventHandler | None = None,
        **run_kwargs: Any,
    ) -> AsyncIterator[Any]: ...
