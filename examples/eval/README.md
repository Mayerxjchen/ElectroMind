# examples/eval

用当前 pagentv4 Runner 做测评 / benchmark 的示例。

| 示例 | 内容 |
|------|------|
| [runners_demo.py](runners_demo.py) | `VanillaRunner` / `ChatRunner` / `CodeRunner` 各跑一例 |
| [gsm8k_compare.py](gsm8k_compare.py) | GSM8K 小子集：无工具 vs `calc` 工具对比 |

## API

```python
from pagentv4 import AgentCore, ChatRunner, CodeRunner, DeepSeek, VanillaRunner

# 无持久化、无 sandbox
runner = VanillaRunner(AgentCore(DeepSeek("deepseek-v4-flash"), system="..."))
ans = "".join([text async for text in runner.run(question, return_type="text")])

# conversation 持久化
runner = ChatRunner(AgentCore(DeepSeek("deepseek-v4-flash"), system="..."), thread_id="eval")
try:
    ans = "".join([text async for text in runner.run(question, return_type="text")])
finally:
    await runner.close()

# sandbox 文件/命令能力；第一次 run 前自动初始化 sandbox
runner = CodeRunner(
    AgentCore(DeepSeek("deepseek-v4-flash"), system="..."),
    thread_id="eval-code",
    backend="local",
)
try:
    ans = "".join([text async for text in runner.run(task, return_type="text")])
finally:
    await runner.close()
```

## 运行

```bash
export DEEPSEEK_API_KEY="your-key"
uv run python -m examples.eval.runners_demo
uv run --with datasets python -m examples.eval.gsm8k_compare
uv run --with datasets python -m examples.eval.gsm8k_compare --sample hard --limit 30 -v
uv run --with datasets python -m examples.eval.gsm8k_compare --sample head --limit 10
```
