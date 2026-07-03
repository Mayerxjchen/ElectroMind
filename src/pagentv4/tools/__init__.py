"""Harness tools — host-process capabilities wired into Runner, not sandbox."""

from .web import fetch_url, web_search

HARNESS_WEB_TOOLS = [web_search, fetch_url]

__all__ = ["HARNESS_WEB_TOOLS", "fetch_url", "web_search"]
