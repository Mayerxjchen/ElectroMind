"""ACP (Agent Client Protocol) adapter for pagent.

Bridges :class:`~pagent.agent.Agent` to editors such as Zed over stdio JSON-RPC.
Requires the optional ``agent-client-protocol`` package (``pagent[acp]``).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from acp import (
    PROTOCOL_VERSION,
    run_agent,
    start_tool_call,
    update_agent_message_text,
    update_agent_thought_text,
    update_tool_call,
)
from acp.helpers import ContentBlock
from acp.interfaces import Client
from acp.schema import (
    CloseSessionResponse,
    Implementation,
    InitializeResponse,
    NewSessionResponse,
    PromptResponse,
)

from pagent import Agent, __version__
from pagent.events import (
    Event,
    ReasoningDelta,
    TextDelta,
    ToolCallBegin,
    ToolResult,
)

AgentFactory = Callable[[str], Agent]


def prompt_to_text(blocks: list[ContentBlock]) -> str:
    parts: list[str] = []
    for block in blocks:
        if block.type == "text":
            parts.append(block.text)
    return "\n".join(parts)


def tool_kind(name: str) -> str:
    if name in ("readfile", "read_file", "read"):
        return "read"
    if name in ("bash", "shell", "execute"):
        return "execute"
    if name in ("web_search", "grep_code", "glob_paths", "search"):
        return "search"
    if name in ("calc", "calculate"):
        return "other"
    return "other"


def parse_raw_input(arguments: str) -> Any:
    try:
        return json.loads(arguments)
    except json.JSONDecodeError:
        return arguments


@dataclass
class SessionState:
    cwd: str
    agent: Agent
    run_task: asyncio.Task | None = field(default=None, repr=False)


class PagentACPAgent:
    """ACP agent backed by a pagent :class:`~pagent.agent.Agent` per session."""

    def __init__(self, make_agent: AgentFactory):
        self._make_agent = make_agent
        self._conn: Client | None = None
        self._sessions: dict[str, SessionState] = {}

    def on_connect(self, conn: Client) -> None:
        self._conn = conn

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: Any = None,
        client_info: Any = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        version = (
            protocol_version
            if protocol_version <= PROTOCOL_VERSION
            else PROTOCOL_VERSION
        )
        return InitializeResponse(
            protocol_version=version,
            agent_info=Implementation(name="pagent", version=__version__),
        )

    async def new_session(
        self,
        cwd: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[Any] | None = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        session_id = uuid4().hex
        self._sessions[session_id] = SessionState(cwd=cwd, agent=self._make_agent(cwd))
        return NewSessionResponse(session_id=session_id)

    async def close_session(
        self, session_id: str, **kwargs: Any
    ) -> CloseSessionResponse | None:
        state = self._sessions.pop(session_id, None)
        if state and state.run_task and not state.run_task.done():
            state.run_task.cancel()
        return CloseSessionResponse()

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        state = self._sessions.get(session_id)
        if state and state.run_task and not state.run_task.done():
            state.run_task.cancel()

    async def prompt(
        self,
        prompt: list[ContentBlock],
        session_id: str,
        message_id: str | None = None,
        **kwargs: Any,
    ) -> PromptResponse:
        state = self._sessions.get(session_id)
        if state is None:
            return PromptResponse(stop_reason="refusal", user_message_id=message_id)

        user_text = prompt_to_text(prompt)
        if not user_text.strip():
            return PromptResponse(stop_reason="end_turn", user_message_id=message_id)

        current = asyncio.current_task()
        if current is not None:
            state.run_task = current

        try:
            async for event in state.agent.arun_events(user_text):
                await self._emit(session_id, event)
        except asyncio.CancelledError:
            return PromptResponse(stop_reason="cancelled", user_message_id=message_id)
        finally:
            state.run_task = None

        return PromptResponse(stop_reason="end_turn", user_message_id=message_id)

    async def _emit(self, session_id: str, event: Event) -> None:
        if self._conn is None:
            return

        if isinstance(event, TextDelta):
            await self._conn.session_update(
                session_id, update_agent_message_text(event.text)
            )
            return

        if isinstance(event, ReasoningDelta):
            await self._conn.session_update(
                session_id, update_agent_thought_text(event.text)
            )
            return

        if isinstance(event, ToolCallBegin):
            await self._conn.session_update(
                session_id,
                start_tool_call(
                    event.tool_call_id,
                    event.name,
                    kind=tool_kind(event.name),
                    status="in_progress",
                    raw_input=parse_raw_input(event.arguments),
                ),
            )
            return

        if isinstance(event, ToolResult):
            await self._conn.session_update(
                session_id,
                update_tool_call(
                    event.tool_call_id,
                    status="completed" if event.ok else "failed",
                    raw_output=event.content,
                ),
            )


async def run_stdio(make_agent: AgentFactory) -> None:
    """Run :class:`PagentACPAgent` on stdio (for Zed / other ACP clients)."""
    await run_agent(PagentACPAgent(make_agent))
