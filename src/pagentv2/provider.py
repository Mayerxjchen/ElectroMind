"""OpenAI-compatible provider — stateless HTTP only."""

import os
from collections.abc import Mapping
from typing import Any

from openai import AsyncOpenAI

RESERVED_KEYS = frozenset({"model", "messages", "stream", "tools"})


def check_run_kwargs(kwargs: Mapping[str, Any]) -> None:
    reserved = kwargs.keys() & RESERVED_KEYS
    if reserved:
        raise TypeError(
            f"run_kwargs must not include {sorted(reserved)}; "
            f"reserved keys: {sorted(RESERVED_KEYS)}"
        )


class Provider:
    API_KEY_ENV_VAR = "OPENAI_API_KEY"
    BASE_URL = "https://api.openai.com"

    def __init__(
        self,
        model_id: str,
        base_url: str | None = None,
        apikey: str | None = None,
        request_kwargs: Mapping[str, Any] | None = None,
    ) -> None:
        resolved_base_url = (base_url or self.BASE_URL).strip()
        resolved_apikey = (
            apikey if apikey is not None else os.getenv(self.API_KEY_ENV_VAR) or ""
        ).strip()

        self.base_url = resolved_base_url
        self.apikey = resolved_apikey
        self.client = AsyncOpenAI(api_key=self.apikey, base_url=self.base_url)
        self.model_id = model_id
        self.request_kwargs = dict(request_kwargs) if request_kwargs is not None else {}
        check_run_kwargs(self.request_kwargs)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **run_kwargs: Any,
    ):
        check_run_kwargs(run_kwargs)
        kwargs: dict[str, Any] = {
            **self.request_kwargs,
            **run_kwargs,
            "model": self.model_id,
            "messages": messages,
            "stream": True,
        }
        if tools is not None:
            kwargs["tools"] = tools

        return await self.client.chat.completions.create(**kwargs)


class DeepSeek(Provider):
    API_KEY_ENV_VAR = "DEEPSEEK_API_KEY"
    BASE_URL = "https://api.deepseek.com"


class Ollama(Provider):
    API_KEY_ENV_VAR = "OLLAMA_API_KEY"
    BASE_URL = "http://127.0.0.1:11434/v1"


class Vllm(Provider):
    API_KEY_ENV_VAR = "VLLM_API_KEY"
    BASE_URL = "http://127.0.0.1:8000/v1"


class Sglang(Provider):
    API_KEY_ENV_VAR = "SGLANG_API_KEY"
    BASE_URL = "http://127.0.0.1:30000/v1"
