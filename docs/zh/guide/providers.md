# 模型与 API Key

语言： [中文](/zh/guide/providers) | [English](/guide/providers)

pagent 通过 **OpenAI Chat Completions** 兼容接口（`/v1/chat/completions`）调用模型。

## 内置 Provider

| 用法 | 示例模型 | 环境变量 |
|------|----------|----------|
| `LLM("gpt-4o-mini")` | 参数指定 | `OPENAI_API_KEY` |
| `DeepSeek("deepseek-v4-flash")` | 参数指定 | `DEEPSEEK_API_KEY` |
| `Ollama("llama3.2")` | 参数指定 | 可选 `OLLAMA_API_KEY` |
| `Vllm`、`Sglang` | 参数指定 | 视部署而定 |

```python
from pagent import DeepSeek, LLM, Ollama

llm = LLM("gpt-4o-mini")
llm = DeepSeek("deepseek-v4-flash")
llm = Ollama("llama3.2")   # http://127.0.0.1:11434/v1
```

## 思考过程（reasoning）

部分模型返回 **`reasoning_content`**（如 DeepSeek）。流式时用 `ReasoningDelta`，详见 [思考过程](/reasoning.zh-CN)。

## 可选依赖

```bash
pip install "pagent[search]"    # 内置 web_search
pip install "pagent[tokens]"    # 部分模型的 HF tokenizer
```
