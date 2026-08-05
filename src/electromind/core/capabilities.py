"""ModelCapabilities — Provider 能力协商（M7 §12.1）。

- 不支持 tool calling 的模型不能进入工具执行 Runner。
- 不支持结构化输出时使用降级验证策略。
- 不允许仅凭模型名称硬编码全部能力；无法确认时必须使用保守默认值。
- Capability 决策进入 RunSnapshot（fingerprint 供固化）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .context_limit import resolve_context_limit


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    """模型能力声明（保守默认值：能力未知时全部 False）。"""

    context_window: int = 0  # 0 = 未确认（使用保守默认）
    supports_tools: bool = False
    supports_parallel_tools: bool = False
    supports_reasoning: bool = False
    supports_json_schema: bool = False
    supports_usage: bool = False
    supports_streaming: bool = False

    def effective_context_window(self, *, default: int = 128_000) -> int:
        """有效窗口：未确认时使用保守默认值。"""
        return self.context_window if self.context_window > 0 else default

    def fingerprint(self) -> str:
        """能力决策的确定性摘要（进 RunSnapshot）。"""
        h = hashlib.sha256()
        h.update(str(self.context_window).encode())
        for flag in (
            self.supports_tools,
            self.supports_parallel_tools,
            self.supports_reasoning,
            self.supports_json_schema,
            self.supports_usage,
            self.supports_streaming,
        ):
            h.update(b"1" if flag else b"0")
        return h.hexdigest()

    def to_dict(self) -> dict:
        return {
            "context_window": self.context_window,
            "supports_tools": self.supports_tools,
            "supports_parallel_tools": self.supports_parallel_tools,
            "supports_reasoning": self.supports_reasoning,
            "supports_json_schema": self.supports_json_schema,
            "supports_usage": self.supports_usage,
            "supports_streaming": self.supports_streaming,
        }


# 按名称子串的保守能力表（具体条目优先；未命中 → 全 False 保守默认）
_CAPABILITY_HINTS: tuple[tuple[str, dict], ...] = (
    (
        "reasoner",
        {
            "supports_tools": True,
            "supports_parallel_tools": True,
            "supports_reasoning": True,
            "supports_json_schema": True,
            "supports_usage": True,
            "supports_streaming": True,
        },
    ),
    (
        "deepseek",
        {
            "supports_tools": True,
            "supports_parallel_tools": True,
            "supports_reasoning": False,
            "supports_json_schema": True,
            "supports_usage": True,
            "supports_streaming": True,
        },
    ),
    (
        "gpt",
        {
            "supports_tools": True,
            "supports_parallel_tools": True,
            "supports_reasoning": False,
            "supports_json_schema": True,
            "supports_usage": True,
            "supports_streaming": True,
        },
    ),
    (
        "claude",
        {
            "supports_tools": True,
            "supports_parallel_tools": True,
            "supports_reasoning": True,
            "supports_json_schema": True,
            "supports_usage": True,
            "supports_streaming": True,
        },
    ),
    (
        "o1",
        {
            "supports_tools": True,
            "supports_parallel_tools": True,
            "supports_reasoning": True,
            "supports_json_schema": True,
            "supports_usage": True,
            "supports_streaming": True,
        },
    ),
    (
        "o3",
        {
            "supports_tools": True,
            "supports_parallel_tools": True,
            "supports_reasoning": True,
            "supports_json_schema": True,
            "supports_usage": True,
            "supports_streaming": True,
        },
    ),
)


def resolve_model_capabilities(
    model: str, *, context_window: int = 0
) -> ModelCapabilities:
    """按模型名解析能力。未命中名称 → 保守默认（全 False + 默认窗口）。

    ``context_window`` 显式传入时优先（调用方可从 RunSnapshot 读取）。
    """
    window = context_window or resolve_context_limit(model)
    name = (model or "").lower()
    for substring, hints in _CAPABILITY_HINTS:
        if substring in name:
            return ModelCapabilities(context_window=window, **hints)
    # 保守默认：能力未知全部 False（仅流式是 OpenAI 兼容基线）
    return ModelCapabilities(
        context_window=window,
        supports_streaming=True,
    )


def supports_tool_runner(capabilities: ModelCapabilities) -> bool:
    """不支持 tool calling 的模型不能进入工具执行 Runner。"""
    return capabilities.supports_tools
