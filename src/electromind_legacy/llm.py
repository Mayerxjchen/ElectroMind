import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RunEnd:
    """One LLM step outcome, or the final result of ``Agent.run`` / ``arun_events``."""

    content: str
    tool_calls: list = field(default_factory=list)
    reasoning_content: str = ""
    usage: object | None = None

    @property
    def has_tool_calls(self):
        return len(self.tool_calls) > 0


class LLM:
    """Stateless wrapper: forwards to the model; no history (caller builds messages)."""

    API_KEY_ENV_VAR = "OPENAI_API_KEY"
    BASE_URL = "https://api.openai.com"
    # Keys managed by LLM itself — callers must not override these via run_kwargs.
    RESERVED_KEYS = frozenset({"model", "messages", "stream", "tools"})

    def __init__(self, model_id, base_url=None, apikey=None, request_kwargs=None):
        from openai import AsyncOpenAI

        resolved_base_url = (base_url or self.BASE_URL).strip()
        resolved_apikey = (apikey or self.get_api_key() or "").strip()

        self.base_url = resolved_base_url
        self.apikey = resolved_apikey
        self.client = AsyncOpenAI(api_key=self.apikey, base_url=self.base_url)
        self.model_id = model_id
        self.request_kwargs = request_kwargs or {}

    def get_api_key(self):
        return os.getenv(self.API_KEY_ENV_VAR)

    async def invoke(self, messages, tools=None, **run_kwargs):
        check_run_kwargs(run_kwargs)
        kwargs = {
            "model": self.model_id,
            "messages": messages,
            "stream": False,
            **self.request_kwargs,
            **run_kwargs,
        }
        if tools:
            kwargs["tools"] = tools

        response = await self.client.chat.completions.create(**kwargs)
        if not response.choices:
            return RunEnd(content="", tool_calls=[], usage=response.usage)

        message = response.choices[0].message
        content = message.content or ""
        reasoning_content = getattr(message, "reasoning_content", None) or ""
        if not message.tool_calls:
            return RunEnd(
                content=content,
                tool_calls=[],
                reasoning_content=reasoning_content,
                usage=response.usage,
            )

        tool_calls = [
            {
                "id": tc.id,
                "type": tc.type,
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in message.tool_calls
        ]
        return RunEnd(
            content=content,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
            usage=response.usage,
        )

    async def invoke_stream(self, messages, tools=None, **run_kwargs) -> AsyncIterator:
        check_run_kwargs(run_kwargs)
        kwargs = {
            "model": self.model_id,
            "messages": messages,
            "stream": True,
            **self.request_kwargs,
            **run_kwargs,
        }
        if tools:
            kwargs["tools"] = tools

        stream = await self.client.chat.completions.create(**kwargs)
        async for chunk in stream:
            yield chunk


def check_run_kwargs(kwargs):
    """Raise TypeError if caller tries to override keys managed by the LLM layer."""
    reserved = kwargs.keys() & LLM.RESERVED_KEYS
    if reserved:
        raise TypeError(
            f"run_kwargs must not include {sorted(reserved)}; "
            f"reserved keys: {sorted(LLM.RESERVED_KEYS)}"
        )


def _dummy_openai_sdk_key(existing):
    """OpenAI client often rejects empty api_key; local servers may not require a real key."""
    if existing is not None and str(existing).strip():
        return existing.strip()
    return "not-needed"


class Ollama(LLM):
    """Local Ollama OpenAI-compatible endpoint (usually /v1).

    Docs: <https://github.com/ollama/ollama/blob/main/docs/openai.md>
    model_id should match what you use with ollama run / ollama pull.
    OLLAMA_API_KEY is optional (dummy key is used when missing).
    """

    API_KEY_ENV_VAR = "OLLAMA_API_KEY"
    BASE_URL = "http://127.0.0.1:11434/v1"

    def __init__(self, model_id, base_url=None, apikey=None, request_kwargs=None):
        resolved = apikey if apikey is not None else self.get_api_key()
        super().__init__(
            model_id,
            base_url=base_url,
            apikey=_dummy_openai_sdk_key(resolved),
            request_kwargs=request_kwargs,
        )


class Vllm(LLM):
    """vLLM OpenAI Chat Completions endpoint (default :8000/v1).

    Port/host/model depend on your launch flags.
    VLLM_API_KEY (or explicit apikey=) is optional; dummy is used if missing.
    """

    API_KEY_ENV_VAR = "VLLM_API_KEY"
    BASE_URL = "http://127.0.0.1:8000/v1"

    def __init__(self, model_id, base_url=None, apikey=None, request_kwargs=None):
        resolved = apikey if apikey is not None else self.get_api_key()
        super().__init__(
            model_id,
            base_url=base_url,
            apikey=_dummy_openai_sdk_key(resolved),
            request_kwargs=request_kwargs,
        )


class Sglang(LLM):
    """SGLang OpenAI-compatible endpoint (common :30000/v1).

    Use your actual router/server port from your launch command.
    SGLANG_API_KEY (or apikey=) is optional; dummy is used if missing.
    """

    API_KEY_ENV_VAR = "SGLANG_API_KEY"
    BASE_URL = "http://127.0.0.1:30000/v1"

    def __init__(self, model_id, base_url=None, apikey=None, request_kwargs=None):
        resolved = apikey if apikey is not None else self.get_api_key()
        super().__init__(
            model_id,
            base_url=base_url,
            apikey=_dummy_openai_sdk_key(resolved),
            request_kwargs=request_kwargs,
        )


class DeepSeek(LLM):
    """DeepSeek OpenAI-compatible Chat Completions provider.

    Docs: <https://api-docs.deepseek.com/zh-cn/>
    API key: DEEPSEEK_API_KEY or <https://platform.deepseek.com/api_keys>
    """

    API_KEY_ENV_VAR = "DEEPSEEK_API_KEY"
    BASE_URL = "https://api.deepseek.com"

    def __init__(self, model_id="deepseek-v4-flash", **kwargs):
        super().__init__(model_id, **kwargs)
