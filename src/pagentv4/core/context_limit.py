"""Model context window sizes for usage UI (best-effort substring match)."""

from __future__ import annotations

DEFAULT_CONTEXT_LIMIT = 128_000

# More specific keys first — first substring match wins.
_MODEL_CONTEXT_LIMITS: tuple[tuple[str, int], ...] = (
    ("deepseek-reasoner", 64_000),
    ("deepseek-v4", 128_000),
    ("deepseek-chat", 64_000),
    ("deepseek", 128_000),
    ("gpt-4o-mini", 128_000),
    ("gpt-4o", 128_000),
    ("gpt-4-turbo", 128_000),
    ("gpt-4-32k", 32_768),
    ("gpt-4", 8_192),
    ("o3-mini", 200_000),
    ("o3", 200_000),
    ("o1-mini", 128_000),
    ("o1", 200_000),
    ("claude-3-5", 200_000),
    ("claude-3-opus", 200_000),
    ("claude-3", 200_000),
    ("claude", 200_000),
)


def resolve_context_limit(model: str, *, default: int = DEFAULT_CONTEXT_LIMIT) -> int:
    """Return an approximate max context window for *model* name."""
    normalized = model.strip().lower()
    if not normalized:
        return default
    for key, limit in _MODEL_CONTEXT_LIMITS:
        if key in normalized:
            return limit
    return default
