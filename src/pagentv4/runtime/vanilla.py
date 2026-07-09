from __future__ import annotations

from collections.abc import AsyncIterator
from inspect import isawaitable

from ..core.agent import Agent
from ..core.events import ToolCallBegin, ToolResult
from ..core.message import Message, Messages, ToolCall
from ..core.tool import FunctionTool, ToolOutput
from .helper import (
    ArunReturnType,
    EventHandler,
    append_message,
    ensure_system,
    message_to_event,
    project_event,
)
from .loop_core import run_event_loop


class VanillaRunner:
    """Minimal in-memory AgentRunner.

    Included:

    - [x] tool execution for Agent.tools
    - [x] message state in memory
    - [x] event stream and return_type projection
    - [x] max_turns loop with one synthesis turn

    Excluded:

    - [ ] message persistence
    - [ ] thread lifecycle
    - [ ] sandbox tools
    - [ ] inbound cancel/steer/checkpoint
    - [ ] tool hooks or approval
    - [ ] skills injection
    """

    def __init__(self, agent: Agent, messages: Messages | None = None):
        self.agent = agent
        self.messages = messages if messages is not None else Messages()

    async def execute_tool(self, tool_call: ToolCall) -> ToolOutput:
        name = tool_call.name
        tool: FunctionTool = self.agent.tool_map.get(name)
        if tool is None:
            return ToolOutput.fail(
                f"error: unknown tool {name!r}; available: {sorted(self.agent.tool_map)}"
            )
        return await tool.acall(tool_call.arguments)

    async def emit(self, event, *, turn_id: int, turn: int) -> AsyncIterator:
        del turn_id, turn
        yield event

    async def stream_agent_events(
        self,
        turn_id: int,
        **run_kwargs,
    ) -> AsyncIterator:
        async for message in self.agent.generate_messages(self.messages, **run_kwargs):
            append_message(self.messages, message, turn_id=turn_id)
            event = message_to_event(message)
            if event is not None:
                yield event

    async def emit_tool_events(
        self,
        tool_calls: list[ToolCall],
        turn_id: int,
        turn: int,
    ) -> AsyncIterator:
        del turn
        for tool_call in tool_calls:
            yield ToolCallBegin(tool_call.id, tool_call.name, tool_call.arguments)
            output = await self.execute_tool(tool_call)
            append_message(
                self.messages,
                Message.tool_result(tool_call.id, output.content),
                turn_id=turn_id,
            )
            yield ToolResult(
                tool_call.id,
                tool_call.name,
                output.content,
                ok=output.ok,
            )

    async def after_continuing(self, *, turn: int) -> None:
        del turn

    async def after_run_end(self, *, turn: int) -> None:
        del turn

    async def run(
        self,
        user_input: str,
        *,
        return_type: ArunReturnType = "event",
        event_handler: EventHandler | None = None,
        **run_kwargs,
    ) -> AsyncIterator:
        """Run one prompt through the vanilla event loop."""
        if return_type not in {"event", "text", "acp", "message"}:
            raise ValueError(f"unknown return_type: {return_type!r}")

        ensure_system(self.messages, self.agent.system)
        turn_id = self.messages.max_turn_id() + 1
        append_message(self.messages, Message.user(user_input), turn_id=turn_id)

        async for event in run_event_loop(
            self,
            user_input=user_input,
            turn_id=turn_id,
            **run_kwargs,
        ):
            if event_handler is not None:
                result = event_handler(event)
                if isawaitable(result):
                    await result

            projected = project_event(event, return_type)
            if projected is None:
                continue
            yield projected
