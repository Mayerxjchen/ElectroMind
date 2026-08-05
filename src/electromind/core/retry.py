"""RetryPolicy — Provider 请求重试（M7 §12.2）。

- 可重试错误：429、5xx、连接/读取超时、流中断、非法 chunk。
- 不可重试错误：4xx（非 429）、参数错误 —— 立即失败。
- 指数退避 + 抖动；重试次数可配置；每次重试记录原因。
- 只允许幂等请求自动重试；工具副作用绝不因 Provider Retry 重复执行
  （副作用层由 IdempotencyStore 保护）。
- 模型 Retry 不重复追加用户消息（消息组装在重试外层）。
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from enum import StrEnum


class RetryableError(Exception):
    """可重试的临时 Provider 故障（429 / 5xx / 超时 / 流中断）。"""

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(detail or kind)
        self.kind = kind


class ProviderErrorTaxonomy(StrEnum):
    RATE_LIMITED = "rate_limited"  # 429
    SERVER_ERROR = "server_error"  # 500/502/503
    CONNECT_TIMEOUT = "connect_timeout"
    READ_TIMEOUT = "read_timeout"
    STREAM_INTERRUPTED = "stream_interrupted"
    INVALID_CHUNK = "invalid_chunk"
    USAGE_MISSING = "usage_missing"
    NON_RETRYABLE = "non_retryable"  # 4xx（非 429）等


def classify_exception(exc: BaseException) -> str:
    """将异常分类为 ProviderErrorTaxonomy 值。"""
    if isinstance(exc, RetryableError):
        return exc.kind
    status = getattr(exc, "status_code", None)
    if status is not None:
        if status == 429:
            return ProviderErrorTaxonomy.RATE_LIMITED
        if 500 <= status < 600:
            return ProviderErrorTaxonomy.SERVER_ERROR
        return ProviderErrorTaxonomy.NON_RETRYABLE
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return ProviderErrorTaxonomy.READ_TIMEOUT
    if "connection" in name or "connect" in name:
        return ProviderErrorTaxonomy.CONNECT_TIMEOUT
    if "interrupt" in name or "stream" in name:
        return ProviderErrorTaxonomy.STREAM_INTERRUPTED
    if "chunk" in name or "parse" in name:
        return ProviderErrorTaxonomy.INVALID_CHUNK
    return ProviderErrorTaxonomy.NON_RETRYABLE


RETRYABLE_KINDS = frozenset(
    {
        ProviderErrorTaxonomy.RATE_LIMITED,
        ProviderErrorTaxonomy.SERVER_ERROR,
        ProviderErrorTaxonomy.CONNECT_TIMEOUT,
        ProviderErrorTaxonomy.READ_TIMEOUT,
        ProviderErrorTaxonomy.STREAM_INTERRUPTED,
        ProviderErrorTaxonomy.INVALID_CHUNK,
    }
)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """指数退避 + 抖动策略。"""

    max_retries: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0
    jitter: float = 0.2  # ±20% 抖动

    def delay_for(self, attempt: int) -> float:
        """第 ``attempt`` 次重试前的延迟（0 基）。"""
        delay = min(
            self.max_delay_seconds,
            self.base_delay_seconds * (2**attempt),
        )
        if self.jitter > 0:
            delay *= 1 + random.uniform(-self.jitter, self.jitter)
        return max(0.0, delay)


@dataclass(slots=True)
class RetryRecord:
    """每次重试的原因记录。"""

    attempts: list[dict] = field(default_factory=list)

    def add(self, attempt: int, kind: str, detail: str) -> None:
        self.attempts.append(
            {
                "attempt": attempt,
                "kind": kind,
                "detail": detail[:200],
                "at": time.time(),
            }
        )

    def to_dict(self) -> dict:
        return {"attempts": self.attempts}


def is_retryable(kind: str) -> bool:
    return kind in RETRYABLE_KINDS


async def run_with_retry(
    fn,
    *,
    policy: RetryPolicy,
    on_retry: "callable | None" = None,
) -> "tuple[object, RetryRecord]":
    """带重试地执行 ``fn``（幂等请求专用）。

    ``fn`` 可返回 stream 时，重试只覆盖「发起」阶段——流开始后的中断
    由调用方通过 ``retry_stream`` 处理。
    """
    record = RetryRecord()
    attempt = 0
    while True:
        try:
            result = await fn()
            return result, record
        except Exception as exc:  # noqa: BLE001 — 分类后决定重试
            kind = classify_exception(exc)
            if not is_retryable(kind) or attempt >= policy.max_retries:
                raise
            record.add(attempt, kind, str(exc))
            if on_retry is not None:
                on_retry(record.attempts[-1])
            await asyncio.sleep(policy.delay_for(attempt))
            attempt += 1


async def retry_stream(
    open_stream,
    *,
    policy: RetryPolicy,
    on_retry: "callable | None" = None,
    record: RetryRecord | None = None,
):
    """流式读取 + 中断恢复（async generator）。

    ``open_stream()`` 每次重开流（幂等请求）。流读取中断（抛异常）时
    按策略重开；已收到的 chunk 由调用方丢弃（模型消息组装在完整流后，
    不重复追加）。传入 ``record`` 可获取重试记录。
    """
    attempts = record or RetryRecord()
    attempt = 0
    while True:
        stream = await open_stream()
        try:
            async for chunk in stream:
                yield chunk
            return
        except Exception as exc:  # noqa: BLE001
            kind = classify_exception(exc)
            if not is_retryable(kind) or attempt >= policy.max_retries:
                raise
            attempts.add(attempt, kind, str(exc))
            if on_retry is not None:
                on_retry(attempts.attempts[-1])
            await asyncio.sleep(policy.delay_for(attempt))
            attempt += 1
