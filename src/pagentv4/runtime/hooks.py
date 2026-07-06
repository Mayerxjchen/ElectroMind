"""工具执行前后 Hook —— Runner 在 ``emit_tool_events`` 内调用。"""

from __future__ import annotations

from dataclasses import dataclass, field
from inspect import isawaitable
from typing import TYPE_CHECKING, Awaitable, Callable

from ..core.tool import ToolOutput

if TYPE_CHECKING:
    from .runner import Runner

BeforeToolHook = Callable[
    ["ToolHookContext"],
    "ToolDecision | None | Awaitable[ToolDecision | None]",
]
AfterToolHook = Callable[
    ["PostToolHookContext"],
    "ToolOutput | None | Awaitable[ToolOutput | None]",
]


@dataclass(frozen=True, slots=True)
class ToolDecision:
    """``before_tool`` 返回值。"""

    execute: bool = True
    content: str | None = None
    ok: bool = True

    @staticmethod
    def allow() -> ToolDecision:
        return ToolDecision()

    @staticmethod
    def deny(message: str) -> ToolDecision:
        return ToolDecision(execute=False, content=message, ok=False)

    @staticmethod
    def replace(content: str, *, ok: bool = True) -> ToolDecision:
        return ToolDecision(execute=False, content=content, ok=ok)


@dataclass(slots=True)
class ToolHookContext:
    runner: Runner
    tool_call_id: str
    name: str
    arguments: str
    turn_id: int


@dataclass(slots=True)
class PostToolHookContext(ToolHookContext):
    output: ToolOutput


@dataclass
class ToolHooks:
    before: list[BeforeToolHook] = field(default_factory=list)
    after: list[AfterToolHook] = field(default_factory=list)

    async def run_before(self, ctx: ToolHookContext) -> ToolDecision | None:
        for hook in self.before:
            decision = hook(ctx)
            if isawaitable(decision):
                decision = await decision
            if decision is not None and not decision.execute:
                return decision
        return None

    async def run_after(
        self, ctx: PostToolHookContext, output: ToolOutput
    ) -> ToolOutput:
        current = output
        for hook in self.after:
            ctx.output = current
            replaced = hook(ctx)
            if isawaitable(replaced):
                replaced = await replaced
            if replaced is not None:
                current = replaced
        return current
