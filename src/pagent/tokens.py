import json
import sys
from dataclasses import dataclass
from typing import Protocol

import tiktoken

BACKEND_TIKTOKEN = "tiktoken"
BACKEND_HUGGINGFACE = "huggingface"

# model name substring → Hugging Face tokenizer repo (when backend=huggingface, tokenizer unset)
HF_TOKENIZER_BY_MODEL = {
    "deepseek": "deepseek-ai/DeepSeek-V3",
}

_encoder_cache: dict[tuple[str, str], "TokenEncoder"] = {}


class TokenEncoder(Protocol):
    def encode(self, text: str) -> list[int]: ...


class TiktokenEncoder:
    def __init__(self, enc):
        self._enc = enc

    def encode(self, text: str) -> list[int]:
        return self._enc.encode(text)


class HuggingFaceEncoder:
    def __init__(self, tokenizer):
        self._tokenizer = tokenizer

    def encode(self, text: str) -> list[int]:
        return self._tokenizer.encode(text, add_special_tokens=False)


def infer_backend(model: str) -> str:
    m = model.lower()
    if "deepseek" in m:
        return BACKEND_HUGGINGFACE
    if m.startswith("gpt") or m.startswith("o1") or m.startswith("o3"):
        return BACKEND_TIKTOKEN
    return BACKEND_TIKTOKEN


def hf_tokenizer_id(model: str, tokenizer: str | None = None) -> str:
    if tokenizer:
        return tokenizer
    m = model.lower()
    for key, repo in HF_TOKENIZER_BY_MODEL.items():
        if key in m:
            return repo
    return model


def get_encoder(
    *,
    model: str = "gpt-4o",
    backend: str | None = None,
    tokenizer: str | None = None,
) -> TokenEncoder:
    """Return a cached tokenizer encoder for *model* and *backend*."""
    resolved_backend = backend or infer_backend(model)
    if resolved_backend == BACKEND_TIKTOKEN:
        cache_key = (BACKEND_TIKTOKEN, model)
        if cache_key not in _encoder_cache:
            _encoder_cache[cache_key] = TiktokenEncoder(
                tiktoken.encoding_for_model(model)
            )
        return _encoder_cache[cache_key]

    if resolved_backend == BACKEND_HUGGINGFACE:
        repo = hf_tokenizer_id(model, tokenizer)
        cache_key = (BACKEND_HUGGINGFACE, repo)
        if cache_key not in _encoder_cache:
            try:
                from transformers import AutoTokenizer
            except ImportError as e:
                raise ImportError(
                    "huggingface token backend requires transformers; "
                    "install with: pip install 'pagent[tokens]'"
                ) from e
            _encoder_cache[cache_key] = HuggingFaceEncoder(
                AutoTokenizer.from_pretrained(repo)
            )
        return _encoder_cache[cache_key]

    raise ValueError(f"unknown token backend: {backend!r}")


def resolve_encoder(
    *,
    encoder: TokenEncoder | None = None,
    model: str = "gpt-4o",
    backend: str | None = None,
    tokenizer: str | None = None,
) -> TokenEncoder:
    if encoder is not None:
        return encoder
    return get_encoder(model=model, backend=backend, tokenizer=tokenizer)


def message_tokens(
    msg,
    *,
    encoder: TokenEncoder | None = None,
    model: str = "gpt-4o",
    backend: str | None = None,
    tokenizer: str | None = None,
):
    """Token count for one Chat Completions message dict."""
    enc = resolve_encoder(
        encoder=encoder, model=model, backend=backend, tokenizer=tokenizer
    )
    n = 0

    content = msg.get("content")
    if isinstance(content, str):
        n += len(enc.encode(content))
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text", "")
                if isinstance(text, str) and text:
                    n += len(enc.encode(text))

    reasoning = msg.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning:
        n += len(enc.encode(reasoning))

    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        name = fn.get("name", "")
        if name:
            n += len(enc.encode(name))
        args = fn.get("arguments", "")
        if args:
            if isinstance(args, str):
                n += len(enc.encode(args))
            else:
                n += len(enc.encode(json.dumps(args, ensure_ascii=False)))

    if msg.get("role") == "tool":
        tc_id = msg.get("tool_call_id")
        if isinstance(tc_id, str) and tc_id:
            n += len(enc.encode(tc_id))

    return n


