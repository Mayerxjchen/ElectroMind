from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from inspect import isawaitable
from pathlib import Path
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
from ..sandbox import Sandbox, SshConnection
from ..skills import (
    SkillRegistry,
    build_skills_system_prompt,
    make_use_skill_tool,
)
from .conversation import JsonlConversationStore
from .inbound import CheckpointPolicy, InboundMailbox, RunCancelled
from .thread import Thread

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
    """Run 调度器，与 thread 同生共死。

    `await Runner.open(...)` → 多次 `runner.run(user_input)` → `await runner.close()`
    """

    def __init__(
        self,
        *,
        thread: Thread,
        sandbox: Sandbox,
        store: JsonlConversationStore,
        messages: Messages,
        agent: Agent,
        skills: SkillRegistry,
        conversation_id: str,
        inbound: InboundMailbox | None = None,
        checkpoint_policy: CheckpointPolicy | None = None,
    ):
        self.thread = thread
        self.sandbox = sandbox
        self.store = store
        self.messages = messages
        self.agent = agent
        self.skills = skills
        self.conversation_id = conversation_id
        self.inbound = inbound or InboundMailbox()
        self.checkpoint_policy = checkpoint_policy or CheckpointPolicy()

    def steer(self, text: str) -> None:
        self.inbound.steer(text)

    def cancel_run(self) -> None:
        self.inbound.cancel()

    def _apply_inbound_drain(
        self, outbound_event: object, *, turn_id: int, turn: int
    ) -> None:
        drain = self.inbound.drain_if_policy(
            outbound_event, self.checkpoint_policy
        )
        if drain is None:
            return
        for text in drain.steers:
            append_message(self.messages, Message.user(text), turn_id=turn_id)
        if drain.cancelled:
            raise RunCancelled(turn)

    async def _emit(
        self,
        event,
        *,
        turn_id: int,
        turn: int,
    ) -> AsyncIterator:
        yield event
        self._apply_inbound_drain(event, turn_id=turn_id, turn=turn)

    async def close(self) -> None:
        await self.sandbox.close()

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
                self.messages,
                Message.tool_result(tool_call["id"], output.content),
                turn_id=turn_id,
            )
            yield ToolResult(tool_call["id"], name, output.content, ok=output.ok)

    async def stream_agent_messages(
        self,
        turn_id: int,
        **run_kwargs,
    ) -> AsyncIterator:
        async for message in self.agent.stream_messages(self.messages, **run_kwargs):
            append_message(self.messages, message, turn_id=turn_id)
            event = message_to_event(message)
            if event is not None:
                yield event

    def flush_conversation(self) -> None:
        self.store.save(self.conversation_id, self.messages)

    async def run(
        self,
        user_input: str,
        *,
        return_type: ArunReturnType = "event",
        event_handler: EventHandler | None = None,
        **run_kwargs,
    ) -> AsyncIterator:
        if return_type not in {"event", "text", "acp", "message"}:
            raise ValueError(f"unknown return_type: {return_type!r}")

        ensure_system(self.messages, self.agent.system)
        turn_id = self.messages.max_turn_id() + 1
        append_message(self.messages, Message.user(user_input), turn_id=turn_id)

        async for event in self._events(user_input, turn_id, **run_kwargs):
            if event_handler is not None:
                result = event_handler(event)
                if isawaitable(result):
                    await result

            projected = project_event(event, return_type)
            if projected is None:
                continue
            yield projected

    async def _events(
        self, user_input: str, turn_id: int, **run_kwargs
    ) -> AsyncIterator:
        try:
            async for event in self._event_loop(user_input, turn_id, **run_kwargs):
                yield event
        except RunCancelled as exc:
            yield TurnEnd(exc.turn, stopped=True, stop_reason="cancelled")
            self.flush_conversation()

    async def _event_loop(
        self, user_input: str, turn_id: int, **run_kwargs
    ) -> AsyncIterator:
        async for event in self._emit(RunBegin(user_input), turn_id=turn_id, turn=0):
            yield event

        for turn in range(self.agent.max_turns):
            async for event in self._emit(TurnBegin(turn), turn_id=turn_id, turn=turn):
                yield event
            turn_start = len(self.messages.data)

            async for event in self.stream_agent_messages(turn_id, **run_kwargs):
                async for out in self._emit(event, turn_id=turn_id, turn=turn):
                    yield out

            result = TurnResult.from_slice(self.messages.data, turn_start)
            async for event in self._emit(result, turn_id=turn_id, turn=turn):
                yield event

            if turn_start >= len(self.messages.data):
                async for event in self._emit(
                    TurnEnd(turn, stopped=True, stop_reason="empty_response"),
                    turn_id=turn_id,
                    turn=turn,
                ):
                    yield event
                self.flush_conversation()
                return

            if not result.has_tool_calls:
                async for event in self._emit(
                    TurnEnd(turn, stopped=True, stop_reason="no_tool_calls"),
                    turn_id=turn_id,
                    turn=turn,
                ):
                    yield event
                self.flush_conversation()
                return

            async for event in self.emit_tool_events(
                result.tool_calls, self.agent.tool_map, turn_id
            ):
                async for out in self._emit(event, turn_id=turn_id, turn=turn):
                    yield out

            if turn + 1 >= self.agent.max_turns:
                async for event in self._emit(
                    TurnEnd(turn, stopped=True, stop_reason="max_turns"),
                    turn_id=turn_id,
                    turn=turn,
                ):
                    yield event
                self.flush_conversation()
                return

            async for event in self._emit(
                TurnEnd(turn, stopped=False, stop_reason="continuing"),
                turn_id=turn_id,
                turn=turn,
            ):
                yield event
            self.flush_conversation()

    @classmethod
    async def open(
        cls,
        thread_id: str,
        provider: Provider,
        *,
        overrides: dict | None = None,
        extra_system: str = "",
        max_turns: int = 8,
        skill_roots: Sequence[str | Path] = (),
        tools: Sequence[FunctionTool] = (),
    ) -> Runner:
        thread = Thread.open(thread_id, overrides=overrides)
        sandbox = await cls._open_sandbox(thread)
        store = JsonlConversationStore(root=thread.root)

        skills = SkillRegistry.from_defaults(*skill_roots)
        mount = await sandbox.install_skills(skills) if skills.names() else {}
        combined_tools = [*sandbox.tools(), *tools]
        if skills.names():
            combined_tools.append(make_use_skill_tool(skills, mount))

        system_tail = thread.spec.system or extra_system
        computer_desc = await sandbox.describe()
        skills_prompt = build_skills_system_prompt(skills, mount)
        system_prompt = "\n".join(
            part for part in (computer_desc, skills_prompt, system_tail) if part
        )

        messages = Messages()
        conversation_id = thread.messages_conversation_id
        for message in store.load(conversation_id).data:
            messages += message

        return cls(
            thread=thread,
            sandbox=sandbox,
            store=store,
            messages=messages,
            agent=Agent(
                provider,
                system=system_prompt,
                tools=combined_tools,
                max_turns=max_turns,
            ),
            skills=skills,
            conversation_id=conversation_id,
        )

    @staticmethod
    async def _open_sandbox(thread: Thread) -> Sandbox:
        spec = thread.spec
        workdir = str(thread.workspace_path)

        if spec.backend == "local":
            return await Sandbox.create(
                backend="local",
                workdir=workdir,
                command_policy=spec.command_policy,
            )

        if spec.backend in ("docker", "podman"):
            if not spec.image:
                raise ValueError(
                    f"thread {thread.id!r}: backend {spec.backend!r} requires image"
                )
            return await Sandbox.create(
                backend=spec.backend,
                workdir=workdir,
                image=spec.image,
                container_ttl_seconds=spec.container_ttl_seconds,
                command_policy=spec.command_policy,
            )

        if not spec.ssh_host:
            raise ValueError(
                f"thread {thread.id!r}: backend 'ssh' requires ssh_host in thread spec"
            )
        conn = SshConnection.from_ssh_config(
            spec.ssh_host,
            config_path=spec.ssh_config,
            workdir=spec.ssh_workdir,
        )
        return await Sandbox.create(
            backend="ssh",
            workdir=workdir,
            connection=conn.to_dict(),
            command_policy=spec.command_policy,
        )
