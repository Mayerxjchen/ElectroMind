# pagentv4 重构修复清单

**范围**:`src/pagentv4/`(~6600 行)。
**分级定义**:

- **P0**:结构性问题,已产生或必然产生行为不一致/维护阻塞,建议尽快处理。
- **P1**:显著冗余或约定不一致,本迭代或下个迭代内处理。
- **P2**:可读性/风格层面,可择机处理,不影响功能。

---

## P0

### P0-1 Runner 未继承 BaseRunner,LoopCoreAdapter 已存在三份实现并发生行为漂移

**问题**
`VanillaRunner`、`BaseRunner`、`Runner` 各自独立实现了同一套 `LoopCoreAdapter` 协议方法(`execute_tool` / `emit` / `stream_agent_events` / `emit_tool_events` / `after_continuing` / `after_run_end` / `run`)。其中 `ChatRunner`、`CodeRunner` 正确继承 `BaseRunner`,但功能最全的 [`Runner`](src/pagentv4/runtime/runner.py#L41) 不继承 `BaseRunner`,而是平行重写。`LoopCoreAdapter` 是 `Protocol`(duck typing),不提供共享实现。

**依据**

- [`Runner`](src/pagentv4/runtime/runner.py#L41) 与 [`BaseRunner`](src/pagentv4/runtime/base_runner.py#L45) 为平级类。
- `emit_tool_events` 已发生行为差异:[Runner 版](src/pagentv4/runtime/runner.py#L158-L186) 走 `run_tool_with_hooks`,[BaseRunner 版](src/pagentv4/runtime/base_runner.py#L109-L129) 直接 `execute_tool`。

**影响**
BaseRunner 的后续改动不会自动传导到 Runner,差异会持续累积。三份近重复实现增加维护成本与回归风险。

**建议**
让 `Runner` 继承 `BaseRunner`,将 inbound/cancel/checkpoint 与 tool hooks 抽成可叠加的能力(基类方法或 mixin),保留单一 adapter 实现作为默认。

#### 详细分析:三个 runner 的相同与不同

逐方法比对(`LoopCoreAdapter` 协议要求的 7 个方法 + 资源生命周期):

| 方法 | VanillaRunner | BaseRunner | Runner | 结论 |
|------|---------------|------------|--------|------|
| `execute_tool` | `tool.acall` | 同左 | 同左 | 三者逐字相同(假重复) |
| `stream_agent_events` | generate→append→to_event | 同左 | 同左 | 三者逐字相同(假重复) |
| `emit` | 透传 | 透传 | 透传 **+ inbound drain** | Vanilla=Base;Runner 多检查点 |
| `emit_tool_events` | 直接 `execute_tool` | 直接 `execute_tool` | 走 `run_tool_with_hooks` | Vanilla=Base;Runner 多 hooks |
| `after_continuing` / `after_run_end` | no-op | `flush` | `flush` | Vanilla 不持久化;Base=Runner |
| `run` 主体 | ensure→append→loop→project | 同左 | 同左,但包 `_events` 捕获 `RunCancelled` | Vanilla=Base;Runner 多 cancel 处理 |
| `close` | 无 | 关 store + sandbox 可选(None 守卫) | 关 store + sandbox 必有 | 资源生命周期不同 |

**为什么需要分开写(本质)**:三个类不是三个不同的引擎,而是「同一套循环骨架 + 4 个正交能力开关」的组合。当前把这 4 个开关的取值焊死成 3 个并列类,共享骨架(`execute_tool` / `stream_agent_events` / `run` 主体 / `emit` 透传)被复制 3 遍,漂移由此产生(`emit_tool_events` 已在 Runner 与 Base 之间分叉)。

| 能力轴 | Vanilla | Base | Runner |
|--------|---------|------|--------|
| ① inbound(steer / cancel / permit) | ✗ | ✗ | ✓ |
| ② tool hooks(before / after) | ✗ | ✗ | ✓ |
| ③ 持久化(thread / store / flush / close) | ✗ | ✓ | ✓ |
| ④ sandbox 必备 | ✗ | 可选 | ✓ |

**收敛方案**:抽 `LoopAdapter` 基类承载骨架,三类只覆写真差异点:

- `LoopAdapter`:`execute_tool` / `stream_agent_events` / `emit`(透传)/ `emit_tool_events`(直接执行)/ `run`(直接 loop)/ `after_*`(no-op 默认)。
- `BaseRunner(LoopAdapter)`:加 thread/store/sandbox/skills;覆写 `after_*`→flush;`close`(sandbox None 守卫);`from_spec`。
- `Runner(BaseRunner)`:加 inbound/hooks;覆写 `emit`(drain)/ `emit_tool_events`(hooks)/ `run`(RunCancelled);inbound 控制面;`create` 工厂。
- `VanillaRunner(LoopAdapter)`:仅 `__init__(agent, messages=)`,其余全继承,`after_*` 用默认 no-op。

消重后:`execute_tool` / `stream_agent_events` / `run` 主体 / `emit` 默认版从 3 份降为 1 份。公共 API(`Runner.create` / `runner.inbound` / `BaseRunner.from_spec` / `VanillaRunner(agent, messages=)` 等)保持不变。

---

### P0-2 `agent_restored.py` 为死代码

**问题**
[`core/agent_restored.py`](src/pagentv4/core/agent_restored.py) 定义的 `Agent` 类与 [`agent.py`](src/pagentv4/core/agent.py#L8) 中的 `AgentCore` 逐字相同,唯一差异是 import 写 `Provider` 还是 `ProviderProtocol`(`agent.py` 末尾另 `Agent = AgentCore` 别名)。

**依据**
全仓引用检索:`agent_restored` 命中 0 处。`core/__init__.py` 与顶层 `__init__.py` 的 `Agent`/`AgentCore` 均从 `agent.py` 导入。

**影响**
无功能影响,但属于重构残留,且 `Agent` / `AgentCore` 双名降低可读性。

**建议**
删除 [`agent_restored.py`](src/pagentv4/core/agent_restored.py),保留单一类定义与一个规范对外名。

---

## P1

### P1-1 `Runner.create` 与 `Runner.open` 完全等价

**问题**
[`Runner.open`](src/pagentv4/runtime/runner.py#L330-L353) 仅转调 `Runner.create`,参数列表完全一致,注释自述"兼容旧入口"。

**依据**
[runner.py:330-353](src/pagentv4/runtime/runner.py#L330-L353)。

**影响**
对外暴露两个等价入口,增加 API 面与文档负担。

**建议**
移除 `open`,或标记 `@deprecated` 后按版本删除。

---

### P1-2 `Messages` 的 append 合并与 export 折叠双重维护

**问题**
存储侧 [`__iadd__` + `can_merge_messages`](src/pagentv4/core/message.py#L249-L302) 在追加时合并相邻同 turn 同类型 assistant chunk;导出侧 [`to_openai`](src/pagentv4/core/message.py#L345-L424) 再次折叠所有 assistant chunk。两套逻辑覆盖范围不一致:append 合并仅处理 text/text、thinking/thinking,export 折叠覆盖全部。

**依据**
[`can_merge_messages`](src/pagentv4/core/message.py#L249-L266) 与 [`to_openai`](src/pagentv4/core/message.py#L381-L419)。

**影响**
任一侧 schema 变更时,另一侧需同步,存在隐性不一致风险。

**建议**
收敛为单一折叠点(建议保留 export 侧折叠,移除 append 侧合并),合并语义只在一处定义。

---

### P1-3 `ChatRunner.from_toml` 与 `CodeRunner.from_toml` 构造约定不一致

**问题**
[`ChatRunner.from_toml`](src/pagentv4/runtime/chat_runner.py#L99-L101) 使用 `instance = cls.__new__(cls)` 绕过 `__init__`,再手动调用 `BaseRunner.__init__`;而 [`CodeRunner.from_toml`](src/pagentv4/runtime/code_runner.py#L291-L301) 使用正常 `cls(..., spec=spec)` 路径。

**依据**
[chat_runner.py:99-101](src/pagentv4/runtime/chat_runner.py#L99-L101) 对比 [code_runner.py:291-301](src/pagentv4/runtime/code_runner.py#L291-L301)。

**影响**
`__new__` 绕过 `__init__` 对父类演化敏感;同一项目两种构造写法无统一约定。

**建议**
统一为 `cls(...)` 构造路径;如需区分 spec 来源,以构造参数(如 `spec=`)传入。

---

### P1-4 别名层放大对外 API 面

**问题**
[runtime/\_\_init\_\_.py:41-44](src/pagentv4/runtime/__init__.py#L41-L44) 定义 `ChatAgent=ChatRunner` / `CodeAgent=CodeRunner` / `ThreadAgent=Runner` / `VanillaAgent=VanillaRunner`,叠加 `core` 的 `Agent=AgentCore`。

**影响**
对每个概念暴露 2 个等价名,使用者难以判断规范写法。

**建议**
每个概念保留单一规范名,别名在文档中标注后逐步移除,或集中到一个显式 `aliases` 子模块。

---

### P1-5 `emit` 方法类型标注与实现不符

**问题**
[`Runner.emit`](src/pagentv4/runtime/runner.py#L130-L138) 与 [`LoopCoreAdapter.emit`](src/pagentv4/runtime/loop_core.py#L16) 标注为 `-> AsyncIterator`,但方法体为 `async def` + `yield`,实际是 async generator(应为 `AsyncGenerator`)。此外 `emit` 这层间接对 `BaseRunner` / `VanillaRunner` 是纯透传(仅 `Runner` 用它插入 inbound drain)。

**依据**
[runner.py:130-138](src/pagentv4/runtime/runner.py#L130-L138)、[base_runner.py:94-96](src/pagentv4/runtime/base_runner.py#L94-L96)、[vanilla.py:54-56](src/pagentv4/runtime/vanilla.py#L54-L56)。

**影响**
类型检查无法正确推断;透传层对非 inbound 实现是噪声。

**建议**
修正标注为 `AsyncGenerator`;评估仅在需要 inbound drain 的实现中保留 `emit` 覆写。

---

## P2

### P2-1 Provider 子类仅为常量差异

**问题**
[`Provider` 的 7 个子类](src/pagentv4/core/provider.py#L84-L116)(DeepSeek/Kimi/MiMo/LongCat/Ollama/Vllm/Sglang)各自仅覆盖 `API_KEY_ENV_VAR` 与 `BASE_URL` 两个类属性。

**影响**
配置被硬编码为类型,新增 provider 需新增类。

**建议**
改为 `Provider("deepseek")` + 预设注册表(`{"deepseek": {...}}`)。

---

### P2-2 `CodeRunner` lazy init 使 `self.agent` 语义可变

**问题**
[`CodeRunner`](src/pagentv4/runtime/code_runner.py#L142-L173) 保留 `base_agent`,在 `ensure_initialized` 时用 [`build_code_agent`](src/pagentv4/runtime/code_runner.py#L45-L57) 重建 `self.agent`。

**影响**
`self.agent` 在 `run` 前后可能为不同对象,`tools` 在初始化前为空。

**建议**
收敛为单一工厂路径(仅 `create`),或文档化"agent 在首次 run 前为占位"。

---

### P2-3 `loop_core` 末尾不可达分支

**问题**
[loop_core.py:168](src/pagentv4/runtime/loop_core.py#L168) `raise RuntimeError("unreachable")`。因 `AgentCore` 构造已拒绝 `max_turns < 1`,该行确实不可达。

**建议**
改为 `assert False, "unreachable"` 或直接移除循环外代码。

---

## 汇总

| 级别 | 编号 | 概要 | 主要文件 |
|------|------|------|----------|
| P0 | P0-1 | Runner 不继承 BaseRunner,adapter 三份实现且已漂移 | runtime/runner.py, base_runner.py, vanilla.py |
| P0 | P0-2 | agent_restored.py 死代码 | core/agent_restored.py |
| P1 | P1-1 | Runner.create / open 等价 | runtime/runner.py |
| P1 | P1-2 | Messages 双重折叠逻辑 | core/message.py |
| P1 | P1-3 | from_toml 构造约定不一致 | runtime/chat_runner.py, code_runner.py |
| P1 | P1-4 | 别名层放大 API 面 | runtime/\_\_init\_\_.py, core/\_\_init\_\_.py |
| P1 | P1-5 | emit 类型标注不符 | runtime/runner.py, loop_core.py |
| P2 | P2-1 | Provider 子类仅常量差异 | core/provider.py |
| P2 | P2-2 | CodeRunner lazy init 致 agent 可变 | runtime/code_runner.py |
| P2 | P2-3 | 不可达分支 | runtime/loop_core.py |

**建议顺序**:P0-2 与 P1-1、P2-3 为低风险删除/收敛动作,可先行;P0-1 为核心结构调整,建议在其基础上统一 P1-3、P1-5。

---

## 执行记录(2026-07-10)

按本清单完成批次一(P0)+ 批次二(P1/P2)。验证:`pytest tests/` **441 passed / 4 skipped**;`ruff check src/pagentv4` **All checks passed**。

### 已完成

| 编号 | 处理 |
|------|------|
| P0-1 | 新增 `runtime/loop_adapter.py` 承载循环骨架;BaseRunner / VanillaRunner / Runner 重组为 `LoopAdapter → BaseRunner → Runner`(Vanilla 直接继承 LoopAdapter)继承链;`run` 仅写一次,Runner 通过覆写 `_event_source` 注入 `RunCancelled`。消除三份 adapter 实现。 |
| P0-2 | 删除 `core/agent_restored.py` 及 `pyproject.toml` coverage omit 对应条目。 |
| P1-1 | 删除 `Runner.open`(= `create`,0 调用者)。 |
| P1-3 | `ChatRunner.__init__` 增加 `spec` 参数,`from_toml` 改用 `cls(...)` 正常构造,去掉 `cls.__new__`。 |
| P1-4 | 保留全部别名(测试硬断言 `XxxAgent is XxxRunner`),在 `runtime/__init__.py` 与 `core/agent.py` 加注释标注规范名。 |
| P1-5 | `loop_adapter.py` / `runner.py` / `loop_core.py` 的 async generator 方法返回标注 `AsyncIterator` → `AsyncGenerator`。 |
| P2-2 | `CodeRunner.ensure_initialized` docstring 文档化 `self.agent` 在首次 run 前为占位。 |
| P2-3 | `loop_core` 末尾 `raise RuntimeError("unreachable")` → `assert False, "unreachable"`。 |

### 降级(深入核实后调整结论)

**P1-2(Messages 双重折叠)**:原建议"移除 append 合并、保留 export 折叠"。核实发现 append 合并是被 `test_runner_accumulates_assistant_chunks_in_messages` 守护的有意设计——流式 reasoning/text delta 需累积成紧凑行(`data[2].content.text == "let me think"`)。它与 `to_openai` 折叠职责不同(append = 同类型 delta 累积,export = chunk → OpenAI dict 结构转换),并非纯冗余。改为在 `message.py` 的 `to_openai` 加分工注释,不移除合并逻辑。

**P2-1(Provider 子类)**:原建议"改为预设注册表"。核实发现 7 个子类是 public API,被 `app/repl.py`、`test_pagentv4_provider`(断言 `.apikey` / `.base_url` 类属性)、`test_pagentv4_thread_session` 直接使用。消除子类属破坏性变更,需先迁移调用方与测试。本次不改实现,列为独立迁移任务。
