# プロバイダと API Key

言語: 日本語 | [English](/guide/providers) | [简体中文](/zh/guide/providers) | [四川话](/sc/guide/providers)

pagent は **OpenAI Chat Completions**（`/v1/chat/completions`）を実装したサーバーに接続します。

## 組み込みクラス

| クラス | モデル例 | 環境変数 |
|--------|----------|----------|
| `LLM("gpt-4o-mini")` | 引数で指定 | `OPENAI_API_KEY` |
| `DeepSeek("deepseek-v4-flash")` | 引数で指定 | `DEEPSEEK_API_KEY` |
| `Ollama("llama3.2")` | 引数で指定 | 任意 `OLLAMA_API_KEY` |
| `Vllm`, `Sglang` | 引数で指定 | プロバイダ依存 |

```python
from pagent import DeepSeek, LLM, Ollama

llm = LLM("gpt-4o-mini")
llm = DeepSeek("deepseek-v4-flash")
llm = Ollama("llama3.2")   # http://127.0.0.1:11434/v1
```

## 推論（reasoning）モデル

一部プロバイダは **`reasoning_content`** を返します（例: DeepSeek）。`run_kwargs` の `reasoning_effort` と、ストリーム時の `ReasoningDelta` を参照。[推論ストリーム](../reasoning)

## オプション依存

```bash
pip install "pagent[search]"    # web_search
pip install "pagent[tokens]"    # 一部モデル用 HF tokenizer
```
