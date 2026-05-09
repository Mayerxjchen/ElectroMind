import os
from dataclasses import dataclass, field


@dataclass
class RunResult:
    content: str
    tool_calls: list = field(default_factory=list)
    usage: object | None = None

    @property
    def has_tool_calls(self):
        return len(self.tool_calls) > 0


class LLM:
    """Stateless wrapper: forwards to the model; no history (caller builds ``messages``)."""

    API_KEY_ENV_VAR = "OPENAI_API_KEY"
    BASE_URL = "https://api.openai.com"

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

    async def invoke(self, messages, tools=None):
        kwargs = {
            "model": self.model_id,
            "messages": messages,
            "stream": False,
            **self.request_kwargs,
        }
        if tools:
            kwargs["tools"] = tools

        response = await self.client.chat.completions.create(**kwargs)
        if not response.choices:
            return RunResult(content="", tool_calls=[], usage=response.usage)

        message = response.choices[0].message
        content = message.content or ""
        if not message.tool_calls:
            return RunResult(content=content, tool_calls=[], usage=response.usage)

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
        return RunResult(content=content, tool_calls=tool_calls, usage=response.usage)


def _dummy_openai_sdk_key(existing):
    """OpenAI client often rejects an empty api_key; local servers rarely need a real secret."""
    if existing is not None and str(existing).strip():
        return existing.strip()
    return "not-needed"


class Ollama(LLM):
    """本地 `Ollama` 的 OpenAI 兼容路由（`/v1`）。

    见：<https://github.com/ollama/ollama/blob/main/docs/openai.md>

    ``model_id`` 需与你在本机 `ollama run` / `ollama pull` 的名称一致；
    ``OLLAMA_API_KEY`` 可选用（若无则占位 key）。"""

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
    """vLLM `--api-server` OpenAI Chat Completions 兼容入口（默认 `:8000/v1`）。

    端口与 `--host` / `--model` 以你进程为准；
    ``VLLM_API_KEY``（或显式 ``apikey=``），无则占位。"""

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
    """SGLang OpenAI-compatible HTTP server（常见 ``:30000/v1``）。

    启动端口以官方文档 `/sgl-workspace/router` 等说明为准；
    ``SGLANG_API_KEY``（或 ``apikey=``），无则占位。"""

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
    """DeepSeek（OpenAI 兼容 Chat Completions）。

    官方说明：<https://api-docs.deepseek.com/zh-cn/>

    Key：环境变量 ``DEEPSEEK_API_KEY``，或在平台申请：https://platform.deepseek.com/api_keys
    """

    API_KEY_ENV_VAR = "DEEPSEEK_API_KEY"
    BASE_URL = "https://api.deepseek.com"

    def __init__(self, model_id="deepseek-v4-flash", **kwargs):
        super().__init__(model_id, **kwargs)
