"""OpenAI-compatible provider — stateless HTTP only."""

from __future__ import annotations

import os


class Provider:
    API_KEY_ENV_VAR = "OPENAI_API_KEY"
    BASE_URL = "https://api.openai.com"

    def __init__(self, model_id: str, base_url=None, apikey=None, request_kwargs=None):
        from openai import AsyncOpenAI

        resolved_base_url = (base_url or self.BASE_URL).strip()
        resolved_apikey = (
            apikey if apikey is not None else os.getenv(self.API_KEY_ENV_VAR) or ""
        ).strip()

        self.base_url = resolved_base_url
        self.apikey = resolved_apikey
        self.client = AsyncOpenAI(api_key=self.apikey, base_url=self.base_url)
        self.model_id = model_id
        self.request_kwargs = request_kwargs or {}

    async def complete(self, messages: list[dict], tools=None, **run_kwargs):
        kwargs = {
            "model": self.model_id,
            "messages": messages,
            "stream": True,
            **self.request_kwargs,
            **run_kwargs,
        }
        if tools:
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
