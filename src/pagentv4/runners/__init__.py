"""pagentv4.runners — 开箱即用的三类 Runner，统一 ``await run(prompt) -> str``。"""

from .agentic import AgenticRunner
from .code import CodeAgent
from .config import RunConfig, resolve_provider
from .simple import SimpleQuestionAnswerRunner

__all__ = [
    "AgenticRunner",
    "CodeAgent",
    "RunConfig",
    "SimpleQuestionAnswerRunner",
    "resolve_provider",
]
