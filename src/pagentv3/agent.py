from collections.abc import AsyncIterator
from typing import Literal

from .acp_adapter import encode_event_line
from .events import (
    ReasoningDelta,
    RunBegin,
    TextDelta,
    ToolCallBegin,
    ToolResult,
    TurnBegin,
    TurnEnd,
)
from .message import Message, Messages, TextChunk, ThinkingChunk, ToolCall
from .persistence import Persistence
from .provider import Provider
from .tool import FunctionTool, ToolOutput, to_openai_tools
from .turn_result import TurnResult

ArunReturnType = Literal["event", "text", "acp", "message"]


class Agent:
    def __init__(
        self,
        provider: Provider,
        messages: Messages | None = None,
        *,
        conversation_id: str | None = None,
        persistence: Persistence | None = None,
        system: str | None = None,
        tools: list[FunctionTool] | None = None,
        max_turns: int = 8,
    ):
        self.provider = provider
        self.persistence = persistence
        if conversation_id is None and persistence is not None:
            conversation_id = persistence.create_conversation()
        self.conversation_id = conversation_id

        if messages is None and persistence is not None and conversation_id is not None:
            messages = persistence.load_messages(conversation_id)
        self.messages = messages or Messages()
        if system and not any(m.role == "system" for m in self.messages):
            self.add_message(Message.system(system))

        self.tools = tools or []
        self.tool_schemas = to_openai_tools(self.tools) or None
        names = [t.name for t in self.tools]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate tool names: {names}")
        self.tool_map: dict[str, FunctionTool] = {t.name: t for t in self.tools}

        if max_turns < 1:
            raise ValueError("max_turns must be >= 1")
        self.max_turns = max_turns
        self.current_turn_id: int | None = None

    def persist_messages(self) -> None:
        if self.persistence is None or self.conversation_id is None:
            return
        self.persistence.save_messages(self.conversation_id, self.messages)

    def add_message(self, message: Message) -> None:
        if message.turn_id is None and message.role != "system":
            message.turn_id = self.current_turn_id
        self.messages += message
        self.persist_messages()

    def reset(self) -> None:
        self.messages = Messages(
            data=[m for m in self.messages.data if m.role == "system"]
        )
        self.current_turn_id = None
        self.persist_messages()

    async def run_tool_call(self, tool_call: dict) -> ToolOutput:
        function_call = tool_call["function"]
        name = function_call["name"]
        tc = self.tool_map.get(name)
        if tc is None:
            return ToolOutput.fail(
                f"error: unknown tool {name!r}; available: {sorted(self.tool_map)}"
            )
        return await tc.acall(function_call["arguments"])

    async def emit_tool_events(self, tool_calls: list[dict]) -> AsyncIterator:
        for tool_call in tool_calls:
            function_call = tool_call["function"]
            name = function_call["name"]
            arguments = function_call["arguments"]
            if not isinstance(arguments, str):
                arguments = str(arguments)
            yield ToolCallBegin(tool_call["id"], name, arguments)
            output = await self.run_tool_call(tool_call)
            self.add_message(Message.tool_result(tool_call["id"], output.content))
            yield ToolResult(tool_call["id"], name, output.content, ok=output.ok)

    async def stream_messages(self, **run_kwargs) -> AsyncIterator[Message]:
        stream = await self.provider.complete(
            self.messages.to_openai(),
            tools=self.tool_schemas,
            **run_kwargs,
        )
        tool_calls_by_idx: dict[int, dict] = {}

        async for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue

            delta = getattr(choices[0], "delta", None)
            if delta is None:
                continue

            content = getattr(delta, "content", None)
            if content:
                message = Message.assistant({"type": "text", "text": content})
                self.add_message(message)
                yield message

            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                message = Message.assistant({"type": "thinking", "text": reasoning})
                self.add_message(message)
                yield message

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

        for _, tc in sorted(tool_calls_by_idx.items()):
            message = Message(role="assistant", content=ToolCall.from_openai(tc))
            self.add_message(message)
            yield message

    def project_event(self, event, return_type):
        if return_type == "event":
            return event
        if return_type == "text":
            if not isinstance(event, TextDelta):
                return None
            return event.text
        if return_type == "acp":
            return encode_event_line(event)
        if return_type == "message":
            if isinstance(event, TextDelta):
                return Message.assistant({"type": "text", "text": event.text})
            if isinstance(event, ReasoningDelta):
                return Message.assistant({"type": "thinking", "text": event.text})
            if isinstance(event, ToolCallBegin):
                return Message(
                    role="assistant",
                    content=ToolCall(
                        type="function",
                        id=event.tool_call_id,
                        name=event.name,
                        arguments=event.arguments,
                    ),
                )
            if isinstance(event, ToolResult):
                return Message.tool_result(event.tool_call_id, event.content)
            return None
        raise ValueError(f"unknown return_type: {return_type!r}")

    async def arun(
        self,
        user_input: str,
        *,
        return_type: ArunReturnType = "event",
        **run_kwargs,
    ) -> AsyncIterator:
        if return_type not in {"event", "text", "acp", "message"}:
            raise ValueError(f"unknown return_type: {return_type!r}")

        async for event in self.events(user_input, **run_kwargs):
            projected = self.project_event(event, return_type)
            if projected is None:
                continue
            yield projected

    async def events(self, user_input: str, **run_kwargs) -> AsyncIterator:
        self.current_turn_id = self.messages.max_turn_id() + 1
        self.add_message(Message.user(user_input))
        yield RunBegin(user_input)

        for turn in range(self.max_turns):
            yield TurnBegin(turn)
            turn_start = len(self.messages.data)

            async for message in self.stream_messages(**run_kwargs):
                chunk = message.content
                if isinstance(chunk, TextChunk):
                    yield TextDelta(chunk.text)
                elif isinstance(chunk, ThinkingChunk):
                    yield ReasoningDelta(chunk.text)

            result = TurnResult.from_slice(self.messages.data, turn_start)
            yield result

            if turn_start >= len(self.messages.data):
                yield TurnEnd(turn, stopped=True, stop_reason="empty_response")
                return

            if not result.has_tool_calls:
                yield TurnEnd(turn, stopped=True, stop_reason="no_tool_calls")
                return

            async for event in self.emit_tool_events(result.tool_calls):
                yield event

            if turn + 1 >= self.max_turns:
                yield TurnEnd(turn, stopped=True, stop_reason="max_turns")
                return

            yield TurnEnd(turn, stopped=False, stop_reason="continuing")
