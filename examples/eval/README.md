# examples/eval

用当前 pagentv4 Runner 做测评 / benchmark 的示例。

| 示例 | 内容 |
|------|------|
| [runners_demo.py](runners_demo.py) | `VanillaRunner` / `ChatRunner` / `CodeRunner` 各跑一例 |
| [gsm8k_compare.py](gsm8k_compare.py) | GSM8K 小子集：无工具 vs `calc` 工具对比 |
| [swe_bench_run.py](swe_bench_run.py) | SWE-bench_Lite 冒烟测试：`CodeRunner` 作 coding agent（20 题，分层评测） |

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

# SWE-bench_Lite 冒烟测试（CodeRunner 作 coding agent；数据 HF 直链下载，无需登录）
uv run --with pyarrow python -m examples.eval.swe_bench_run --limit 1 -v
uv run --with pyarrow python -m examples.eval.swe_bench_run --limit 20
uv run --with pyarrow python -m examples.eval.swe_bench_run --limit 20 --try-tests  # 含 best-effort 测试运行
```

### SWE-bench 状态分档

- `resolved`：agent patch + gold test_patch 在 fresh checkout 上让 FAIL_TO_PASS 全过（Tier1，需 `--try-tests`）
- `partial`：Tier1 环境正常但部分测试未过
- `patch-only`：Tier1 未跑或失败；看 patch 能否干净 apply + 与 gold 的文件重合（`file_jaccard`）/ 行相似度（`line_similarity`）
- `failed`：无 patch 或 patch 无法 apply

⚠️ 本机无 docker，无法用官方 `sweb.eval` 测试镜像。Tier1 在宿主机用 `venv + pip install -e .` 构建 best-effort 环境，存在 Python 版本不匹配、C 扩展编译失败等问题。`resolved` 率为下界，**不可与官方 leaderboard 对比**；`patch-only` 档的结构指标更可靠。
