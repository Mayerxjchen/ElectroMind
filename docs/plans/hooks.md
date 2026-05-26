# pagent Hooks 支持计划书

> 状态：草案（设计讨论用，尚未实现）
> 版本：2025-05
> 相关：[事件流](../events.md) · [Wire 协议](../wire.md) · [开发指南](../development.md)

## 1. 背景与目标

pagent 当前提供：

- **透明 `session.messages`**：给模型的 OpenAI 形态历史；
- **出站 `Event` / Wire**：给 UI 的只读时间线（`arun_events` / `arun_wire`）；
- **固定 Agent 循环**：`run` / `arun_events` 内串联 LLM 与工具，**没有**可插拔的横切逻辑。

实际集成里常见需求：

| 需求 | 今天怎么做 | 痛点 |
|------|------------|------|
| 工具调用前人工审批 | 在应用层包一层，不用 `Agent` 内置执行 | 要自己拆循环，重复事件语义 |
| 记录审计日志 / 计费 | 订阅 `arun_events` | 只能看，不能改参数或拦工具 |
| 注入上下文（RAG、策略） | 改 `session` 或 system prompt | 时机分散，易与循环脱节 |
| 取消长任务 | 中断 HTTP / 杀任务 | 库内无统一 cancel 点 |
| 限流、重试、fallback 模型 | 包 `LLM` 子类 | 可行但每个应用各写一套 |

**目标：** 在保持「小而可嵌入」的前提下，增加 **Hooks**——在循环关键节点挂自定义逻辑，支持 **观察、变更、短路（拒绝/跳过）、取消**，并与现有 **Event** 时间线对齐，而不是再造一套消息系统。

**非目标（本计划不覆盖）：**

- 内置 MCP、文件编辑、Shell、并行工具；
- 把 Cursor / Claude Code 的 `hooks.json` 原样搬进 pagent（可作为上层集成示例，见 §8）；
- 在 Wire 协议里做双向控制（仍建议应用层 HTTP/API，见 §6）。

---

## 2. 概念界定

```text
                    ┌─────────────────────────────────────┐
  用户 / 应用        │            Agent 循环                │
       │            │  Hook 点（可改、可拦、可取消）          │
       ▼            │       ↓                              │
  session ◄────────┤  LLM ◄──► tools                       │
       │            │       ↓                              │
       │            │  Event 流（只读事实，给 UI/日志）      │
       └───────────►│  arun_events / arun_wire ──► 前端    │
                    └─────────────────────────────────────┘
```

| 机制 | 方向 | 职责 |
|------|------|------|
| **Session** | 持久状态 | 模型可见的消息历史 |
| **Hook** | 循环内、同步/异步回调 | 在步骤**之前/之后**介入，可改上下文或决策 |
| **Event** | 出站广播 | 描述「发生了什么」，供 UI 渲染与落盘 |
| **Wire** | Event 的序列化 | 非 Python 消费者；**不**承载入站控制 |

原则：**Event 继续只做事实推送；需要「能不能执行」的语义放在 Hook。**

---

## 3. 典型用例（按优先级）

### P0 — 第一版就要能表达

1. **工具前审批（PreTool）**
   看到 `name` + `arguments`，返回 `allow` / `deny` + 可选替换结果；deny 时写入 `role: tool` 错误信息或跳过执行。

2. **运行级观察（OnEvent）**
   每个 `Event` 发出前/后跑回调（审计、metrics），**默认不改变**事件（与 `arun_events` 消费等价，但在库内统一）。

3. **取消（Cancel）**
   `asyncio` 协作式取消：在 turn 之间、`invoke_stream` 迭代间检查 token；Hook 或外部 `RunController.cancel()` 触发。

### P1 — 第二版

4. **LLM 前注入（PreLLM）**
   只读或追加 ephemeral 消息（如检索片段）；需明确是否写回 `session`（默认：仅当次调用可见的 `extra_messages`）。

5. **Run / Turn 边界（RunBegin/End, TurnBegin/End）**
   统计、压缩触发（与 `CompactingSession` 配合）、自定义 `max_turns` 动态调整。

6. **工具后处理（PostTool）**
   改写 tool 结果（脱敏、截断、结构化），再写 `session`。

### P2 — 按需

7. **Steer（中途用户插话）**
   队列里压入新 `user` 消息，打断当前 turn 策略（需定义与 `max_turns` 的关系）。

8. **LLM 包装（Pre/Post LLM 完整 Step）**
   重试、换模型、缓存；也可继续推荐用户包装 `LLM` 子类，Hook 只暴露观测。