def count_tokens(
    messages,
    *,
    encoder: TokenEncoder | None = None,
    model: str = "gpt-4o",
    backend: str | None = None,
    tokenizer: str | None = None,
):
    """Sum ``message_tokens`` over a message list."""
    enc = resolve_encoder(
        encoder=encoder, model=model, backend=backend, tokenizer=tokenizer
    )
    return sum(message_tokens(m, encoder=enc) for m in messages)


def tools_tokens(
    tools,
    *,
    encoder: TokenEncoder | None = None,
    model: str = "gpt-4o",
    backend: str | None = None,
    tokenizer: str | None = None,
):
    """Token count for an OpenAI ``tools`` schema list (JSON-encoded)."""
    if not tools:
        return 0
    enc = resolve_encoder(
        encoder=encoder, model=model, backend=backend, tokenizer=tokenizer
    )
    return len(enc.encode(json.dumps(tools, ensure_ascii=False)))


def text_tokens(
    text,
    *,
    encoder: TokenEncoder | None = None,
    model: str = "gpt-4o",
    backend: str | None = None,
    tokenizer: str | None = None,
):
    """Token count for arbitrary caller-provided text."""
    if not text:
        return 0
    enc = resolve_encoder(
        encoder=encoder, model=model, backend=backend, tokenizer=tokenizer
    )
    return len(enc.encode(text))


@dataclass
class TokenBreakdown:
    """Context token buckets (system / tools / conversation + optional extras)."""

    system: int
    tools: int
    conversation: int
    extras: dict[str, int]
    total: int
    max_tokens: int | None = None

    @property
    def percent(self) -> float | None:
        if self.max_tokens is None or self.max_tokens <= 0:
            return None
        return 100.0 * self.total / self.max_tokens

    @property
    def is_full(self) -> bool | None:
        if self.max_tokens is None:
            return None
        return self.total >= self.max_tokens


def count_tokens_detail(
    messages,
    *,
    tools=None,
    extras=None,
    encoder: TokenEncoder | None = None,
    model: str = "gpt-4o",
    backend: str | None = None,
    tokenizer: str | None = None,
    max_tokens=None,
) -> TokenBreakdown:
    """Split context tokens into buckets for UI-style breakdowns.

    Example with :class:`~pagent.agent.Agent`::

        from pagent import count_tokens_detail

        detail = count_tokens_detail(
            agent.session.messages,
            tools=agent.tool_schemas,
            extras={"rules": my_rules_text, "skills": my_skills_text},
            max_tokens=128_000,
        )
        detail.system, detail.tools, detail.conversation, detail.total
        detail.percent, detail.is_full
    """
    enc = resolve_encoder(
        encoder=encoder, model=model, backend=backend, tokenizer=tokenizer
    )

    system = 0
    conversation = 0
    for msg in messages:
        n = message_tokens(msg, encoder=enc)
        if msg.get("role") == "system":
            system += n
        else:
            conversation += n

    tools_n = tools_tokens(tools, encoder=enc) if tools else 0

    extras_counts: dict[str, int] = {}
    if extras:
        for key, text in extras.items():
            extras_counts[key] = text_tokens(text, encoder=enc)

    total = system + tools_n + conversation + sum(extras_counts.values())

    return TokenBreakdown(
        system=system,
        tools=tools_n,
        conversation=conversation,
        extras=extras_counts,
        total=total,
        max_tokens=max_tokens,
    )


RESET = "\033[0m"
DIM = "\033[2m"
GRAY = "\033[90m"
MAGENTA = "\033[35m"
YELLOW = "\033[33m"
EXTRA_COLORS = ("\033[36m", "\033[34m", "\033[32m", "\033[91m", "\033[96m", "\033[94m")

BUCKET_LABELS = {
    "system": "System prompt",
    "tools": "Tool definitions",
    "conversation": "Conversation",
}

EXTRA_LABELS = {
    "rules": "Rules",
    "skills": "Skills",
    "subagent_definitions": "Subagent definitions",
    "subagents": "Subagent definitions",
}

BUCKET_COLORS = {
    "system": GRAY,
    "tools": MAGENTA,
    "conversation": YELLOW,
}


