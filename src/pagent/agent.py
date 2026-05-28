from collections.abc import AsyncIterator

from .events import (
    ReasoningDelta,
    RunBegin,
    StepEnd,
    TextDelta,
    ToolCallBegin,
    ToolResult,
    TurnBegin,
    TurnEnd,
)
from .llm import RunEnd
from .tool import FunctionTool, ToolOutput, to_openai_tools


class AgentStats:
    def __init__(self):
        self.usage = None
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.turns = 0

    def add_usage(self, usage):
        self.usage = usage
        self.turns += 1
        if usage:
            self.prompt_tokens += usage.prompt_tokens
            self.completion_tokens += usage.completion_tokens
            self.total_tokens += usage.total_tokens

    def __str__(self):
        return (
            f"turns={self.turns}, "
            f"prompt_tokens={self.prompt_tokens}, "
            f"completion_tokens={self.completion_tokens}, "
            f"total_tokens={self.total_tokens}"
        )


class Agent:
    def __init__(self, llm, session, tools=None, max_turns=8):
        self.llm = llm
        self.session = session
        self.tools = tools or []
        self.tool_schemas = to_openai_tools(self.tools)
        names = [t.name for t in self.tools]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate tool names: {names}")
        self.tool_map: dict[str, FunctionTool] = {t.name: t for t in self.tools}
        if max_turns < 1:
            raise ValueError("max_turns must be >= 1")
        self.max_turns = max_turns
        self.stats = AgentStats()

    def _run_tool(self, tool_call) -> ToolOutput:
        function_call = tool_call["function"]
        name = function_call["name"]
        tc = self.tool_map.get(name)
        if tc is None:
            return ToolOutput.fail(
                f"error: unknown tool {name!r}; available: {sorted(self.tool_map)}"
            )
        return tc.call(function_call["arguments"])

    def _execute_tool_calls(self, tool_calls):
        for tool_call in tool_calls:
            output = self._run_tool(tool_call)
            self.session += {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": output.content,
            }

    async def _emit_tool_events(self, tool_calls):
        for tool_call in tool_calls:
            function_call = tool_call["function"]
            name = function_call["name"]
            arguments = function_call["arguments"]
            if not isinstance(arguments, str):
                arguments = str(arguments)
            yield ToolCallBegin(tool_call["id"], name, arguments)
            output = self._run_tool(tool_call)
            self.session += {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": output.content,
            }
            yield ToolResult(tool_call["id"], name, output.content, ok=output.ok)

    def reset(self):
        self.session.reset()
        self.stats = AgentStats()

    def _assistant_message(self, result):
        message = {"role": "assistant", "content": result.content or None}
        if result.tool_calls:
            message["tool_calls"] = result.tool_calls
        if result.reasoning_content:
            message["reasoning_content"] = result.reasoning_content
        return message

    async def _stream_step_events(self, **run_kwargs) -> AsyncIterator:
        content_parts = []
        reasoning_content_parts = []
        tool_calls_by_idx = {}
        usage = None

        async for chunk in self.llm.invoke_stream(
            self.session.messages,
            tools=self.tool_schemas,
            **run_kwargs,
        ):
            usage = getattr(chunk, "usage", usage)
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue

            delta = getattr(choices[0], "delta", None)
            if delta is None:
                continue

            content = getattr(delta, "content", None)
            if content:
                content_parts.append(content)
                yield TextDelta(content)
            reasoning_content = getattr(delta, "reasoning_content", None)
            if reasoning_content:
                reasoning_content_parts.append(reasoning_content)
                yield ReasoningDelta(reasoning_content)

            for tc_delta in getattr(delta, "tool_calls", None) or []:
                idx = getattr(tc_delta, "index", 0)
                tc = tool_calls_by_idx.setdefault(
                    idx,
                    {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    },
                )
                tc_id = getattr(tc_delta, "id", None)
                if tc_id:
                    tc["id"] = tc_id
                tc_type = getattr(tc_delta, "type", None)
                if tc_type:
                    tc["type"] = tc_type

                fn_delta = getattr(tc_delta, "function", None)
                if fn_delta is None:
                    continue

                fn_name = getattr(fn_delta, "name", None)
                if fn_name:
                    tc["function"]["name"] += fn_name
                fn_args = getattr(fn_delta, "arguments", None)
                if fn_args:
                    tc["function"]["arguments"] += fn_args

        tool_calls = [
            tc for _, tc in sorted(tool_calls_by_idx.items(), key=lambda item: item[0])
        ]
        result = RunEnd(
            content="".join(content_parts),
            tool_calls=tool_calls,
            reasoning_content="".join(reasoning_content_parts),
            usage=usage,
        )
        self.session += self._assistant_message(result)
        self.stats.add_usage(result.usage)
        yield StepEnd(
            content=result.content,
            tool_calls=result.tool_calls,
            reasoning_content=result.reasoning_content,
            usage=result.usage,
        )

    async def run(self, user_input, **run_kwargs):
        self.session += {"role": "user", "content": user_input}
        result = RunEnd(content="")

        for _ in range(self.max_turns):
            result = await self.llm.invoke(
                self.session.messages,
                tools=self.tool_schemas,
                **run_kwargs,
            )
            self.session += self._assistant_message(result)
            self.stats.add_usage(result.usage)

            if not result.has_tool_calls:
                return result

            self._execute_tool_calls(result.tool_calls)

        return result

    async def arun_events(self, user_input, **run_kwargs) -> AsyncIterator:
        self.session += {"role": "user", "content": user_input}
        yield RunBegin(user_input)
        last_result = RunEnd(content="")

        for turn in range(self.max_turns):
            yield TurnBegin(turn)
            turn_start = len(self.session.messages)
            step_end = None
            async for event in self._stream_step_events(**run_kwargs):
                yield event
                if isinstance(event, StepEnd):
                    step_end = event

            if step_end is None:
                yield TurnEnd(turn, stopped=True)
                yield last_result
                return

            last_result = RunEnd(
                content=step_end.content,
                tool_calls=step_end.tool_calls,
                reasoning_content=step_end.reasoning_content,
                usage=step_end.usage,
            )

            if turn_start >= len(self.session.messages):
                yield TurnEnd(turn, stopped=True)
                yield last_result
                return

            assistant_message = self.session.messages[turn_start]
            if not assistant_message.get("tool_calls"):
                yield TurnEnd(turn, stopped=True)
                yield last_result
                return

            async for event in self._emit_tool_events(assistant_message["tool_calls"]):
                yield event
            yield TurnEnd(turn, stopped=False)

        yield last_result

    async def arun_wire(self, user_input, **run_kwargs) -> AsyncIterator[str]:
        """Yield NDJSON lines (JSON-RPC 2.0 notifications). See :mod:`pagent.wire`."""
        from .wire import encode_event_line

        async for event in self.arun_events(user_input, **run_kwargs):
            yield encode_event_line(event)

    async def arun(self, user_input, **run_kwargs) -> AsyncIterator[str]:
        async for event in self.arun_events(user_input, **run_kwargs):
            if isinstance(event, TextDelta):
                yield event.text
