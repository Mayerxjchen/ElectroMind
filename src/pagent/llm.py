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
