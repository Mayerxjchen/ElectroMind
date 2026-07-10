"""VanillaRunner —— 最小内存版 Agent Runner。

所有循环骨架方法（`execute_tool` / `stream_agent_events` / `emit` /
`emit_tool_events` / `run`）继承自 `LoopAdapter`；本类只持有 `agent` + `messages`，
`after_*` 用 `LoopAdapter` 的默认 no-op（不持久化）。三个 runner 的差异分析见
`docs/pagentv4/refactor-triage.md` 的 P0-1。
"""

from __future__ import annotations

from ..core.agent import Agent
from ..core.message import Messages
from .loop_adapter import LoopAdapter


class VanillaRunner(LoopAdapter):
    """Minimal in-memory AgentRunner.

    Included:

    - [x] tool execution for Agent.tools
    - [x] message state in memory
    - [x] event stream and return_type projection
    - [x] max_turns loop with one synthesis turn

    Excluded:

    - [ ] message persistence
    - [ ] thread lifecycle
    - [ ] sandbox tools
    - [ ] inbound cancel/steer/checkpoint
    - [ ] tool hooks or approval
    - [ ] skills injection
    """

    def __init__(self, agent: Agent, messages: Messages | None = None):
        super().__init__(agent, messages)
