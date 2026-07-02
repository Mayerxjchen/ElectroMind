from collections.abc import AsyncIterator, Awaitable, Callable
from inspect import isawaitable
from typing import Any, Literal

from ..adapters.acp import encode_event_line
from ..core.agent import Agent
from ..core.events import (
    ReasoningDelta,
    RunBegin,
    TextDelta,
    ToolCallBegin,
    ToolResult,
    TurnBegin,
    TurnEnd,
)
from ..core.message import Message, Messages, TextChunk, ThinkingChunk, ToolCall
from ..core.provider import Provider
from ..core.tool import FunctionTool, ToolOutput
from ..core.turn_result import TurnResult
from ..sandbox import Sandbox, SandboxLimits
from .conversation import ConversationStore

ArunReturnType = Literal["event", "text", "acp", "message"]

EventHandler = Callable[[Any], Awaitable[None] | None]


def append_message(messages: Messages, message: Message, turn_id: int | None) -> None:
    if message.turn_id is None and message.role != "system":
        message.turn_id = turn_id
    messages += message


def ensure_system(messages: Messages, system: str | None) -> None:
    if system is None:
        return
    if any(message.role == "system" for message in messages):
        return
    append_message(messages, Message.system(system), turn_id=0)


def message_to_event(message: Message):
    chunk = message.content
    if isinstance(chunk, TextChunk):
        return TextDelta(chunk.text)
    if isinstance(chunk, ThinkingChunk):
        return ReasoningDelta(chunk.text)
    return None


def project_event(event, return_type: ArunReturnType):
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


