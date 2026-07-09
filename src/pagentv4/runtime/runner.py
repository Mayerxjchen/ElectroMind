from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from inspect import isawaitable
from pathlib import Path

from ..conversation import ConversationStore
from ..core.agent import Agent
from ..core.events import RunEnd, ToolCallBegin, ToolResult, TurnEnd
from ..core.message import Message, Messages, ToolCall
from ..core.provider import ProviderProtocol
from ..core.tool import FunctionTool, ToolOutput
from ..sandbox import Sandbox
from ..skills import (
    SkillRegistry,
    build_skills_system_prompt,
    make_use_skill_tool,
)
from .helper import (
    ArunReturnType,
    EventHandler,
    append_message,
    ensure_system,
    message_to_event,
    project_event,
)
from .hooks import PostToolHookContext, ToolHookContext, ToolHooks
from .inbound import (
    CancelRun,
    CheckpointPolicy,
    DenyTool,
    InboundMailbox,
    PermitTool,
    RunCancelled,
    ToolPermitResult,
)
from .loop_core import run_event_loop
from .thread import Thread


class Runner:
    """Run 调度器，与 thread 同生共死。

    `await Runner.create(...)` → 多次 `runner.run(user_input)` → `await runner.close()`
    """

    def __init__(
        self,
        *,
        thread: Thread,
        sandbox: Sandbox,
        store: ConversationStore,
        messages: Messages,
        agent: Agent,
        skills: SkillRegistry,
        conversation_id: str,
        inbound: InboundMailbox | None = None,
        checkpoint_policy: CheckpointPolicy | None = None,
        tool_hooks: ToolHooks | None = None,
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
        self.tool_hooks = tool_hooks

    def steer(self, text: str) -> None:
        self.inbound.steer(text)

    def cancel_run(self) -> None:
        self.inbound.cancel()

    def permit_tool(self, tool_call_id: str) -> None:
        self.inbound.permit(tool_call_id)

    def deny_tool(self, tool_call_id: str, *, reason: str = "") -> None:
        self.inbound.deny(tool_call_id, reason=reason)

    async def wait_tool_permit(self, tool_call_id: str) -> ToolPermitResult:
        """阻塞直到入站 ``PermitTool`` / ``DenyTool`` / ``CancelRun``。"""
        deferred: list[object] = []
        try:
            while True:
                event = await self.inbound.wait()
                resolved = self._resolve_tool_permit(event, tool_call_id)
                if resolved is not None:
                    return resolved
                deferred.append(event)
        finally:
            for event in deferred:
                self.inbound.push(event)

    @staticmethod
    def _resolve_tool_permit(
        event: object, tool_call_id: str
    ) -> ToolPermitResult | None:
        if isinstance(event, PermitTool):
            if event.tool_call_id == tool_call_id:
                return ToolPermitResult(approved=True)
            return None
        if isinstance(event, DenyTool):
            if event.tool_call_id == tool_call_id:
                return ToolPermitResult(approved=False, reason=event.reason)
            return None
        if isinstance(event, CancelRun):
            return ToolPermitResult(
                approved=False,
                reason="run cancelled by user",
            )
        return None

    def _apply_inbound_drain(
        self, outbound_event: object, *, turn_id: int, turn: int
    ) -> None:
        drain = self.inbound.drain_for_checkpoint(
            outbound_event, self.checkpoint_policy
        )
        if drain is None:
            return
        for text in drain.steers:
            append_message(self.messages, Message.user(text), turn_id=turn_id)
        if drain.cancelled:
            raise RunCancelled(turn)

    async def emit(
        self,
        event,
        *,
        turn_id: int,
        turn: int,
    ) -> AsyncIterator:
        yield event
        self._apply_inbound_drain(event, turn_id=turn_id, turn=turn)

    async def close(self) -> None:
        close_store = getattr(self.store, "close", None)
        if callable(close_store):
            close_store()
        await self.sandbox.close()

    async def execute_tool(
        self,
        tool_call: ToolCall,
    ) -> ToolOutput:
        name = tool_call.name
        tool: FunctionTool | None = self.agent.tool_map.get(name)
        if tool is None:
            return ToolOutput.fail(
                f"error: unknown tool {name!r}; available: {sorted(self.agent.tool_map)}"
            )
        return await tool.acall(tool_call.arguments)

    async def emit_tool_events(
        self,
        tool_calls: list[ToolCall],
        turn_id: int,
        turn: int,
    ) -> AsyncIterator:
        del turn
        for tool_call in tool_calls:
            name = tool_call.name
            arguments = tool_call.arguments
            if not isinstance(arguments, str):
                arguments = str(arguments)
            yield ToolCallBegin(tool_call.id, name, arguments)

            ctx = ToolHookContext(
                self,
                tool_call.id,
                name,
                arguments,
                turn_id,
            )
            output = await self.run_tool_with_hooks(ctx, tool_call)

            append_message(
                self.messages,
                Message.tool_result(tool_call.id, output.content),
                turn_id=turn_id,
            )
            yield ToolResult(tool_call.id, name, output.content, ok=output.ok)

    async def run_tool_with_hooks(
        self,
        ctx: ToolHookContext,
        tool_call: ToolCall,
    ) -> ToolOutput:
        if self.tool_hooks is not None:
            decision = await self.tool_hooks.run_before(ctx)
            if decision is not None:
                return ToolOutput(
                    content=decision.content or "",
                    ok=decision.ok,
                )

        output = await self.execute_tool(tool_call)

        if self.tool_hooks is None:
            return output

        post_ctx = PostToolHookContext(
            ctx.runner,
            ctx.tool_call_id,
            ctx.name,
            ctx.arguments,
            ctx.turn_id,
            output,
        )
        return await self.tool_hooks.run_after(post_ctx, output)

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

    def flush_conversation(self) -> None:
        self.store.save(self.conversation_id, self.messages)

    async def after_continuing(self, *, turn: int) -> None:
        del turn
        self.flush_conversation()

    async def after_run_end(self, *, turn: int) -> None:
        del turn
        self.flush_conversation()

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
            async for event in run_event_loop(
                self,
                user_input=user_input,
                turn_id=turn_id,
                **run_kwargs,
            ):
                yield event
        except RunCancelled as exc:
            yield TurnEnd(exc.turn, stopped=True, stop_reason="cancelled")
            yield RunEnd(exc.turn, stop_reason="cancelled")
            self.flush_conversation()

    @classmethod
    async def create(
        cls,
        thread_id: str,
        provider: ProviderProtocol,
        *,
        overrides: dict | None = None,
        extra_system: str = "",
        max_turns: int = 8,
        skill_roots: Sequence[str | Path] = (),
        tools: Sequence[FunctionTool] = (),
        tool_hooks: ToolHooks | None = None,
    ) -> Runner:
        """创建完整 Runner：打开 thread、sandbox、conversation 和 skills。"""
        thread = Thread.open(thread_id, overrides=overrides)
        sandbox = await thread.open_sandbox()
        store = thread.open_store()

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

        conversation_id = thread.messages_conversation_id
        messages = thread.load_messages()

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
            tool_hooks=tool_hooks,
        )

    @classmethod
    async def open(
        cls,
        thread_id: str,
        provider: ProviderProtocol,
        *,
        overrides: dict | None = None,
        extra_system: str = "",
        max_turns: int = 8,
        skill_roots: Sequence[str | Path] = (),
        tools: Sequence[FunctionTool] = (),
        tool_hooks: ToolHooks | None = None,
    ) -> Runner:
        """兼容旧入口；新代码优先使用 `Runner.create(...)`。"""
        return await cls.create(
            thread_id,
            provider,
            overrides=overrides,
            extra_system=extra_system,
            max_turns=max_turns,
            skill_roots=skill_roots,
            tools=tools,
            tool_hooks=tool_hooks,
        )