def format_k(n: int, *, approximate: bool = False) -> str:
    """Format token counts; use K suffix for values >= 1000."""
    if n >= 1000:
        k = n / 1000
        if k >= 100:
            text = f"{int(round(k))}K"
        else:
            text = f"{k:.1f}".rstrip("0").rstrip(".") + "K"
        return f"~{text}" if approximate else text
    return str(n)


def extra_label(key: str) -> str:
    return EXTRA_LABELS.get(key, key.replace("_", " ").title())


def _use_color(use_color: bool | None) -> bool:
    if use_color is None:
        return sys.stdout.isatty()
    return use_color


def _paint(text: str, color: str, use_color: bool) -> str:
    if not use_color or not color:
        return text
    return f"{color}{text}{RESET}"


def _breakdown_buckets(detail: TokenBreakdown) -> list[tuple[str, str, int, str]]:
    """Return (key, label, count, color) rows in display order."""
    rows: list[tuple[str, str, int, str]] = []
    if detail.system:
        rows.append(
            ("system", BUCKET_LABELS["system"], detail.system, BUCKET_COLORS["system"])
        )
    if detail.tools:
        rows.append(
            ("tools", BUCKET_LABELS["tools"], detail.tools, BUCKET_COLORS["tools"])
        )
    for i, (key, count) in enumerate(detail.extras.items()):
        if count:
            color = EXTRA_COLORS[i % len(EXTRA_COLORS)]
            rows.append((key, extra_label(key), count, color))
    if detail.conversation:
        rows.append(
            (
                "conversation",
                BUCKET_LABELS["conversation"],
                detail.conversation,
                BUCKET_COLORS["conversation"],
            )
        )
    return rows


def _allocate_blocks(counts: list[int], width: int, capacity: int) -> list[int]:
    if width <= 0 or capacity <= 0 or not any(counts):
        return [0] * len(counts)

    total = sum(counts)
    target_filled = min(width, max(0, int(round(width * total / capacity))))
    if target_filled == 0:
        return [0] * len(counts)

    blocks = [0] * len(counts)
    fractions: list[tuple[float, int]] = []
    for i, count in enumerate(counts):
        if count <= 0:
            continue
        exact = target_filled * count / total
        whole = int(exact)
        blocks[i] = whole
        fractions.append((exact - whole, i))

    remainder = target_filled - sum(blocks)
    fractions.sort(reverse=True)
    for k in range(remainder):
        blocks[fractions[k % len(fractions)][1]] += 1
    return blocks


def format_context(
    detail: TokenBreakdown, *, width: int = 40, use_color: bool | None = None
) -> str:
    """ASCII/ANSI context window breakdown (progress bar + legend)."""
    color_on = _use_color(use_color)
    rows = _breakdown_buckets(detail)
    lines: list[str] = []

    lines.append(_paint("Context", "", color_on))

    if detail.max_tokens is not None and detail.percent is not None:
        pct = int(round(detail.percent))
        header_right = f"{format_k(detail.total, approximate=True)} / {format_k(detail.max_tokens)} Tokens"
        lines.append(f"{pct}% Full    {header_right}")
    else:
        lines.append(f"{format_k(detail.total, approximate=True)} Tokens")

    capacity = detail.max_tokens if detail.max_tokens else max(detail.total, 1)
    counts = [r[2] for r in rows]
    blocks = _allocate_blocks(counts, width, capacity)
    filled = sum(blocks)
    empty = max(0, width - filled) if detail.max_tokens else 0

    bar_parts: list[str] = []
    for (_, _, _, bucket_color), n in zip(rows, blocks, strict=False):
        if n > 0:
            chunk = "█" * n
            bar_parts.append(_paint(chunk, bucket_color, color_on))
    if empty > 0:
        bar_parts.append(_paint("░" * empty, DIM, color_on))
    lines.append(
        "".join(bar_parts) if bar_parts else _paint("░" * width, DIM, color_on)
    )

    square = "■"
    for _, label, count, bucket_color in rows:
        count_s = format_k(count)
        marker = _paint(square, bucket_color, color_on)
        lines.append(f"{marker} {label:<22} {count_s}")

    return "\n".join(lines)
