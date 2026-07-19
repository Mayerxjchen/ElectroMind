import pytest

from pagentv4 import Kimi, LongCat, MiMo, Ollama, Provider, Sglang, Vllm


def test_provider_uses_dummy_api_key_when_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    provider = Provider("test-model")

    assert provider.apikey == "not-needed"


def test_local_providers_use_dummy_api_key_when_missing(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("VLLM_API_KEY", raising=False)
    monkeypatch.delenv("SGLANG_API_KEY", raising=False)

    ollama = Ollama("gemma4")
    vllm = Vllm("test-model")
    sglang = Sglang("test-model")

    assert ollama.apikey == "not-needed"
    assert vllm.apikey == "not-needed"
    assert sglang.apikey == "not-needed"


def test_local_providers_respect_explicit_api_key():
    assert Vllm("test-model", apikey="real").apikey == "real"


def test_local_providers_use_env_api_key(monkeypatch):
    monkeypatch.setenv("VLLM_API_KEY", "vk")

    assert Vllm("test-model").apikey == "vk"


def test_provider_rejects_reserved_request_kwargs():
    with pytest.raises(TypeError, match="reserved keys"):
        Provider("test-model", apikey="dummy", request_kwargs={"stream": False})


def test_provider_rejects_multiple_reserved_request_kwargs():
    with pytest.raises(TypeError, match="reserved keys"):
        Provider(
            "test-model",
            apikey="dummy",
            request_kwargs={"model": "x", "messages": []},
        )


def test_provider_rejects_tools_in_request_kwargs():
    with pytest.raises(TypeError, match="reserved keys"):
        Provider("test-model", apikey="dummy", request_kwargs={"tools": []})


@pytest.mark.asyncio
async def test_provider_rejects_reserved_run_kwargs():
    provider = Provider("test-model", apikey="dummy")

    with pytest.raises(TypeError, match="reserved keys"):
        await provider.complete([], stream=False)


@pytest.mark.asyncio
async def test_provider_rejects_model_run_kwargs():
    provider = Provider("test-model", apikey="dummy")

    with pytest.raises(TypeError, match="reserved keys"):
        await provider.complete([], model="override")


@pytest.mark.asyncio
async def test_provider_requests_include_usage(monkeypatch):
    captured: dict = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)

            async def stream():
                if False:
                    yield None

            return stream()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    provider = Provider("test-model", apikey="dummy")
    monkeypatch.setattr(provider, "client", FakeClient())

    await provider.complete([{"role": "user", "content": "hi"}])

    assert captured["stream_options"] == {"include_usage": True}


def test_hosted_providers_use_env_api_key(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "mk")
    monkeypatch.setenv("MIMO_API_KEY", "mm")
    monkeypatch.setenv("LONGCAT_API_KEY", "lc")

    assert Kimi("kimi-k2.5").apikey == "mk"
    assert MiMo("mimo-v2-pro").apikey == "mm"
    assert LongCat("LongCat-2.0-Preview").apikey == "lc"


def test_hosted_providers_default_base_url():
    assert Kimi("kimi-k2.5", apikey="x").base_url == "https://api.moonshot.cn/v1"
    assert MiMo("mimo-v2-pro", apikey="x").base_url == "https://api.mimo-v2.com/v1"
    assert (
        LongCat("LongCat-2.0-Preview", apikey="x").base_url
        == "https://api.longcat.chat/openai/v1"
    )


def test_hosted_providers_allow_base_url_override():
    provider = LongCat(
        "LongCat-2.0-Preview",
        base_url="https://proxy.example.com/openai/v1",
        apikey="x",
    )
    assert provider.base_url == "https://proxy.example.com/openai/v1"