9. **与 IDE Hooks 桥接**
   文档 + 示例：FastAPI 收到 Cursor `preToolUse` JSON → 转 pagent `PreTool` 决策（§8）。

---

## 4. 设计原则

1. **默认零开销**：`hooks=None` 时行为与今天完全一致（同一套测试基线）。
2. **显式优于魔法**：Hook 用枚举名注册，不搞全局单例。
3. **可预测顺序**：同一点多 Hook 按注册顺序；文档写明「先注册先执行」。
4. **失败策略可配置**：`on_error="raise" | "log" | "ignore"`（默认 `raise`）。
5. **变更要可见**：若 Hook 改了 `session` 或 tool 结果，可选发出 **`HookApplied`** 类 Event（P1），便于 UI 调试。
6. **不替代 Event**：UI 仍以 `TextDelta` / `ToolCallBegin` 为主；Hook 专用事件保持最少。

---

## 5. Hook 点与 Agent 循环映射

对照 `src/pagent/agent.py` 当前流程：

```text
arun_events(user_input)
│
├─ [H1] before_run          session += user（或之前）
├─ RunBegin
│
└─ for turn in range(max_turns):
     ├─ [H2] before_turn
     ├─ TurnBegin
     ├─ [H3] before_llm_step     ← 可注入 extra_messages
     ├─ _stream_step_events / invoke_stream
     │    ├─ (stream) TextDelta / ReasoningDelta  → [H4] on_event（可选）
     │    └─ StepEnd
     ├─ [H5] after_llm_step        ← 可读 StepEnd，一般不改
     │
     ├─ 若无 tool_calls → TurnEnd(stopped=True) → [H6] after_turn → [H7] after_run → RunEnd
     │
     └─ for each tool_call:
          ├─ [H8] before_tool     ← 审批 / 改参
          ├─ ToolCallBegin
          ├─ execute / skip
          ├─ ToolResult
          └─ [H9] after_tool
     ├─ TurnEnd(stopped=False)
     └─ [H6] after_turn
```

`run()`（非流式）走同一套 Hook 点，但不产生 delta 类 Event（仅 Step 边界 + 工具事件可选）。

---

## 6. API 草案（Python）

### 6.1 注册方式

```python
from pagent import Agent, HookRegistry
from pagent.hooks import HookPoint, ToolDecision

hooks = HookRegistry()

@hooks.on(HookPoint.BEFORE_TOOL)
async def approve_tool(ctx):
    if ctx.tool_name == "shell" and not ctx.metadata.get("trusted"):
        return ToolDecision.deny("blocked by policy")
    return ToolDecision.allow()

agent = Agent(llm, session, tools=[...], hooks=hooks)
```

或轻量列表（第一版可二选一，避免两套 API）：

```python
agent = Agent(..., hooks=[before_tool_fn, audit_events_fn])
```

### 6.2 上下文对象 `HookContext`（草案字段）

| 字段 | 说明 |
|------|------|
| `point` | 当前 `HookPoint` |
| `agent` | `Agent` 实例 |
| `session` | 当前 `Session` |
| `turn` | 0-based |
| `user_input` | 本轮 run 的原始输入 |
| `tool_name` / `tool_call_id` / `arguments` | 工具 Hook 专用 |
| `step` | `StepEnd` 或等价结构（LLM 后） |
| `event` | `on_event` 时的事件 |
| `metadata` | 调用方传入的 `run(metadata={...})` |
| `cancelled` | 是否已请求取消 |

### 6.3 返回值（按 Hook 类型）

| Hook | 返回 | 效果 |
|------|------|------|
| `before_tool` | `ToolDecision` | `allow` / `deny(message)` / `replace_result(str)` |
| `before_llm_step` | `LLMStepInput` | 可选 `extra_messages: list[dict]` |
| `after_tool` | `str \| None` | `None` 保持原结果，否则替换 content |
| `on_event` | `Event \| None` | `None` 原样发出；非 `None` 替换（P1，慎用） |
| 其它 | `None` | 纯副作用 |

同步函数与 `async def` 均支持（运行时检测）。

### 6.4 取消

```python
controller = agent.run_controller()  # 或 run(..., controller=c)
async for ev in agent.arun_events("...", controller=controller):
    ...
controller.cancel()  # 设置 Event，下一检查点抛 CancelledError 或发 RunCancelled Event
```

检查点：`TurnBegin` 前、`_stream_step_events` 每 chunk 后、`before_tool` 前。

