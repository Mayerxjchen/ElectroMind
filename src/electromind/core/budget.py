"""RunBudget — 每次 Run 的资源预算（M7 §12.3）。

- 每次模型调用和工具调用后更新预算。
- 超预算后停止新工作并进入结构化终止。
- Finalize 预留独立预算。
- 子 Agent 消耗计入父 Run 总预算。
- 未知 Token Usage 时使用保守估算。
- 预算耗尽不能继续提交新的外部任务。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# 未知 usage 的保守估算（token）
CONSERVATIVE_INPUT_TOKENS = 4_000
CONSERVATIVE_OUTPUT_TOKENS = 1_000


class BudgetExceededError(RuntimeError):
    """预算耗尽 —— 结构化终止（不继续新工作）。"""


@dataclass(slots=True)
class RunBudget:
    """Run 级预算账户。字段 0/None = 不限制。"""

    max_input_tokens: int = 0
    max_output_tokens: int = 0
    max_total_tokens: int = 0
    max_model_calls: int = 0
    max_tool_calls: int = 0
    max_wall_time_seconds: float = 0.0
    max_external_cost: float = 0.0

    # 已消耗
    input_tokens: int = 0
    output_tokens: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    external_cost: float = 0.0
    _started_at: float = field(default_factory=time.monotonic)

    # ── 检查 ────────────────────────────────────────────────────────

    def remaining_total(self) -> int:
        if self.max_total_tokens <= 0:
            return -1  # 不限制
        return max(0, self.max_total_tokens - (self.input_tokens + self.output_tokens))

    def exceeded_reason(self) -> str | None:
        """返回首个超限原因；None = 预算内。"""
        if self.max_total_tokens > 0 and (
            self.input_tokens + self.output_tokens > self.max_total_tokens
        ):
            return (
                f"total_tokens 超限: {self.input_tokens + self.output_tokens} > "
                f"{self.max_total_tokens}"
            )
        if self.max_input_tokens > 0 and self.input_tokens > self.max_input_tokens:
            return f"input_tokens 超限: {self.input_tokens} > {self.max_input_tokens}"
        if self.max_output_tokens > 0 and self.output_tokens > self.max_output_tokens:
            return (
                f"output_tokens 超限: {self.output_tokens} > {self.max_output_tokens}"
            )
        if self.max_model_calls > 0 and self.model_calls >= self.max_model_calls:
            return f"model_calls 超限: {self.model_calls} ≥ {self.max_model_calls}"
        if self.max_tool_calls > 0 and self.tool_calls >= self.max_tool_calls:
            return f"tool_calls 超限: {self.tool_calls} ≥ {self.max_tool_calls}"
        if (
            self.max_wall_time_seconds > 0
            and time.monotonic() - self._started_at > self.max_wall_time_seconds
        ):
            return "wall_time 超限"
        if self.max_external_cost > 0 and self.external_cost > self.max_external_cost:
            return (
                f"external_cost 超限: {self.external_cost} > {self.max_external_cost}"
            )
        return None

    def check(self) -> None:
        """超限即抛 ``BudgetExceededError``（结构化终止）。"""
        reason = self.exceeded_reason()
        if reason is not None:
            raise BudgetExceededError(reason)

    def can_submit_external(self) -> bool:
        """预算耗尽（或接近）时禁止提交新的外部任务。"""
        if self.exceeded_reason() is not None:
            return False
        return True

    # ── 记账 ────────────────────────────────────────────────────────

    def account_model_call(
        self, usage: dict | None = None, *, conservative: bool = False
    ) -> None:
        """模型调用后记账。usage 未知且 conservative=True 时用保守估算。"""
        self.model_calls += 1
        if usage:
            inp = int(usage.get("prompt_tokens", 0) or 0)
            out = int(usage.get("completion_tokens", 0) or 0)
            if inp or out or usage.get("total_tokens"):
                self.input_tokens += inp
                self.output_tokens += out
                return
        if conservative:
            self.input_tokens += CONSERVATIVE_INPUT_TOKENS
            self.output_tokens += CONSERVATIVE_OUTPUT_TOKENS

    def account_tool_call(self) -> None:
        self.tool_calls += 1

    def account_external_cost(self, cost: float) -> None:
        self.external_cost += cost

    def merge(self, other: "RunBudget") -> None:
        """子 Agent 消耗计入父 Run 总预算。"""
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.model_calls += other.model_calls
        self.tool_calls += other.tool_calls
        self.external_cost += other.external_cost

    def to_dict(self) -> dict:
        return {
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_total_tokens": self.max_total_tokens,
            "max_model_calls": self.max_model_calls,
            "max_tool_calls": self.max_tool_calls,
            "max_wall_time_seconds": self.max_wall_time_seconds,
            "max_external_cost": self.max_external_cost,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "external_cost": self.external_cost,
        }


# Finalize 预留预算（元数据常量）
FINALIZE_RESERVE_TOKENS = 2_000
