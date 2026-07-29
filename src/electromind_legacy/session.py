import json

from .tokens import count_tokens, tools_tokens

COMPACTOR_SYSTEM = """You are a conversation compactor. The user provides a conversation history.
Compress it into a concise summary that preserves:
- Key decisions and conclusions
- Important facts, numbers, and names
- User preferences and constraints
- Any unresolved questions or action items

Discard:
- Greetings, pleasantries, filler
- Redundant exchanges
- Verbose reasoning that led to a final answer (keep only the answer)

Output only the compressed summary, nothing else."""


def compactor(llm):
    """Create a conversation compactor agent.

    Usage::

        from pagent import DeepSeek, compactor

        cp = compactor(DeepSeek("deepseek-v4-flash"))
        result = await cp.run("对话历史内容...")
        print(result.content)  # compressed summary
    """
    from .agent import Agent

    return Agent(llm, Session(COMPACTOR_SYSTEM), tools=[], max_turns=1)


class Session:
    """Conversation buffer: Chat Completions-shaped message dicts in ``messages``.

    Append: ``session += {"role": "user", "content": "..."}`` or ``session += [msg, ...]``.
    """

    def __init__(self, system_prompt="You are a helpful assistant."):
        self.system_prompt = system_prompt
        self.messages = []
        if not system_prompt:
            return
        self.messages.append({"role": "system", "content": system_prompt})

    def __iadd__(self, other):
        if isinstance(other, (str, bytes, bytearray)):
            raise TypeError("session += expects message dict(s), not str/bytes")
        if isinstance(other, dict):
            self.messages.append(dict(other))
            return self

        self.messages.extend(dict(m) for m in other)
        return self

    def reset(self):
        self.messages.clear()
        if not self.system_prompt:
            return
        self.messages.append({"role": "system", "content": self.system_prompt})

    def save_to_file(self, path, *, indent=2):
        """Write ``messages`` as UTF-8 JSON (API-shaped list of dicts)."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.messages, f, ensure_ascii=False, indent=indent)


class CompactingSession(Session):
    """``Session`` that can summarize non-system history via ``compact()``.

    Call ``await session.compact()`` manually when ``should_compact`` is true
    (when ``compact_at_tokens`` is set and token count exceeds the threshold).
    """

    def __init__(
        self,
        system_prompt="You are a helpful assistant.",
        *,
        llm,
        compact_at_tokens=None,
        model="gpt-4o",
        backend=None,
    ):
        self.llm = llm
        self.compact_at_tokens = compact_at_tokens
        self.model = model
        self.backend = backend
        super().__init__(system_prompt)

    @property
    def should_compact(self):
        if self.compact_at_tokens is None:
            return False
        kw = {"model": self.model, "backend": self.backend}
        return count_tokens(self.messages, **kw) > self.compact_at_tokens

    async def compact(self):
        prefix, rest = self._split_messages()
        if not rest:
            return
        history = json.dumps(rest, ensure_ascii=False)
        result = await compactor(self.llm).run(history)
        summary = (result.content or "").strip()
        self.messages = prefix + [
            {
                "role": "user",
                "content": f"[Previous conversation summary]\n{summary}",
            }
        ]

    def _split_messages(self):
        i = 0
        while i < len(self.messages) and self.messages[i].get("role") == "system":
            i += 1
        return self.messages[:i], self.messages[i:]


class SlidingWindowSession(Session):
    """``Session`` that trims conversation to fit within ``max_tokens``.

    Leading ``role==system`` messages are always kept. Tool schema tokens
    (``tools=``) are reserved from the budget. When trimming, an assistant
    message with ``tool_calls`` is removed together with its following
    ``tool`` messages.
    """

    def __init__(
        self,
        system_prompt="You are a helpful assistant.",
        *,
        max_tokens=8000,
        model="gpt-4o",
        tools=None,
        backend=None,
    ):
        if max_tokens < 1:
            raise ValueError("max_tokens must be >= 1")
        self.max_tokens = max_tokens
        self.model = model
        self.tools = tools
        self.backend = backend
        super().__init__(system_prompt)

    def __iadd__(self, other):
        super().__iadd__(other)
        self._trim()
        return self

    def _trim(self):
        prefix, rest = self._split_messages()
        kw = {"model": self.model, "backend": self.backend}
        tools_n = tools_tokens(self.tools, **kw) if self.tools else 0
        prefix_tokens = count_tokens(prefix, **kw)
        limit = max(self.max_tokens - tools_n, prefix_tokens)

        if limit < prefix_tokens:
            self.messages = prefix
            return

        while rest and count_tokens(prefix + rest, **kw) > limit:
            rest = self._drop_oldest(rest)
        self.messages = prefix + rest

    def _split_messages(self):
        i = 0
        while i < len(self.messages) and self.messages[i].get("role") == "system":
            i += 1
        return self.messages[:i], self.messages[i:]

    def _drop_oldest(self, rest):
        if not rest:
            return rest
        msg = rest[0]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            i = 1
            while i < len(rest) and rest[i].get("role") == "tool":
                i += 1
            return rest[i:]
        return rest[1:]
