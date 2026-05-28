# DuplexBus 设计说明

Agent 与 UI 客户端通过 **DuplexBus** 解耦：出站统一 `emit` Event，入站在 Agent 侧**按时机**检查 iwire。Bus 与 Agent 同生命周期；多轮 Run 共用一根 Bus。

---

## 核心原则

### 1. 出站：凡要给 UI 看的，都 `emit` Event

- 载荷一律是 **Event**（`pagent.events` + `pagent_live.live_events`）。
- 生产者（Agent 主循环、`ToolContext.emit`）只负责 **`emit` → `push_owire`**，不替 UI 消费 owire。
- UI 客户端**自己** `get_owire` / `wait_owire` 拉取并渲染；Agent 不从 owire 上取事件（避免与 UI 抢队列）。

```text
Agent / tool                    UI 客户端
    emit(event)                      │
         │                           │
         ▼                           ▼
    [ owire ]  ──── 客户端独占消费 ────► 展示 / Wire / CLI
```

### 2. 入站：UI `push_iwire`，Agent 在检查点读 iwire

- 用户操作、控制指令、会合回复等，UI 写入 **iwire**（`push_iwire`）。
- **Agent 不假设** iwire 会主动回调；在 Run 循环的**固定检查点**上调用 `poll_iwire(bus)`（内部 `get_iwire` 排空当前队列并分发）。
- 会合类回复（如 `HumanReply`）可走 `push_iwire` 里的 `wait_reply` 快捷路径；未命中 waiter 的事件留在 iwire 上，由下一次 `poll_iwire` 处理。

```text
UI 客户端                         Agent
    push_iwire(event)                  │
         │                           │
         ▼                           ▼
    [ iwire ]  ──── poll_iwire() ───► 分发 / 取消 / wait_reply
              （工具等待、Turn 间隙等检查点）
```

### 3. 职责边界

| 角色 | owire | iwire |
|------|-------|-------|
| **Agent / tool** | 只写（`emit` / `publish_owire`） | 在检查点读（`poll_iwire`） |
| **UI 客户端** | 只读 | 只写 |

---

## Event 与双线

方向由所走的线决定，**不是**两套类型系统：

| 线 | 方向 | 写入 | 读取 |
|----|------|------|------|
| **owire** | Agent → UI | `emit` / `publish_owire` | UI：`get_owire` / `wait_owire` |
| **iwire** | UI → Agent | UI：`push_iwire` | Agent：`poll_iwire`（`get_iwire`） |

当前 live 类型示例：

| 场景 | owire（emit） | iwire（push） |
|------|----------------|---------------|
| 流式输出 | `TextDelta`、`ReasoningDelta`、`RunEnd` … | — |
| 工具可见性 | `ToolCallBegin`、`ToolResult` | — |
| 向用户提问 | `HumanInputRequired` | `HumanReply` |
| 中止 Run | — | `CancelRun` |

会合键：工具场景用 `tool_call_id`；通用场景可用 `request_id`（同一约定）。

---

## 术语

| 术语 | 层级 | 含义 |
|------|------|------|
| **Agent** | 实现 | 长命运行体；Session、tools、`bus` |
| **Session** | 用户可见 | 对话记忆 |
| **Run** | 用户可见 | 用户一条输入 → `RunBegin` … `RunEnd` |
| **Turn** | 实现 | 一轮「模型 → 工具」 |
| **Step** | 实现 | Turn 内一次 LLM 调用 |
| **检查点** | 实现 | Agent 调用 `poll_iwire` 的时机 |

```text
Agent
  └── Run
        └── Turn：Step → ToolCall* → ToolResult*
        └── RunEnd
```

---

## Agent 检查 iwire 的时机

Agent **不**订阅 owire；**在以下时机**非阻塞扫描 iwire（`poll_iwire`，`get_iwire` 直到为空）：

