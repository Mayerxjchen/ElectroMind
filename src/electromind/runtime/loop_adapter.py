"""LoopAdapter —— runner 共享的事件循环骨架。

VanillaRunner / BaseRunner / Runner 三个 runner 共享同一套循环骨架
(`execute_tool` / `stream_agent_events` / `emit` / `emit_tool_events` /
`run` / `after_*`)；它们的真差异只有四个正交能力开关：inbound、tool hooks、
持久化、sandbox。

LoopAdapter 承载这套骨架的默认实现，每个 runner 只覆写自己的差异点：

- `VanillaRunner(LoopAdapter)`：纯内存，`after_*` 用默认 no-op。
- `BaseRunner(LoopAdapter)`：加 thread/store/sandbox，`after_*` 覆写为 flush。
- `Runner(BaseRunner)`：加 inbound + tool hooks，覆写 `emit` / `emit_tool_events`
  / `_event_source`（cancel 处理）。

`run` 只在此写一次；需要改造事件源（如 Runner 的 cancel 捕获）的子类覆写
`_event_source`，而不必复制 `run` 主体。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from inspect import isawaitable

from ..core.agent import Agent
from ..core.events import ToolCallBegin, ToolResult
from ..core.message import Message, Messages, ToolCall
from ..core.tool import FunctionTool, ToolOutput
from .frame import RunFrame
from .helper import (
    ArunReturnType,
    EventHandler,
    append_message,
    ensure_system,
    message_to_event,
    project_event,
)
from .loop_core import run_event_loop
from .run_state import RunState


class LoopAdapter:
    """Runner 共享的事件循环骨架；满足 `loop_core.LoopCoreAdapter` 协议。

    运行上下文放在帧栈 ``self.frames`` 上，当前上下文永远是栈顶帧。``agent`` /
    ``messages`` / ``run_state`` / ``sandbox`` / ``store`` / ``skills`` /
    ``conversation_id`` 都是栈顶帧的字段，通过 property 读写——循环骨架照旧用
    ``self.agent`` 就够了，委派子 agent 时压帧换栈顶即可切换整套上下文。

    子类按需覆写 `emit` / `emit_tool_events` / `after_*` / `_event_source` 来叠加
    inbound、hooks、持久化等能力。
    """

    def __init__(self, agent: Agent, messages: Messages | None = None) -> None:
        base = RunFrame(
            agent=agent,
            messages=messages if messages is not None else Messages(),
        )
        self.frames: list[RunFrame] = [base]

    @property
    def frame(self) -> RunFrame:
        return self.frames[-1]

    @property
    def agent(self) -> Agent:
        return self.frame.agent

    @agent.setter
    def agent(self, value: Agent) -> None:
        self.frame.agent = value

    @property
    def messages(self) -> Messages:
        return self.frame.messages

    @messages.setter
    def messages(self, value: Messages) -> None:
        self.frame.messages = value

    @property
    def run_state(self) -> RunState:
        return self.frame.run_state

    @run_state.setter
    def run_state(self, value: RunState) -> None:
        self.frame.run_state = value

    @property
    def conversation_id(self) -> str | None:
        return self.frame.conversation_id

    @conversation_id.setter
    def conversation_id(self, value: str | None) -> None:
        self.frame.conversation_id = value

    @property
    def sandbox(self):
        return self.frame.sandbox

    @sandbox.setter
    def sandbox(self, value) -> None:
        self.frame.sandbox = value

    @property
    def store(self):
        return self.frame.store

    @store.setter
    def store(self, value) -> None:
        self.frame.store = value

    @property
    def skills(self):
        return self.frame.skills

    @skills.setter
    def skills(self, value) -> None:
        self.frame.skills = value

    def push_frame(self, frame: RunFrame) -> RunFrame:
        """压入一帧并切换当前上下文到它；返回该帧。"""
        self.frames.append(frame)
        return frame

    async def pop_frame(self) -> RunFrame:
        """弹出栈顶帧并释放它拥有的资源；返回被弹出的帧。

        栈底基帧不弹（那是 runner 自身的主上下文，由 ``close`` 收尾）。
        """
        if len(self.frames) <= 1:
            raise RuntimeError("cannot pop the base frame")
        frame = self.frames.pop()
        await frame.release()
        return frame

    async def execute_tool(self, tool_call: ToolCall) -> ToolOutput:
        name = tool_call.name
        tool: FunctionTool | None = self.agent.tool_map.get(name)
        if tool is None:
            return ToolOutput.fail(
                f"error: unknown tool {name!r}; available: {sorted(self.agent.tool_map)}"
            )
        return await tool.acall(tool_call.arguments, context=self.tool_context())

    def tool_context(self):
        """注入给声明了 `context` 形参的工具的运行上下文；默认是 runner 自身。

        delegate 之类需要压栈起子 agent 的工具靠它拿到 runner 与资源栈。
        """
        return self

    async def emit(self, event, *, turn_id: int, turn: int) -> AsyncGenerator:
        del turn_id, turn
        yield event

    async def stream_agent_events(
        self,
        turn_id: int,
        **run_kwargs,
    ) -> AsyncGenerator:
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
    ) -> AsyncGenerator:
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

    async def before_user_turn(self, user_input: str) -> None:
        """Hook called before appending the user message and running the agent.

        Subclasses (e.g. ``BaseRunner``) override this to refresh Skills
        or other per-turn resources.
        """
        del user_input

    async def after_continuing(self, *, turn: int) -> None:
        del turn

    async def after_run_end(self, *, turn: int) -> None:
        del turn

    async def _event_source(
        self,
        user_input: str,
        turn_id: int,
        **run_kwargs,
    ) -> AsyncGenerator:
        async for event in run_event_loop(
            self,
            user_input=user_input,
            turn_id=turn_id,
            **run_kwargs,
        ):
            yield event

    async def run(
        self,
        user_input: str,
        *,
        return_type: ArunReturnType = "event",
        event_handler: EventHandler | None = None,
        **run_kwargs,
    ) -> AsyncGenerator:
        if return_type not in {"event", "text", "acp", "message"}:
            raise ValueError(f"unknown return_type: {return_type!r}")

        self.run_state = RunState(phase="initializing")
        await self.before_user_turn(user_input)
        ensure_system(self.messages, self.agent.system)
        turn_id = self.messages.max_turn_id() + 1
        self.run_state.turn_id = turn_id
        append_message(self.messages, Message.user(user_input), turn_id=turn_id)
        await asyncio.sleep(0)

        async for event in self._event_source(user_input, turn_id, **run_kwargs):
            if event_handler is not None:
                result = event_handler(event)
                if isawaitable(result):
                    await result

            projected = project_event(event, return_type)
            if projected is None:
                continue
            yield projected
