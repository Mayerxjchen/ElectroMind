"""``LiveAgent`` = :class:`pagent.agent.Agent` + :class:`~pagent_live.bus.DuplexBus`."""

import asyncio
import inspect
from collections.abc import AsyncIterator

from pagent.agent import Agent
from pagent.events import ToolCallBegin, ToolResult
from pagent.tool import ToolOutput

from .bus import DuplexBus
from .context import end_run, poll_iwire, publish_owire, reset_live
from .tooling import call_with_context, call_with_context_async


class LiveAgent(Agent):
    def __init__(self, llm, session, tools=None, max_turns=8):
        super().__init__(llm, session, tools, max_turns)
        self.bus = DuplexBus()

    def _run_tool(self, tool_call) -> ToolOutput:
        function_call = tool_call["function"]
        tc = self.tool_map.get(function_call["name"])
        if tc is None:
            return ToolOutput.fail(
                f"error: unknown tool {function_call['name']!r}; "
                f"available: {sorted(self.tool_map)}"
            )
        return call_with_context(tc, function_call["arguments"], self, tool_call["id"])

    async def _invoke_tool(self, tool_call) -> ToolOutput:
        function_call = tool_call["function"]
        tc = self.tool_map.get(function_call["name"])
        if tc is None:
            return ToolOutput.fail(
                f"error: unknown tool {function_call['name']!r}; "
                f"available: {sorted(self.tool_map)}"
            )
        if inspect.iscoroutinefunction(tc.func):
            return await call_with_context_async(
                tc, function_call["arguments"], self, tool_call["id"]
            )
        return call_with_context(tc, function_call["arguments"], self, tool_call["id"])

    async def _emit_tool_events(self, tool_calls):
        for tool_call in tool_calls:
            function_call = tool_call["function"]
            name = function_call["name"]
            arguments = function_call["arguments"]
            if not isinstance(arguments, str):
                arguments = str(arguments)

            yield ToolCallBegin(tool_call["id"], name, arguments)

            task = asyncio.create_task(self._invoke_tool(tool_call))
            while not task.done():
                poll_iwire(self.bus)
                await asyncio.sleep(0.01)
            output = await task

            self.session += {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": output.content,
            }
            yield ToolResult(tool_call["id"], name, output.content, ok=output.ok)

    async def arun_events(self, user_input, **run_kwargs) -> AsyncIterator:
        reset_live(self.bus)
        try:
            async for event in super().arun_events(user_input, **run_kwargs):
                publish_owire(self.bus, event)
                yield event
        finally:
            end_run(self.bus)

    async def arun_wire(self, user_input, **run_kwargs) -> AsyncIterator[str]:
        from pagent.wire import encode_event_line

        async for event in self.arun_events(user_input, **run_kwargs):
            yield encode_event_line(event)
