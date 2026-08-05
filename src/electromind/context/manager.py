"""ContextManager — 每次模型调用前的上下文构造与预算（M3 §8.1/§8.2）。

构造顺序（M3 §8.1）：
1. System 与安全策略
2. 用户明确固定的约束
3. 当前 Objective 与 Approved Plan
4. 当前 Step
5. 最近若干轮原始对话
6. 历史对话摘要
7. 相关 Artifact/文件的检索结果
8. Tool Result 的结构化摘要
9. 当前预算与剩余资源

不得无条件发送完整历史；超过 85% 阈值必须先压缩。原始输出落盘，
消息里保留摘要和引用。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.capabilities import ModelCapabilities
from .budget import ContextBudget, decide_context_budget, trace_entry
from .compactor import Compactor, SummaryRecord


@dataclass(slots=True)
class ContextInput:
    """一次上下文构造的输入（可由 RunEngine 填充）。"""

    system: str = ""
    pinned_constraints: list[str] = field(default_factory=list)
    objective: str = ""
    plan: str = ""  # Approved Plan 的紧凑表示
    current_step: str = ""
    recent_messages: list[dict] = field(default_factory=list)  # 原始对话
    tool_summaries: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    budget_info: str = ""  # 剩余资源摘要
    memory: dict = field(default_factory=dict)  # Thread/Project 记忆快照


@dataclass(slots=True)
class PreparedContext:
    """构造结果：送模型的 openai 消息 + 预算决策 + 压缩记录。"""

    messages: list[dict]
    budget: ContextBudget
    summary: SummaryRecord | None = None
    trace: list[dict] = field(default_factory=list)


class ContextManager:
    """按上下文构成规则构造消息列表；超阈值时先压缩。"""

    def __init__(
        self,
        capabilities: ModelCapabilities,
        *,
        compactor: Compactor | None = None,
        encoder=None,
    ) -> None:
        self.capabilities = capabilities
        self.compactor = compactor or Compactor()
        self.encoder = encoder
        self.last_trace: list[dict] = []

    def prepare(self, context: ContextInput) -> PreparedContext:
        """构造并（必要时）压缩。永不抛——超限时返回 limit 决策。"""
        messages = self._assemble(context)
        budget = decide_context_budget(
            messages, self.capabilities, encoder=self.encoder
        )
        trace = [trace_entry(budget)]
        summary: SummaryRecord | None = None

        if budget.decision == "compact":
            messages, summary = self.compactor.compact(messages)
            budget = decide_context_budget(
                messages, self.capabilities, encoder=self.encoder
            )
            trace.append(trace_entry(budget))
        if budget.decision == "limit":
            # 压缩后仍超限：截断最旧的非约束消息（保守降级，绝不丢约束）
            messages = self._truncate_safely(messages)
            budget = decide_context_budget(
                messages, self.capabilities, encoder=self.encoder
            )
            trace.append(trace_entry(budget))

        self.last_trace = trace
        return PreparedContext(
            messages=messages, budget=budget, summary=summary, trace=trace
        )

    # ── 组装 ────────────────────────────────────────────────────────

    def _assemble(self, context: ContextInput) -> list[dict]:
        system_parts = [context.system]
        if context.pinned_constraints:
            system_parts.append(
                "用户固定约束（必须始终遵守，不得省略）：\n- "
                + "\n- ".join(context.pinned_constraints)
            )
        if context.objective:
            system_parts.append(f"当前目标：{context.objective}")
        if context.plan:
            system_parts.append(f"已批准计划：{context.plan}")
        if context.current_step:
            system_parts.append(f"当前步骤：{context.current_step}")
        if context.budget_info:
            system_parts.append(f"资源预算：{context.budget_info}")

        messages: list[dict] = [
            {
                "role": "system",
                "content": "\n".join(part for part in system_parts if part),
            }
        ]
        if context.artifact_refs:
            messages.append(
                {
                    "role": "user",
                    "content": "[相关产物索引]\n" + "\n".join(context.artifact_refs),
                }
            )
        messages.extend(context.recent_messages)
        if context.tool_summaries:
            messages.append(
                {
                    "role": "user",
                    "content": "[工具结果摘要]\n" + "\n".join(context.tool_summaries),
                }
            )
        return messages

    def _truncate_safely(self, messages: list[dict]) -> list[dict]:
        """压缩后仍超限：从后往前丢弃可弃消息（非 system、非约束）。"""
        safe: list[dict] = []
        for message in messages:
            content = message.get("content", "")
            text = content if isinstance(content, str) else str(content or "")
            if message.get("role") == "system":
                safe.append(message)
                continue
            if (
                "[历史摘要]" in text
                or "[相关产物索引]" in text
                or "[工具结果摘要]" in text
            ):
                continue  # 合成段可弃
            if any(c and c in text for c in self.compactor.pinned_constraints):
                safe.append(message)  # 约束段不可弃
                continue
        # 约束之后，保留尾部最近消息（至少保留最后一条）
        tail = [m for m in messages if m not in safe][-8:]
        return safe + tail