### 6.5 与 Wire 的边界

- **出站**：不变；`ToolCallBegin` 仍在执行前发出（审批 UI 可据此弹窗）。若工具被 deny，仍发 `ToolResult`，`content` 为拒绝原因。
- **入站**：Wire **不**增加 `jsonrpc` request；浏览器审批走应用 REST，服务端调用 `ToolDecision.deny/allow` 等价逻辑（内部走 Hook 或临时 handler）。

---

## 7. 模块与文件规划

```text
src/pagent/
  hooks.py          HookPoint, HookRegistry, HookContext, ToolDecision, ...
  agent.py          在现有循环插入调用；run() 与 arun_events() 共用私有 _run_loop
```

测试：

```text
tests/test_hooks.py       审批、deny、replace_result、取消、顺序、on_error
tests/test_hooks_events.py  Hook 与 Event 顺序一致性
```

文档：

```text
docs/hooks.md             用户指南（实现后）
docs/plans/hooks.md       本计划书
docs/agent-reference.md   实现后补充 Hook API 表
```

---

## 8. 分阶段路线图

### Phase 0 — 设计冻结（1 周）

- [ ] 评审本计划：Hook 点清单、返回值、与 Event 顺序
- [ ] 确认第一版仅 `async` 路径还是 `run()` 同步也要完整支持
- [ ] 写 `tests/test_hooks.py` 的 **期望行为** 用例（先红灯）

### Phase 1 — MVP（2–3 周）

- [ ] `HookRegistry` + `HookPoint.BEFORE_TOOL` / `AFTER_TOOL`
- [ ] `ToolDecision`：`allow` / `deny` / `replace_result`
- [ ] `arun_events` / `run` 共用 `_run_with_hooks`
- [ ] `RunController.cancel()` + 基础检查点
- [ ] `on_event` 只读审计（不改变事件）
- [ ] 文档 `docs/hooks.md` + `examples/hooks_tool_approval.py`

**验收：** wire_demo 可加「工具需点批准」示例（服务端 Hook，前端仍用现有 Wire）。

### Phase 2 — 上下文与可观测（2 周）

- [ ] `before_llm_step` + `extra_messages`
- [ ] `before_run` / `after_run` / `before_turn` / `after_turn`
- [ ] 可选 `HookApplied` Event
- [ ] `post_tool` 结果改写

### Phase 3 — 生态（按需）

- [ ] Steer 队列与文档
- [ ] Cursor `hooks.json` ↔ pagent 桥接示例（`.cursor/hooks/` 调本地 API）
- [ ] 若社区需要：声明式 `hooks.yaml` 加载器（**非**核心依赖）

---

## 9. 风险与开放问题

| 问题 | 选项 | 倾向 |
|------|------|------|
| `run()` 与 `arun_events()` 代码分叉 | 抽 `_run_loop` 单路径 | **单路径**，减少漂移 |
| Hook 修改 `session` 的可见性 | 仅 `before_*` 允许；`after_*` 只读 session | 文档写清，避免竞态 |
| `on_event` 能否改 Event | Phase 1 禁止；Phase 2 可选 | 默认禁止，防 UI 与 session 不一致 |
| 工具审批时 Event 顺序 | `ToolCallBegin` 在审批前还是后 | **审批前**发 `ToolCallBegin`，审批后发 `ToolResult`（与今天一致） |
| 线程安全 | 单 Agent 单 task | 文档声明：勿跨 task 共享 Agent |
| 性能 | Hook 列表为空快速返回 | `if not registry: ...` 原路径 |

---

## 10. 成功标准

- 不改 Hook 时，`pytest` 全绿且与当前 main 行为一致。
- 用 **<30 行** 应用代码实现「危险工具需 `metadata["approved"]`」。
- wire_demo 可选演示：一个工具默认 deny，POST `/api/approve` 后同 session 重试（示例级）。
- [agent-reference](../agent-reference.md) 与 [llms.txt](../../llms.txt) 在 Phase 1 后更新。

---

## 11. 参考

- 现有循环：`src/pagent/agent.py`
- 事件定义：`src/pagent/events.py`
- Wire 边界说明：`docs/wire.md`（入站控制 out of scope）
- IDE Hook 格式（集成参考，非 pagent 核心）：Cursor `hooks.json`、本仓库 `.claude/settings.json` 示例

---

**下一步建议：** 在 Issue / 讨论中确认 Phase 1 的 Hook 点是否过多；若希望极简，可只 ship **`before_tool` + `cancel` + `on_event`**，其余列入 Phase 2。
