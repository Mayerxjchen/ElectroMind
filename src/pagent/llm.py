import os
from dataclasses import dataclass, field


@dataclass
class RunResult:
    content: str
    tool_calls: list[dict] = field(default_factory=list)
    usage: object | None = None

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class LLM:
    """Stateless LLM client wrapper.

    This class only forwards requests to the model inference service.
    It does not persist or manage conversation history/session state.
    The caller is responsible for storing and assembling message history.
    """

    API_KEY_ENV_VAR = "OPENAI_API_KEY"
    BASE_URL = "https://api.openai.com"

    def __init__(
        self,
        model_id: str,
        base_url: str | None = None,
        apikey: str | None = None,
        request_kwargs: dict | None = None,
    ) -> None:
        from openai import AsyncOpenAI

        resolved_base_url = (base_url or self.BASE_URL).strip()
        resolved_apikey = (apikey or self.get_api_key() or "").strip()

        self.base_url = resolved_base_url
        self.apikey = resolved_apikey
        self.client = AsyncOpenAI(api_key=self.apikey, base_url=self.base_url)
        self.model_id = model_id
        self.request_kwargs = request_kwargs or {}

    def get_api_key(self) -> str:
        return os.getenv(self.API_KEY_ENV_VAR)

    async def invoke(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> RunResult:
        kwargs: dict = {
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
        tool_calls: list[dict] = []
        if message.tool_calls:
            for tool_call in message.tool_calls:
                tool_calls.append(
                    {
                        "id": tool_call.id,
                        "type": tool_call.type,
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    }
                )

        return RunResult(content=content, tool_calls=tool_calls, usage=response.usage)


class DeepSeek(LLM):
    API_KEY_ENV_VAR = "DEEPSEEK_API_KEY"
    BASE_URL = "https://api.deepseek.com"

    def __init__(self, model_id: str = "deepseek-chat", **kwargs) -> None:
        super().__init__(model_id, **kwargs)


class VllmModel(LLM):
    API_KEY_ENV_VAR = "VLLM_API_KEY"
    BASE_URL = "http://localhost:30000/v1"

    def __init__(self, model_id: str = "Qwen/Qwen2.5-72B-Instruct", **kwargs) -> None:
        super().__init__(model_id, **kwargs)


class ChatAnywhereModel(LLM):
    API_KEY_ENV_VAR = "CHAT_ANYWHERE_API_KEY"
    BASE_URL = "https://api.chatanywhere.tech/v1"

    def __init__(self, model_id: str = "Qwen/Qwen2.5-7B-Instruct", **kwargs) -> None:
        super().__init__(model_id, **kwargs)
