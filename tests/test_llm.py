import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pagent import LLM, DeepSeek, Ollama, Sglang, Vllm


def make_llm(response):
    llm = LLM.__new__(LLM)
    llm.model_id = "test-model"
    llm.request_kwargs = {}
    create = AsyncMock(return_value=response)
    llm.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    return llm, create


def test_invoke_returns_content_and_usage():
    usage = SimpleNamespace(prompt_tokens=3, completion_tokens=5, total_tokens=8)
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content="hello", tool_calls=None))
        ],
        usage=usage,
    )
    llm, create = make_llm(response)

    result = asyncio.run(llm.invoke([{"role": "user", "content": "hi"}]))

    assert result.content == "hello"
    assert result.tool_calls == []
    assert result.has_tool_calls is False
    assert result.usage is usage
    assert create.await_args.kwargs == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
    }


def test_invoke_returns_tool_calls_and_passes_tools():
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call_1",
                            type="function",
                            function=SimpleNamespace(
                                name="get_weather",
                                arguments='{"city":"beijing"}',
                            ),
                        )
                    ],
                )
            )
        ],
        usage=None,
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather",
                "parameters": {"type": "object"},
            },
        }
    ]
    llm, create = make_llm(response)

    result = asyncio.run(
        llm.invoke([{"role": "user", "content": "weather"}], tools=tools)
    )

    assert result.content == ""
    assert result.has_tool_calls is True
    assert result.tool_calls == [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "get_weather",
                "arguments": '{"city":"beijing"}',
            },
        }
    ]
    assert result.usage is None
    assert create.await_args.kwargs["tools"] == tools


def test_invoke_empty_choices():
    usage = SimpleNamespace(prompt_tokens=1, completion_tokens=0, total_tokens=1)
    response = SimpleNamespace(choices=[], usage=usage)
    llm, _ = make_llm(response)
    result = asyncio.run(llm.invoke([{"role": "user", "content": "x"}]))
    assert result.content == ""
    assert result.tool_calls == []
    assert result.usage is usage


def test_deepseek_provider_defaults():
    ds = DeepSeek(apikey="sk-test")
    assert ds.model_id == "deepseek-v4-flash"
    assert DeepSeek.API_KEY_ENV_VAR == "DEEPSEEK_API_KEY"
    assert "deepseek.com" in ds.base_url


def test_local_providers_default_base_urls():
    om = Ollama("phi4")
    assert om.model_id == "phi4"
    assert ":11434" in om.base_url and om.apikey == "not-needed"

    vv = Vllm("Meta-Llama-3-8B-Instruct")
    assert ":8000" in vv.base_url and vv.apikey == "not-needed"

    sg = Sglang("Qwen2.5-7B-Instruct")
    assert ":30000" in sg.base_url and sg.apikey == "not-needed"


def test_local_providers_respect_explicit_api_key():
    assert Vllm("m", apikey="real").apikey == "real"


def test_local_providers_optional_env_key(monkeypatch):
    monkeypatch.setenv(Vllm.API_KEY_ENV_VAR, "vk")
    v = Vllm("x")
    assert v.apikey == "vk"
