from __future__ import annotations

from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field

from ..core.agent import Agent
from ..core.provider import DeepSeek, Provider
from ..core.tool import FunctionTool, to_openai_tools


@dataclass
class RunConfig:
    """三类 Runner 的共用配置。"""

    model: str = "deepseek-v4-flash"
    provider: Provider | None = None
    system: str | None = None
    max_turns: int | None = None
    api_key: str | None = None
    base_url: str | None = None
    thread_id: str = "code-agent"
    backend: str = "local"
    image: str | None = None
    extra_system: str = ""
    sandbox_overrides: dict = field(default_factory=dict)


def resolve_provider(config: RunConfig) -> Provider:
    if config.provider is not None:
        return config.provider
    kwargs: dict = {}
    if config.api_key:
        kwargs["apikey"] = config.api_key
    if config.base_url:
        kwargs["base_url"] = config.base_url
    return DeepSeek(config.model, **kwargs)


def merge_tools(
    base: Sequence[FunctionTool],
    extra: Sequence[FunctionTool] | None,
) -> list[FunctionTool]:
    if not extra:
        return list(base)
    merged = [*base, *extra]
    names = [tool.name for tool in merged]
    if len(names) != len(set(names)):
        raise ValueError(f"duplicate tool names: {names}")
    return merged


@contextmanager
def temporary_tools(agent: Agent, tools: Sequence[FunctionTool]):
    saved_tools = agent.tools
    saved_map = agent.tool_map
    saved_schemas = agent.tool_schemas
    agent.tools = list(tools)
    agent.tool_map = {tool.name: tool for tool in agent.tools}
    agent.tool_schemas = to_openai_tools(agent.tools) or None
    try:
        yield
    finally:
        agent.tools = saved_tools
        agent.tool_map = saved_map
        agent.tool_schemas = saved_schemas
