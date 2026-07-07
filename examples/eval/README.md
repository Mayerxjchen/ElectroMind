# examples/eval

用 pagentv4 三类 Runner 做测评 / benchmark 的示例。

| 示例 | Runner |
|------|--------|
| [runners_demo.py](runners_demo.py) | 三个 Runner 各跑一例 |
| [gsm8k_compare.py](gsm8k_compare.py) | GSM8K 小子集：Simple vs Agentic(+calc) 对比 |

## API

```python
from pagentv4 import RunConfig, SimpleQuestionAnswerRunner, AgenticRunner, CodeAgent

config = RunConfig(system="...", model="deepseek-v4-flash")

# 文章 + 问题，单轮 QA
runner = SimpleQuestionAnswerRunner(config)
ans = await runner.run(article + question)

# 自定义工具，无沙箱
runner = AgenticRunner(config, tools=[web_search])
ans = await runner.run(question, tools=[web_search])

# 完整沙箱（SWE-bench 等）
agent = CodeAgent(config, tools=[...])
ans = await agent.run(task)
await agent.close()
```

## 运行

```bash
export DEEPSEEK_API_KEY="your-key"
uv run python -m examples.eval.runners_demo
uv run --with datasets python -m examples.eval.gsm8k_compare
uv run --with datasets python -m examples.eval.gsm8k_compare --sample hard --limit 30 -v
uv run --with datasets python -m examples.eval.gsm8k_compare --sample head --limit 10
```
