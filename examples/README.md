# examples

示例按能力分目录放置，根目录只保留分类入口。

| 目录 | 内容 |
|------|------|
| `app/` | 终端应用入口 wrapper；正式使用优先运行 `uv run pagent` |
| `pagentv4/runner/` | `Runner.create()`、多轮、工具、return type、sandbox |
| `pagentv4/thread_based/` | `ChatRunner` / `CodeRunner` / thread-based runner 选择指南 |
| `pagentv4/vanilla/` | 无持久化、无 sandbox 的 `VanillaRunner` |
| `wire_browser/` | Wire NDJSON + browser UI |
| `eval/` | 评测和对比脚本 |

常用命令：

```bash
uv run pagent
uv run python -m examples.pagentv4.thread_based.conversation_only
uv run python -m examples.pagentv4.thread_based.code_runner
uv run python -m examples.pagentv4.runner.return_types
uv run --with fastapi --with uvicorn python examples/wire_browser/server.py
```
