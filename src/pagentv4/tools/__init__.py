"""Harness tools — host-process capabilities wired into Runner, not sandbox."""

from .delegate import (
    SUBAGENT_TOOL_NAME,
    make_delegate_tool,
    make_delegate_tools,
    make_subagent_tool,
)
from .web import fetch_url, web_search

HARNESS_WEB_TOOLS = [web_search, fetch_url]
# 对应 HARNESS_WEB_TOOLS 的工具名，用于 [agent] tools 白名单匹配。
HARNESS_WEB_TOOL_NAMES = ("web_search", "fetch_url")

__all__ = [
    "HARNESS_WEB_TOOLS",
    "HARNESS_WEB_TOOL_NAMES",
    "SUBAGENT_TOOL_NAME",
    "fetch_url",
    "make_delegate_tool",
    "make_delegate_tools",
    "make_subagent_tool",
    "web_search",
]
