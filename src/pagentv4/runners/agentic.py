from __future__ import annotations

from collections.abc import Sequence

from ..core.agent import Agent
from ..core.message import Messages
from ..core.tool import FunctionTool
from .config import RunConfig, resolve_provider
from .loop import run_agent


class AgenticRunner:
    """带工具的 agent：无沙箱。工具可在构造时或每次 run 时传入。"""

    def __init__(
        self,
        config: RunConfig,
        *,
        tools: Sequence[FunctionTool] = (),
    ):
        self.config = config
        self.default_tools = list(tools)
        max_turns = 8 if config.max_turns is None else config.max_turns
        self.agent = Agent(
            resolve_provider(config),
            system=config.system,
            tools=self.default_tools,
            max_turns=max_turns,
        )

    def _agent_for(self, tools: Sequence[FunctionTool] | None) -> Agent:
        if tools is None:
            return self.agent
        return Agent(
            self.agent.provider,
            system=self.agent.system,
            tools=list(tools),
            max_turns=self.agent.max_turns,
        )

    async def run(
        self,
        prompt: str,
        *,
        tools: Sequence[FunctionTool] | None = None,
        **run_kwargs,
    ) -> str:
        agent = self._agent_for(tools)
        return await run_agent(
            agent, prompt, messages=Messages(), run_kwargs=run_kwargs
        )