| 检查点 | 时机 | 典型处理 |
|--------|------|----------|
| **工具等待** | `_emit_tool_events` 内，`invoke_tool` 任务未完成前 | `HumanReply` → `wait_reply`；`CancelRun` → `cancel_waits` |
| **Run 开始** | `arun_events` 入口 `reset_live(bus)` | 清空上轮队列、取消未完成会合 |
| **Run 结束** | `arun_events` 的 `finally` → `end_run` | `cancel_waits`；owire 留给 UI 排空 |
| *（可扩展）* | Turn 之间、Step 流式循环内 | `CancelRun`、`Steer` 等 |

工具等待循环示意：

```text
yield ToolCallBegin
task = create_task(invoke_tool)
while not task.done():
    poll_iwire(bus)      # ← Agent 看 iwire
    await asyncio.sleep(0)
output = await task
yield ToolResult
```

UI 侧并行：

```text
while run_active:
    event = await bus.wait_owire()
    render(event)
    if HumanInputRequired:
        push_iwire(bus, HumanReply(...))
```

---

## 出站：谁 emit、emit 什么

| 来源 | 方式 | 说明 |
|------|------|------|
| 主循环 | `arun_events` 内对每个 core Event `publish_owire` | `TextDelta`、`ToolCallBegin` 等与 core 一致 |
| 工具 | `ToolContext.emit(event)` | `HumanInputRequired`、自定义 UI 事件等 |
| 工具会合 | `emit(HumanInputRequired)` + `await wait_reply(id)` | 出站走 emit；入站 `HumanReply` 经 iwire 回到 `wait_reply` |

**禁止**：Agent 在 `_emit_tool_events` 里 `drain` owire 再 `yield` 给 UI（与「客户端自己消费 owire」冲突）。工具产生的 UI 事件只 `emit` 到 owire，由客户端读取。

---

## 会合（rendezvous）

以 `ask_user` 为例：

1. tool：`emit(HumanInputRequired { tool_call_id, question })` → owire
2. UI：`wait_owire` 收到 → 展示问题 → `push_iwire(HumanReply { tool_call_id, text })`
3. Agent：`push_iwire` 命中 `wait_reply(tool_call_id)`，tool 返回 text；若 tool 仍在等，检查点 `poll_iwire` 也会处理队列中的 `HumanReply`
4. 主循环继续，`ToolResult` 经 `publish_owire` 发出

```text
tool ──emit──► owire ──► UI
tool ◄──wait_reply── iwire ◄── push ── UI
         ▲
         └── poll_iwire（工具等待检查点，兜底）
```

---

## 生命周期

| 阶段 | owire | iwire |
|------|-------|-------|
| Agent 构造 | `LiveAgent.bus` 创建 | 同左 |
| Run 开始 | `reset_live(bus)` 清空（含 flush） | 同左 |
| Run 进行中 | Agent/tool 只写；UI 只读 | UI 只写；Agent 在检查点读 |
| Run 结束 | `end_run`：不 flush owire，UI 可继续排空 | `cancel_waits` |

---

## 策略

- owire、iwire 各自 FIFO 保序
- `DuplexBus(maxsize=0)` 默认无界；`maxsize>0` 时 `push_*` 满则 `QueueFull`（背压）
- `CancelRun`：`poll_iwire` / `push_iwire` 触发 `cancel_waits`，并应中止当前 Run（实现可逐步加强）
- 会合可超时；迟到 `HumanReply` 可忽略

---

## 参考实现

| 模块 | 职责 |
|------|------|
| `bus.py` | 队列 + `wait_owire` 唤醒 |
| `context.py` | `publish_owire`、`push_iwire`、`poll_iwire`、`wait_reply` |
| `agent.py` | `publish_owire` 镜像 core 事件；工具等待时 `poll_iwire` |
| `tools.py` | `ask_user` → `request_human` |
| `examples/demo2/cli.py` | UI 消费 owire、`push_iwire` 回复 |

交互示例见 [examples/demo2/README.md](../../examples/demo2/README.md)（猜人游戏）。
