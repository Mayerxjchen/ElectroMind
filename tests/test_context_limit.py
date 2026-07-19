from pagentv4.core.context_limit import (
    DEFAULT_CONTEXT_LIMIT,
    resolve_context_limit,
)


def test_resolve_context_limit_deepseek_v4():
    assert resolve_context_limit("deepseek-v4-flash") == 128_000


def test_resolve_context_limit_deepseek_chat():
    assert resolve_context_limit("deepseek-chat") == 64_000


def test_resolve_context_limit_unknown_falls_back():
    assert resolve_context_limit("custom-model") == DEFAULT_CONTEXT_LIMIT
    assert resolve_context_limit("") == DEFAULT_CONTEXT_LIMIT
