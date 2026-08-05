"""Context 与记忆（M3）。

- ``budget``：Token 估算与 85% 阈值决策。
- ``compactor``：摘要压缩（约束 100% 保留、配对完整）。
- ``memory``：Thread / Project / Artifact 三层记忆。
- ``manager``：ContextManager 上下文构造（RunEngine 接入点）。
"""

from .budget import (
    ContextBudget,
    decide_context_budget,
    estimate_tokens,
    message_tokens,
    trace_entry,
)
from .compactor import Compactor, SummaryRecord, digest_messages
from .manager import ContextInput, ContextManager, PreparedContext
from .memory import (
    ArtifactMemory,
    ArtifactMemoryEntry,
    ProjectMemory,
    ThreadMemory,
)

__all__ = [
    "ArtifactMemory",
    "ArtifactMemoryEntry",
    "Compactor",
    "ContextBudget",
    "ContextInput",
    "ContextManager",
    "PreparedContext",
    "ProjectMemory",
    "SummaryRecord",
    "ThreadMemory",
    "decide_context_budget",
    "digest_messages",
    "estimate_tokens",
    "message_tokens",
    "trace_entry",
]
