# examples/v4runner

pagentv4 使用示例，按复杂度递进：

| 示例 | 展示 |
|------|------|
| [quickstart.py](quickstart.py) | `Runner.open()` 打开 thread，跑一轮 |
| [multi_turn.py](multi_turn.py) | 同一 thread 里多次 `runner.run()` 做多轮对话 |
| [tools.py](tools.py) | 工具调用完整事件流：`ToolCallBegin` / `ToolResult` / `TurnEnd` 等 |
| [return_types.py](return_types.py) | 同一次调用，`text` / `message` / `acp` / `event` 四种投影对比 |
| [sandbox_session.py](sandbox_session.py) | local sandbox + 文件/命令工具 |
| [repl.py](repl.py) | 交互式 REPL：不带参数新建 `thread-<时间戳>`，`--thread-id foo` 续上已有的 |
| [concurrent_repl.py](concurrent_repl.py) | 底栏固定输入 REPL（与默认 `uv run pagent` 相同） |

实现位于 `src/app/`，与 `uv run pagent` / `uv run python -m app` 相同。

## 运行

```bash
export DEEPSEEK_API_KEY="your-key"
uv run pagent                              # 新建 thread
uv run pagent --thread-id demo             # 续聊
uv run python -m examples.v4runner.repl
uv run pagent                              # TTY 默认底栏固定输入
uv run pagent --blocking                   # 阻塞模式（跑完再输入）
uv run python -m examples.v4runner.concurrent_repl
uv run python -m examples.v4runner.quickstart
uv run python -m examples.v4runner.multi_turn
uv run python -m examples.v4runner.tools
uv run python -m examples.v4runner.return_types
uv run python -m examples.v4runner.sandbox_session
```

## 分层速查

```python
runner = await Runner.open(
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
