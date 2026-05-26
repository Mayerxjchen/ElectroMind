# 模型跟 API Key

语言：四川话 | [English](/guide/providers) | [普通话](/zh/guide/providers) | [日本語](/ja/guide/providers)

pagent 走 **OpenAI Chat Completions** 兼容接口（`/v1/chat/completions`）喊模型。

## 内置 Provider

| 用法 | 示例模型 | 环境变量 |
|------|----------|----------|
| `LLM("gpt-4o-mini")` | 参数自己填 | `OPENAI_API_KEY` |
| `DeepSeek("deepseek-v4-flash")` | 参数自己填 | `DEEPSEEK_API_KEY` |
| `Ollama("llama3.2")` | 参数自己填 | 可选 `OLLAMA_API_KEY` |
| `Vllm`、`Sglang` | 参数自己填 | 看你咋个部署 |

```python
from pagent import DeepSeek, LLM, Ollama

llm = LLM("gpt-4o-mini")
llm = DeepSeek("deepseek-v4-flash")
llm = Ollama("llama3.2")   # http://127.0.0.1:11434/v1
```

## 脑壳转（reasoning）

有些模型会吐 **`reasoning_content`**（比如 DeepSeek）。流式用 `ReasoningDelta`，详见 [脑壳转](../reasoning)。

## 可选依赖

```bash
pip install "pagent[search]"    # 内置 web_search
pip install "pagent[tokens]"    # 部分模型的 HF tokenizer
```
