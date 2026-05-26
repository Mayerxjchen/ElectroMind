# Providers & API keys

Language: [中文](/zh/guide/providers) | English

pagent talks to any server that implements **OpenAI Chat Completions** (`/v1/chat/completions`).

## Built-in classes

| Class | Default model (examples) | Environment variable |
|-------|------------------------|----------------------|
| `LLM("gpt-4o-mini")` | as passed | `OPENAI_API_KEY` |
| `DeepSeek("deepseek-v4-flash")` | as passed | `DEEPSEEK_API_KEY` |
| `Ollama("llama3.2")` | as passed | optional `OLLAMA_API_KEY` |
| `Vllm`, `Sglang` | as passed | provider-specific |

```python
from pagent import DeepSeek, LLM, Ollama

llm = LLM("gpt-4o-mini")
llm = DeepSeek("deepseek-v4-flash")
llm = Ollama("llama3.2")   # http://127.0.0.1:11434/v1
```

## Reasoning models

Some providers expose **`reasoning_content`** (e.g. DeepSeek). Use `reasoning_effort` in `run_kwargs` and handle `ReasoningDelta` when streaming. See [Reasoning streams](/reasoning).

## Optional extras

```bash
pip install "pagent[search]"    # web_search tool (ddgs)
pip install "pagent[tokens]"    # HuggingFace tokenizers for some models
```
