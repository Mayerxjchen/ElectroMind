"""M7: Provider 可靠性层测试（capabilities / retry / budget）。"""

from __future__ import annotations

import time

import pytest

from electromind.core.budget import (
    CONSERVATIVE_INPUT_TOKENS,
    BudgetExceededError,
    RunBudget,
)
from electromind.core.capabilities import (
    ModelCapabilities,
    resolve_model_capabilities,
    supports_tool_runner,
)
from electromind.core.retry import (
    ProviderErrorTaxonomy,
    RetryableError,
    RetryPolicy,
    RetryRecord,
    classify_exception,
    is_retryable,
    retry_stream,
    run_with_retry,
)

# ── capabilities ────────────────────────────────────────────────────────


def test_resolve_known_model():
    caps = resolve_model_capabilities("deepseek-v4-flash")
    assert caps.supports_tools
    assert caps.context_window == 128_000
    assert caps.fingerprint()
    d = caps.to_dict()
    assert d["supports_tools"] is True


def test_resolve_reasoner_and_unknown():
    caps = resolve_model_capabilities("deepseek-reasoner")
    assert caps.supports_reasoning
    unknown = resolve_model_capabilities("custom-llm-xyz")
    # 未命中 → 保守默认：工具能力未知为 False，窗口取 context_limit 保守值
    assert not unknown.supports_tools
    assert unknown.supports_streaming
    assert unknown.effective_context_window(default=64_000) == 128_000
    assert not supports_tool_runner(unknown)
    assert supports_tool_runner(caps)


def test_capability_fingerprint_changes():
    a = resolve_model_capabilities("deepseek-v4")
    b = resolve_model_capabilities("custom")
    assert a.fingerprint() != b.fingerprint()
    assert a.fingerprint() == a.fingerprint()  # 确定性


def test_capabilities_conservative_defaults():
    caps = ModelCapabilities()
    assert not caps.supports_tools
    assert caps.effective_context_window(default=128_000) == 128_000


# ── retry ───────────────────────────────────────────────────────────────


class FakeHTTPError(Exception):
    def __init__(self, status_code):
        super().__init__(f"http {status_code}")
        self.status_code = status_code


def test_classify_exception():
    assert classify_exception(FakeHTTPError(429)) == ProviderErrorTaxonomy.RATE_LIMITED
    assert classify_exception(FakeHTTPError(503)) == ProviderErrorTaxonomy.SERVER_ERROR
    assert classify_exception(FakeHTTPError(400)) == ProviderErrorTaxonomy.NON_RETRYABLE
    assert (
        classify_exception(TimeoutError("read timeout"))
        == ProviderErrorTaxonomy.READ_TIMEOUT
    )
    assert (
        classify_exception(RetryableError("stream_interrupted")) == "stream_interrupted"
    )
    assert is_retryable(ProviderErrorTaxonomy.RATE_LIMITED)
    assert not is_retryable(ProviderErrorTaxonomy.NON_RETRYABLE)


def test_retry_policy_delay():
    policy = RetryPolicy(base_delay_seconds=0.1, max_delay_seconds=0.5, jitter=0)
    assert policy.delay_for(0) == 0.1
    assert policy.delay_for(1) == 0.2
    assert policy.delay_for(5) == 0.5  # 封顶
    jittered = RetryPolicy(base_delay_seconds=1.0, jitter=0.5)
    assert 0.5 <= jittered.delay_for(0) <= 1.5


async def test_run_with_retry_success_after_failures():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise FakeHTTPError(503)
        return "ok"

    policy = RetryPolicy(max_retries=3, base_delay_seconds=0.01, jitter=0)
    result, record = await run_with_retry(flaky, policy=policy)
    assert result == "ok"
    assert len(record.attempts) == 2
    assert record.attempts[0]["kind"] == ProviderErrorTaxonomy.SERVER_ERROR


