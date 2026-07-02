# examples/v4runner

pagentv4 使用示例，按复杂度递进：

| 示例 | 展示 |
|------|------|
| [quickstart.py](quickstart.py) | 一行 `run_agent()` 尝鲜；Messages 内部临时创建，跑完即弃 |
| [multi_turn.py](multi_turn.py) | 手动持有 `Runner` + `Messages` 做多轮对话 |
| [tools.py](tools.py) | 工具调用完整事件流：`ToolCallBegin` / `ToolResult` / `TurnEnd` 等 |
| [return_types.py](return_types.py) | 同一次调用，`text` / `message` / `acp` / `event` 四种投影对比 |
| [sandbox_session.py](sandbox_session.py) | `Runner.session()` 一站式：自动造 Sandbox（伴身电脑）、绑好 6 个文件/命令工具，跑完自动关机 |
| [repl.py](repl.py) | 交互式 REPL：不带参数新建一条 thread，`--thread-id foo` 续上已有的；每条 thread 绑 Sandbox + 消息 + workspace，跨轮跨启动持久；内置 `/exit` `/pwd` `/ls` `/skills` `/history` |

## 运行

所有示例都需要 DeepSeek key：

```bash
export DEEPSEEK_API_KEY="your-key"
uv run python -m examples.v4runner.quickstart
uv run python -m examples.v4runner.multi_turn
uv run python -m examples.v4runner.tools
uv run python -m examples.v4runner.return_types
uv run python -m examples.v4runner.sandbox_session
uv run python -m examples.v4runner.repl
```

## 分层速查

```python
# 尝鲜：一行搞定
async for text in run_agent(agent, "hi", return_type="text"):
    ...

# 进阶：需要跨轮记忆 / 检查 messages / 定制 Runner 时
runner = Runner()
messages = Messages()
async for event in runner.arun(agent, "hi", messages):
    ...

# 需要文件/命令工具时：一站式，不用手动造 Sandbox
async for event in Runner().session(
    provider, "在 /home/agent 写一个 hello.txt",
    workspace_id="default",   # 落到 <cwd>/.pagent/workspaces/default/
):
    ...

# 需要跨调用记住历史时：Runner 注入 store + 带 conversation_id
runner = Runner(store=JsonlConversationStore())
async for event in runner.arun(agent, "hi", Messages(), conversation_id="demo"):
    ...
# 或者在 session 一站式糖里带 id
async for event in Runner(store=...).session(
    provider, "hi", workspace_id="default", conversation_id="demo",
):
    ...
```

Agent 是配置容器，Messages 是对话容器，Runner 是调度器+持久化门面，
Sandbox 是伴身电脑，ConversationStore 是对话档案柜。
`run_agent` 是「一次性 Runner + 一次性 Messages」的糖；
`Runner.session()` 是「Runner + Sandbox + 工具绑定」的糖，跑完自动关机；
`conversation_id` 让 Runner 自动 load 之前的记忆，并在每个 TurnEnd flush。
