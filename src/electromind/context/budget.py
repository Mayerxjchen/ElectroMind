"""Context Budget — Token 估算与 85% 阈值（M3 §8.2）。

- 每次请求前估算 Token；超过安全阈值必须先压缩。
- 默认上下文占用不得超过模型窗口的 85%。
- 必须保留输出与工具 Schema 空间。
- 无法确认窗口时使用保守默认值；Budget 决策进入 Trace。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.capabilities import ModelCapabilities

# 默认安全阈值（窗口占比）
MAX_CONTEXT_RATIO = 0.85
# 保守保留空间：输出 + 工具 schema（token）
RESERVE_TOKENS = 8_000


@dataclass(slots=True)
class ContextBudget:
    """一次模型调用的上下文预算决策。"""

    window: int
    estimate: int = 0
    threshold: int = 0
    decision: str = "ok"  # ok | compact | limit
    details: str = ""

    def over_threshold(self) -> bool:
        return self.decision in ("compact", "limit")


def estimate_tokens(text: str, *, encoder=None) -> int:
    """估算文本 token 数：tiktoken 优先，退化用字符/4 保守估算。"""
    if not text:
        return 0
    if encoder is not None:
        try:
            return len(encoder.encode(text))
        except Exception:  # noqa: BLE001
            pass
    return max(1, len(text) // 4)


def message_tokens(messages: list[dict], *, encoder=None) -> int:
    """估算 OpenAI 消息列表的 token 数（含 role 开销）。"""
    total = 0
    for message in messages:
        total += 4  # role 与结构开销
        content = message.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content, encoder=encoder)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    total += estimate_tokens(str(part.get("text", "")), encoder=encoder)
                else:
                    total += estimate_tokens(str(part), encoder=encoder)
        tc = message.get("tool_calls")
        if tc:
            for call in tc:
                fn = call.get("function", {})
                total += estimate_tokens(
                    str(fn.get("name", "")) + str(fn.get("arguments", "")),
                    encoder=encoder,
                )
    return total


def decide_context_budget(
    messages: list[dict],
    capabilities: ModelCapabilities,
    *,
    encoder=None,
    reserve_tokens: int = RESERVE_TOKENS,
) -> ContextBudget:
    """估算并决策：估算 > 85% 窗口 → compact；仍超 → limit。

    ``limit`` 表示压缩后依然超限（必须拒绝调用或丢弃工具 schema）。
    """
    window = capabilities.effective_context_window()
    threshold = int(window * MAX_CONTEXT_RATIO)
    estimate = message_tokens(messages, encoder=encoder)
    decision = "ok"
    details = f"estimate={estimate} threshold={threshold} window={window}"
    if estimate + reserve_tokens > threshold:
        decision = "compact"
        if estimate > threshold:
            decision = "limit"
    return ContextBudget(
        window=window,
        estimate=estimate,
        threshold=threshold,
        decision=decision,
        details=details,
    )


def trace_entry(budget: ContextBudget) -> dict:
    """Budget 决策的 Trace 记录。"""
    return {
        "event": "context_budget",
        "window": budget.window,
        "estimate": budget.estimate,
        "threshold": budget.threshold,
        "decision": budget.decision,
        "details": budget.details,
    }