async def test_run_with_retry_non_retryable_immediate_fail():
    async def bad():
        raise FakeHTTPError(400)

    with pytest.raises(FakeHTTPError):
        await run_with_retry(bad, policy=RetryPolicy(max_retries=3))


async def test_run_with_retry_exhausted():
    calls = {"n": 0}

    async def always_429():
        calls["n"] += 1
        raise FakeHTTPError(429)

    with pytest.raises(FakeHTTPError):
        await run_with_retry(
            always_429,
            policy=RetryPolicy(max_retries=2, base_delay_seconds=0.01, jitter=0),
        )
    assert calls["n"] == 3  # 1 次初始 + 2 次重试


async def test_retry_stream_recovers():
    received = []
    policy = RetryPolicy(max_retries=2, base_delay_seconds=0.01, jitter=0)

    # 第一次流中断 → 重开流成功（第二次流正常结束）
    attempts = {"n": 0}
    record = RetryRecord()

    async def open_stream2():
        attempts["n"] += 1
        if attempts["n"] == 1:

            async def broken():
                yield {"text": "first"}
                raise RetryableError("stream_interrupted")

            return broken()
        else:

            async def good():
                yield {"text": "second"}

            return good()

    async for chunk in retry_stream(open_stream2, policy=policy, record=record):
        received.append(chunk)
    assert received == [{"text": "first"}, {"text": "second"}]
    assert len(record.attempts) == 1
    assert record.attempts[0]["kind"] == "stream_interrupted"


# ── budget ──────────────────────────────────────────────────────────────


def test_budget_accounting():
    budget = RunBudget(max_total_tokens=1000)
    budget.account_model_call({"prompt_tokens": 100, "completion_tokens": 50})
    assert budget.model_calls == 1
    assert budget.input_tokens == 100 and budget.output_tokens == 50
    budget.account_tool_call()
    assert budget.tool_calls == 1
    budget.account_external_cost(2.5)
    assert budget.external_cost == 2.5
    assert budget.remaining_total() == 850
    assert budget.exceeded_reason() is None
    assert budget.can_submit_external()


def test_budget_exceeded():
    budget = RunBudget(max_model_calls=2, max_total_tokens=100)
    budget.account_model_call({"prompt_tokens": 60, "completion_tokens": 60})
    reason = budget.exceeded_reason()
    assert reason and "total_tokens" in reason
    with pytest.raises(BudgetExceededError):
        budget.check()
    assert not budget.can_submit_external()


def test_budget_limits():
    budget = RunBudget(max_tool_calls=1, max_wall_time_seconds=1)
    budget.account_tool_call()
    assert "tool_calls" in budget.exceeded_reason()
    # wall time
    budget2 = RunBudget(max_wall_time_seconds=0)
    assert budget2.exceeded_reason() is None
    budget3 = RunBudget(max_wall_time_seconds=1)
    budget3._started_at = time.monotonic() - 5
    assert "wall_time" in budget3.exceeded_reason()


def test_budget_conservative_usage():
    budget = RunBudget()
    budget.account_model_call(None, conservative=True)
    assert budget.input_tokens == CONSERVATIVE_INPUT_TOKENS
    assert budget.output_tokens == 1000
    # 未知 usage 且非保守 → 不记账 token
    budget2 = RunBudget()
    budget2.account_model_call(None, conservative=False)
    assert budget2.input_tokens == 0


def test_budget_merge_subagent():
    parent = RunBudget()
    parent.account_model_call({"prompt_tokens": 10, "completion_tokens": 5})
    child = RunBudget()
    child.account_model_call({"prompt_tokens": 20, "completion_tokens": 10})
    child.account_tool_call()
    parent.merge(child)
    assert parent.input_tokens == 30
    assert parent.output_tokens == 15
    assert parent.model_calls == 2
    assert parent.tool_calls == 1


# ── AgentCore 集成（M7） ────────────────────────────────────────────────


