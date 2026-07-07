from __future__ import annotations

from ..core.agent import Agent
from ..core.message import Messages
from .config import RunConfig, resolve_provider
from .loop import run_agent


class SimpleQuestionAnswerRunner:
    """单轮问答：无工具、无沙箱。适合文章 + 问题拼在一个 prompt 里。"""

    def __init__(self, config: RunConfig):
        self.config = config
        max_turns = 1 if config.max_turns is None else config.max_turns
        self.agent = Agent(
            resolve_provider(config),
            system=config.system,
            tools=[],
            max_turns=max_turns,
        )

    async def run(self, prompt: str, **run_kwargs) -> str:
        return await run_agent(
            self.agent, prompt, messages=Messages(), run_kwargs=run_kwargs
        )
