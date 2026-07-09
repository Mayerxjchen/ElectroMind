# examples/pagentv4/runner

pagentv4 使用示例，按复杂度递进：

| 示例 | 展示 |
|------|------|
| [quickstart.py](quickstart.py) | `Runner.create()` 打开 thread，跑一轮 |
| [multi_turn.py](multi_turn.py) | 同一 thread 里多次 `runner.run()` 做多轮对话 |
| [tools.py](tools.py) | 工具调用完整事件流：`ToolCallBegin` / `ToolResult` / `TurnEnd` 等 |
| [return_types.py](return_types.py) | 同一次调用，`text` / `message` / `acp` / `event` 四种投影对比 |
| [sandbox.py](sandbox.py) | local sandbox + 文件/命令工具 |

交互式 REPL 示例在 `examples/app/`；正式入口是 `uv run pagent`。

## 运行

```bash
export DEEPSEEK_API_KEY="your-key"
uv run pagent                              # 新建 thread
uv run pagent --thread-id demo             # 续聊
uv run pagent                              # TTY 默认底栏固定输入
uv run pagent --blocking                   # 阻塞模式（跑完再输入）
uv run python -m examples.app.repl
uv run python -m examples.app.concurrent_repl
uv run python -m examples.pagentv4.runner.quickstart
uv run python -m examples.pagentv4.runner.multi_turn
uv run python -m examples.pagentv4.runner.tools
uv run python -m examples.pagentv4.runner.return_types
uv run python -m examples.pagentv4.runner.sandbox
```

## 分层速查

```python
runner = await Runner.create(
    "demo",
    provider,
    overrides={"backend": "local"},
    extra_system="你是助手。",
    tools=[my_tool],          # 可选：额外工具
)
try:
    async for event in runner.run("hi"):
        ...
    async for text in runner.run("again", return_type="text"):
        ...
finally:
    await runner.close()
```

Runner 与 thread / sandbox / messages 同生共死；消息自动持久化到 thread 目录下的 `messages.jsonl`。
