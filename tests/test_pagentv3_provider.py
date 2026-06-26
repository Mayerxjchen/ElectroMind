from pagentv3 import Ollama, Sglang, Vllm


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
