"""Runner —— 带 inbound 控制面 + tool hooks 的完整 Agent Runner。

继承 `BaseRunner`（从而继承 `LoopAdapter` 的循环骨架与持久化），叠加两个
能力：

- **inbound 控制面**：steer / cancel / permit / deny；在 `emit` 的每个检查点
  drain 邮箱，在 `_event_source` 里捕获 `RunCancelled`。
- **tool hooks**：`emit_tool_events` 走 `run_tool_with_hooks`（before/after）。

`Runner` 与 thread 同生共死：`await Runner.create(...)` → 多次
`runner.run(user_input)` → `await runner.close()`。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from pathlib import Path

from ..conversation import ConversationStore
from ..core.agent import Agent
from ..core.events import RunEnd, ToolCallBegin, ToolResult, TurnEnd
from ..core.message import Message, Messages, ToolCall
from ..core.provider import ProviderProtocol
from ..core.tool import FunctionTool, ToolOutput
from ..sandbox import Sandbox
from ..skills import SkillRegistry
from ..skills.runtime import SkillRuntime
from .base_runner import BaseRunner, assemble_run_resources
from .helper import append_message
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
from .run_state import RunState
from .thread import Thread


class Runner(BaseRunner):
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
        skill_runtime: SkillRuntime | None = None,
    ):
        super().__init__(
            agent,
            thread,
            store=store,
            messages=messages,
            sandbox=sandbox,
            skills=skills,
            skill_runtime=skill_runtime,
        )
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
    ) -> AsyncGenerator:
        yield event
        self._apply_inbound_drain(event, turn_id=turn_id, turn=turn)

    async def emit_tool_events(
        self,
        tool_calls: list[ToolCall],
        turn_id: int,
        turn: int,
    ) -> AsyncGenerator:
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

    async def _event_source(
        self,
        user_input: str,
        turn_id: int,
        **run_kwargs,
    ) -> AsyncGenerator:
        try:
            async for event in run_event_loop(
                self,
                user_input=user_input,
                turn_id=turn_id,
                **run_kwargs,
            ):
                yield event
        except RunCancelled as exc:
            self.run_state.turn = exc.turn
            self.run_state.stop_reason = "cancelled"
            self.run_state.phase = "ended"
            yield TurnEnd(exc.turn, stopped=True, stop_reason="cancelled")
            yield RunEnd(exc.turn, stop_reason="cancelled")
            self.run_state.phase = "tearing_down"
            self.messages.complete_orphan_tool_results(text="已取消：任务被中断")
            self.flush_conversation()
            self.run_state.phase = "ended"

    @classmethod
    async def create(
        cls,
        thread_id: str,
        provider: ProviderProtocol,
        *,
        overrides: dict | None = None,
        extra_system: str = "",
        max_turns: int = 24,
        skill_roots: Sequence[str | Path] = (),
        tools: Sequence[FunctionTool] = (),
        tool_hooks: ToolHooks | None = None,
    ) -> Runner:
        """创建完整 Runner：打开 thread、sandbox、conversation 和 skills。"""
        thread = Thread.open(thread_id, overrides=overrides)
        run_state = RunState(phase="waking_sandbox")
        resources = await assemble_run_resources(
            thread,
            skill_roots=skill_roots,
            tools=tools,
            extra_system=extra_system,
            run_state=run_state,
        )
        store = thread.open_store()
        conversation_id = thread.messages_conversation_id
        messages = thread.load_messages()

        skill_runtime = SkillRuntime(
            thread.spec.project_path,
            configured_roots=tuple(thread.spec.skills) + tuple(skill_roots),
        )

        runner = cls(
            thread=thread,
            sandbox=resources.sandbox,
            store=store,
            messages=messages,
            agent=Agent(
                provider,
                system=resources.system_prompt,
                tools=resources.tools,
                max_turns=max_turns,
            ),
            skills=resources.skills,
            conversation_id=conversation_id,
            tool_hooks=tool_hooks,
            skill_runtime=skill_runtime,
        )
        runner.run_state = run_state
        return runner