class Runner:
    def __init__(self, store: ConversationStore | None = None):
        self.store = store

    async def execute_tool(
        self,
        tool_call: dict,
        tool_map: dict[str, FunctionTool],
    ) -> ToolOutput:
        function_call = tool_call["function"]
        name = function_call["name"]
        tool = tool_map.get(name)
        if tool is None:
            return ToolOutput.fail(
                f"error: unknown tool {name!r}; available: {sorted(tool_map)}"
            )
        return await tool.acall(function_call["arguments"])

    async def emit_tool_events(
        self,
        tool_calls: list[dict],
        tool_map: dict[str, FunctionTool],
        messages: Messages,
        turn_id: int,
    ) -> AsyncIterator:
        for tool_call in tool_calls:
            function_call = tool_call["function"]
            name = function_call["name"]
            arguments = function_call["arguments"]
            if not isinstance(arguments, str):
                arguments = str(arguments)
            yield ToolCallBegin(tool_call["id"], name, arguments)
            output = await self.execute_tool(tool_call, tool_map)
            append_message(
                messages,
                Message.tool_result(tool_call["id"], output.content),
                turn_id=turn_id,
            )
            yield ToolResult(tool_call["id"], name, output.content, ok=output.ok)

    async def stream_agent_messages(
        self,
        agent: Agent,
        messages: Messages,
        turn_id: int,
        **run_kwargs,
    ) -> AsyncIterator:
        async for message in agent.stream_messages(messages, **run_kwargs):
            append_message(messages, message, turn_id=turn_id)
            event = message_to_event(message)
            if event is not None:
                yield event

    async def arun(
        self,
        agent: Agent,
        user_input: str,
        messages: Messages,
        *,
        return_type: ArunReturnType = "event",
        event_handler: EventHandler | None = None,
        conversation_id: str | None = None,
        **run_kwargs,
    ) -> AsyncIterator:
        if return_type not in {"event", "text", "acp", "message"}:
            raise ValueError(f"unknown return_type: {return_type!r}")

        async for event in self.events(
            agent,
            user_input,
            messages,
            conversation_id=conversation_id,
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

    def load_conversation(
        self, conversation_id: str | None, messages: Messages
    ) -> None:
        if conversation_id is None or self.store is None:
            return
        if messages.data:
            return
        loaded = self.store.load(conversation_id)
        for message in loaded.data:
            messages += message

    def flush_conversation(
        self, conversation_id: str | None, messages: Messages
    ) -> None:
        if conversation_id is None or self.store is None:
            return
        self.store.save(conversation_id, messages)

    async def events(
        self,
        agent: Agent,
        user_input: str,
        messages: Messages,
        *,
        conversation_id: str | None = None,
        **run_kwargs,
    ) -> AsyncIterator:
        if conversation_id is not None and self.store is None:
            raise ValueError(
                "conversation_id was given but Runner has no store; "
                "construct Runner(store=JsonlConversationStore())"
            )

        self.load_conversation(conversation_id, messages)
        ensure_system(messages, agent.system)
        turn_id = messages.max_turn_id() + 1
        append_message(messages, Message.user(user_input), turn_id=turn_id)
        yield RunBegin(user_input)

        for turn in range(agent.max_turns):
            yield TurnBegin(turn)
            turn_start = len(messages.data)

            async for event in self.stream_agent_messages(
                agent, messages, turn_id, **run_kwargs
            ):
                yield event

            result = TurnResult.from_slice(messages.data, turn_start)
            yield result

            if turn_start >= len(messages.data):
                yield TurnEnd(turn, stopped=True, stop_reason="empty_response")
                self.flush_conversation(conversation_id, messages)
                return

            if not result.has_tool_calls:
                yield TurnEnd(turn, stopped=True, stop_reason="no_tool_calls")
                self.flush_conversation(conversation_id, messages)
                return

            async for event in self.emit_tool_events(
                result.tool_calls, agent.tool_map, messages, turn_id
            ):
                yield event

            if turn + 1 >= agent.max_turns:
                yield TurnEnd(turn, stopped=True, stop_reason="max_turns")
                self.flush_conversation(conversation_id, messages)
                return

            yield TurnEnd(turn, stopped=False, stop_reason="continuing")
            self.flush_conversation(conversation_id, messages)

    async def session(
        self,
        provider: Provider,
        user_input: str,
        *,
        system: str | None = None,
        tools: list[FunctionTool] | None = None,
        max_turns: int = 8,
        backend: str = "local",
        workspace_id: str | None = None,
        workdir: str | None = None,
        home: str = "/home/agent",
        image: str | None = None,
        env: dict[str, str] | None = None,
        connection: dict[str, str] | None = None,
        default_limits: SandboxLimits | None = None,
        messages: Messages | None = None,
        return_type: ArunReturnType = "event",
        event_handler: EventHandler | None = None,
        conversation_id: str | None = None,
        **run_kwargs,
    ) -> AsyncIterator:
        """一次新的 run：造 sandbox → 造 agent → 绑工具 → 跑 → 关 sandbox。

        流程与 pagentv4 顶层设计一致：
        1. 从 backend / workspace 参数造 Sandbox 电脑（伴身电脑）
        2. 从电脑里拿工具，与用户传入的 tools 合并
        3. 用 provider + system + 合并工具造 Agent
        4. 走标准 arun，事件按 return_type 投影后 yield 给上层
        5. 迭代结束（正常或异常）都 close sandbox
        """
        sandbox = await Sandbox.create(
            backend=backend,
            workspace_id=workspace_id,
            workdir=workdir,
            home=home,
            image=image,
            env=env,
            connection=connection,
            default_limits=default_limits,
        )
        try:
            combined_tools = [*sandbox.tools(), *(tools or [])]
            agent = Agent(
                provider,
                system=system,
                tools=combined_tools,
                max_turns=max_turns,
            )
            async for item in self.arun(
                agent,
                user_input,
                messages if messages is not None else Messages(),
                return_type=return_type,
                event_handler=event_handler,
                conversation_id=conversation_id,
                **run_kwargs,
            ):
                yield item
        finally:
            await sandbox.close()


async def run_agent(
    agent: Agent,
    user_input: str,
    *,
    return_type: ArunReturnType = "event",
    event_handler: EventHandler | None = None,
    **run_kwargs,
) -> AsyncIterator:
    async for item in Runner().arun(
        agent,
        user_input,
        Messages(),
        return_type=return_type,
        event_handler=event_handler,
        **run_kwargs,
    ):
        yield item