class _StreamingProvider:
    """简易 Provider：返回可迭代的 chunk 流。"""

    def __init__(self, chunks, *, fail_times=0):
        self.chunks = chunks
        self.fail_times = fail_times
        self.calls = 0

    async def complete(self, messages, tools=None, **run_kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise FakeHTTPError(503)

        async def stream():
            for chunk in self.chunks:
                yield chunk

        return stream()


def _text_chunk(content: str):
    return type(
        "Chunk",
        (),
        {
            "choices": [
                type(
                    "Choice",
                    (),
                    {
                        "delta": type(
                            "Delta",
                            (),
                            {
                                "content": content,
                                "reasoning_content": None,
                                "tool_calls": None,
                            },
                        )()
                    },
                )()
            ],
            "usage": None,
        },
    )()


def _usage_chunk():
    return type(
        "Chunk",
        (),
        {
            "choices": [],
            "usage": type("Usage", (), {"prompt_tokens": 10, "completion_tokens": 5})(),
        },
    )()


async def test_agentcore_budget_accounting_and_check():
    from electromind.core.agent import AgentCore
    from electromind.core.budget import BudgetExceededError, RunBudget

    provider = _StreamingProvider([_text_chunk("hi"), _usage_chunk()])
    budget = RunBudget(max_total_tokens=1000)
    agent = AgentCore(provider, budget=budget, max_turns=2)
    from electromind.core.message import Messages

    messages = Messages()
    async for _ in agent.generate_messages(messages):
        pass
    assert budget.model_calls == 1
    assert budget.input_tokens == 10 and budget.output_tokens == 5

    # 预算耗尽 → 下一次调用前抛 BudgetExceededError
    tight = RunBudget(max_total_tokens=100)
    agent2 = AgentCore(_StreamingProvider([]), budget=tight, max_turns=2)
    tight.account_model_call({"prompt_tokens": 200})
    import pytest as _pytest

    with _pytest.raises(BudgetExceededError):
        async for _ in agent2.generate_messages(Messages()):
            pass


async def test_agentcore_retry_policy():
    from electromind.core.agent import AgentCore
    from electromind.core.message import Messages
    from electromind.core.retry import RetryPolicy

    provider = _StreamingProvider([_text_chunk("recovered")], fail_times=2)
    agent = AgentCore(
        provider,
        retry_policy=RetryPolicy(max_retries=3, base_delay_seconds=0.01, jitter=0),
        max_turns=2,
    )
    texts = []
    async for m in agent.generate_messages(Messages()):
        texts.append(getattr(m.content, "text", ""))
    assert texts == ["recovered"]
    assert provider.calls == 3  # 1 初始 + 2 重试
    assert agent.last_retry is not None
    assert agent.last_retry["kind"] == "server_error"


# ── R2-1 验收：Context limit 硬门禁 ─────────────────────────────────────


async def test_context_limit_hard_gate_rejects_provider_call():
    """R2-1: decision=limit 时拒绝调用 Provider（fail-closed）。"""
    from electromind.context import Compactor, ContextManager
    from electromind.core.agent import AgentCore, ContextLimitError
    from electromind.core.capabilities import ModelCapabilities
    from electromind.core.message import Messages

    calls = {"n": 0}

    class CountingProvider(_StreamingProvider):
        async def complete(self, messages, tools=None, **run_kwargs):
            calls["n"] += 1
            return await super().complete(messages, tools, **run_kwargs)

    provider = CountingProvider([_text_chunk("hi")])
    caps = ModelCapabilities(context_window=2_000)
    manager = ContextManager(caps, compactor=Compactor())
    agent = AgentCore(provider, context_manager=manager, max_turns=2)
    big = Messages()
    # 构造远超窗口的消息（压缩后仍超）
    big += _big_user_message(150_000)
    with pytest.raises(ContextLimitError, match="上下文超限"):
        async for _ in agent.generate_messages(big):
            pass
    assert calls["n"] == 0  # Provider 未被调用


def _big_user_message(chars: int):
    from electromind.core.message import Message

    return Message.user("x" * chars)
