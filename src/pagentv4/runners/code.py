from __future__ import annotations

from collections.abc import Sequence

from ..core.events import TurnEnd
from ..core.message import reply_text
from ..core.tool import FunctionTool
from ..runtime.runner import Runner
from .config import RunConfig, merge_tools, resolve_provider, temporary_tools


class CodeAgent:
    """完整沙箱 agent：文件/命令工具 + 可选额外工具。适合 SWE-bench 类任务。"""

    def __init__(
        self,
        config: RunConfig,
        *,
        tools: Sequence[FunctionTool] = (),
    ):
        self.config = config
        self.default_tools = list(tools)
        self._runner: Runner | None = None

    @property
    def runner(self) -> Runner:
        if self._runner is None:
            raise RuntimeError("CodeAgent is not open; call `await open()` first")
        return self._runner

    async def open(self) -> CodeAgent:
        if self._runner is not None:
            return self
        overrides = {"backend": self.config.backend, **self.config.sandbox_overrides}
        if self.config.image:
            overrides["image"] = self.config.image
        max_turns = 16 if self.config.max_turns is None else self.config.max_turns
        self._runner = await Runner.open(
            self.config.thread_id,
            resolve_provider(self.config),
            overrides=overrides,
            extra_system=self.config.extra_system or self.config.system or "",
            max_turns=max_turns,
            tools=self.default_tools,
        )
        return self

    async def close(self) -> None:
        if self._runner is None:
            return
        await self._runner.close()
        self._runner = None

    async def __aenter__(self) -> CodeAgent:
        await self.open()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def run(
        self,
        prompt: str,
        *,
        tools: Sequence[FunctionTool] | None = None,
        **run_kwargs,
    ) -> str:
        if self._runner is None:
            await self.open()

        agent = self.runner.agent
        merged = merge_tools(agent.tools, tools) if tools else agent.tools
        if tools:
            with temporary_tools(agent, merged):
                return await self._run_prompt(prompt, **run_kwargs)
        return await self._run_prompt(prompt, **run_kwargs)

    async def _run_prompt(self, prompt: str, **run_kwargs) -> str:
        stop_reason = "no_tool_calls"
        async for event in self.runner.run(prompt, return_type="event", **run_kwargs):
            if isinstance(event, TurnEnd) and event.stopped:
                stop_reason = event.stop_reason
        _ = stop_reason
        return reply_text(self.runner.messages.data)
