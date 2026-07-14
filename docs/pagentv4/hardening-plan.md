# pagentv4 runtime 夯实计划

**范围**:`src/pagentv4/runtime/` 与 `src/pagentv4/sandbox/`。
**目标**:巩固刚落地的 runner 继承链重构,消除遗留重复与约定漂移,不引入新功能。

**分级定义**:

- **P0**:已存在的重复或漂移,继续累积会加重维护成本,优先处理。
- **P1**:约定不一致或职责越界,本迭代内处理。
- **P2**:可读性/组织层面,择机处理,不影响功能。

**验收总则**:每项完成需满足 `ruff check` + `ruff format --check` 干净、`pytest tests/` 全绿、涉及英文文档改动时同步 `llms-full.txt`。

---

## 现状快照(已核实)

重构后的继承链已收敛为单一循环骨架:

```
LoopAdapter                骨架:execute_tool / stream_agent_events / emit / emit_tool_events / run
  ├─ VanillaRunner         纯内存,after_* 用默认 no-op
  └─ BaseRunner            + thread / store / sandbox / skills,after_* 覆写为 flush
       ├─ ChatRunner       仅对话持久化(backend="none")
       ├─ CodeRunner       代码参数 / TOML 配置入口 + 懒初始化 sandbox
       └─ Runner           + inbound 控制面 + tool hooks
```

- 循环骨架已单份化,`run` 主体只在 [loop_adapter.py](../../src/pagentv4/runtime/loop_adapter.py) 写一次。
- REPL 实际使用带 inbound + hooks 的 `Runner.create()`(见 [repl.py](../../src/app/repl.py))。inbound / hooks 属于当前生产路径,但实现沿用重构前形态,尚未按新架构定型。
- 测试基线:`pytest tests/` 467 passed / 5 skipped。

---

## P0

### P0-1 三处资源初始化逻辑重复 ✅ 已完成

**现状**
「open sandbox → install skills → build system prompt → 组装 Agent」这一段在三处近乎逐字重复:

- [`open_code_resources`](../../src/pagentv4/runtime/code_runner.py)(code_runner.py L61-88)
- [`BaseRunner.from_spec`](../../src/pagentv4/runtime/base_runner.py)(base_runner.py L100-157)
- [`Runner.create`](../../src/pagentv4/runtime/runner.py)(runner.py L231-283)

三份都在拼 `computer_desc` / `skills_prompt` / `system_tail`,并把 `sandbox.tools()` 与外部 tools 合并。改动一处需同步另外两处,已是漂移温床。

**目标**
抽一个共享装配函数(输入 thread + skill_roots + tools + system 片段,输出 sandbox / skills / system_prompt / combined_tools),三处调用同一实现。

**验收**
三处初始化路径不再各自拼接 system prompt;`test_pagentv4_base_runner` / `test_pagentv4_code_runner` / `test_pagentv4_sandbox` 全绿。

**落地**
新增 `assemble_run_resources` + `RunResources`(base_runner.py),三处统一调用;删除 `open_code_resources`。`pytest tests/` 467 passed / 5 skipped,ruff 干净。

### P0-2 inbound 与 tool hooks 按新架构定型

**现状**
`Runner` 已继承 `BaseRunner`,但 inbound 检查点(`emit` 内 `_apply_inbound_drain`)、`RunCancelled` 捕获(`_event_source`)、hooks 调度(`run_tool_with_hooks`)三段逻辑沿用重构前实现,作为后续重构的参考保留(见 runner.py L126-229)。checkpoint / drain 机制与 `emit` 骨架的边界尚未定型。

**目标**
明确 inbound 与 hooks 作为「可叠加能力」挂进骨架的方式:界定 `emit` 检查点契约、`RunCancelled` 的传播路径、hooks 的前后置插入点,让 `Runner` 只覆写真差异点而不重写循环。保持公开 API(`runner.steer` / `cancel_run` / `permit_tool` / `deny_tool`、`Runner.create`)不变。

**验收**
`test_pagentv4_runner_inbound` / `test_pagentv4_inbound` / `test_pagentv4_tool_hooks` 全绿;REPL(`app/repl.py`、`app/tool_permit.py`)行为不变。

---

## P1

### P1-1 CodeRunner 初始化时序统一 ✅ 已完成

**现状**
`CodeRunner` 有三种初始化路径,时序不一致:`__init__` 懒初始化(首次 run 前),[`create`](../../src/pagentv4/runtime/code_runner.py)(L213-265)与 [`from_toml`](../../src/pagentv4/runtime/code_runner.py)(L267-314)立即初始化。使用者需理解三者差异才能避免误用。

**目标**
统一为单一构造入口 + 一个显式的初始化开关(懒 / 立即),`create` 与 `from_toml` 复用同一路径。

**验收**
`test_pagentv4_code_runner` 中懒初始化与立即初始化两条用例均覆盖且全绿。

**落地**
配置入口收敛到 `__init__`:`create` 改为 `cls(agent, **kwargs)` + `ensure_initialized` 的薄封装(不再复制 13 个参数声明);`from_toml` 解析出 spec 后直接复用 `create`,thread_id 兜底交给构造器。时序契约写进模块 docstring(懒 / 立即两条路径)。`pytest tests/` 467 passed / 5 skipped,ruff 干净。

### P1-2 Thread.open_sandbox 与 backend 映射解耦 ✅ 已完成

**现状**
[`Thread.open_sandbox`](../../src/pagentv4/ithread/local.py)(local.py L129-167)把 local / docker / podman / ssh 的配置映射逐分支写死在 Thread 内。新增 backend 需改 Thread。

**目标**
Thread 只负责准备 workdir 与 spec,后端选择与参数映射交给 sandbox 侧的工厂,Thread 不感知具体 backend 种类。

**验收**
新增一个 backend 分支时无需改动 `ithread/local.py`;`test_pagentv4_thread` / `test_pagentv4_sandbox` 全绿。

**落地**
backend 映射知识下沉到 sandbox 层:新增 `open_sandbox_for_spec(profile, workdir, *, label="")` 工厂([sandbox.py](../../src/pagentv4/sandbox/sandbox.py)),用 `SandboxProfile` Protocol 声明所需字段(ThreadSpec 结构上即满足),docker/podman 校验 image、ssh 校验 ssh_host 并解析 `~/.ssh/config` 都收敛于此。`Thread.open_sandbox` 简化为一次委托调用,不感知 backend 种类;新增 backend 只改工厂。`pytest tests/` 467 passed / 5 skipped,ruff 干净。

---

## P2

### P2-1 ThreadSpec 字段分组 ✅ 已完成

**现状**
[`ThreadSpec`](../../src/pagentv4/ithread/__init__.py)(L38-149)把 conversation / sandbox / ssh / agent 四个关注点平铺在一个 dataclass 里,`from_dict` / `to_dict` 手工分段维护。字段增删时映射易漏。

**目标**
按关注点拆成子配置(保持 `to_dict` / `from_dict` 的 TOML 兼容),或以更明确的分组表达四个 section。

**验收**
`thread.toml` 读写往返不变;`test_pagentv4_ithread` 全绿。

**落地**
字段保持扁平(消费方 `spec.backend` 等按属性读取不变),用 `toml_field(section, key, default)` 把每个字段的 `[section] key` 绑定进 dataclass metadata。`to_dict` / `from_dict` 改为从 `section_bindings()` 推导映射,新增字段只需声明一行,两个方向自动生效,不再有三处手工同步。`from_dict` 仍兼容旧的顶层扁平写法与未知键归入 `extra`。`pytest tests/` 467 passed / 5 skipped,ruff 干净。

### P2-2 backend 错误处理口径统一 ✅ 已完成

**现状**
后端异常风格不一致:`LocalBackend` 命令失败返回 `CommandResult(ok=False)`,`SshBackend` 未启动直接 `raise RuntimeError`。上层对两类反馈的处理路径不同。

**目标**
统一「命令级失败走 CommandResult、生命周期级错误走异常」的口径,并在文档中写明这条边界。

**验收**
`test_pagentv4_sandbox` / `test_pagentv4_ssh` 全绿;`docs/pagentv4/sandbox.md` 补充口径说明。

**落地**
在 [base.py](../../src/pagentv4/sandbox/base.py) 新增 `SandboxError` 基类与 `SandboxNotStartedError`,并把 `SandboxDeadError` 归到 `SandboxError` 之下,上层可用 `except SandboxError` 兜住整类「sandbox 不可用」。四类边界写进 `Backend` Protocol docstring:命令级失败走 `CommandResult(ok=False)`;未启动走 `SandboxNotStartedError`、start 失败走 `SandboxError`;配置不合法走 `ValueError`;文件语义级失败沿用 `FileNotFoundError` / `IsADirectoryError`。container / ssh backend 的「not started」与 start 环境失败改抛对应类型。新增三条契约测试,`docs/pagentv4/sandbox.md` 补错误处理表。`pytest tests/` 470 passed / 5 skipped,ruff 干净。

---

## 进度小结

P0-1 / P1-1 / P1-2 / P2-1 / P2-2 均已完成。仅剩 P0-2(inbound / hooks 按新架构定型),按用户要求延后,单独一个迭代处理。

---

## 执行顺序建议

1. **P0-1**(共享装配函数):收益最直接,先做能减少后续各项的改动面。
2. **P1-1 / P1-2**:依赖 P0-1 的统一装配,顺势收拢初始化时序与 backend 解耦。
3. **P0-2**(inbound / hooks 定型):独立且影响 REPL,单独一个迭代,配合回归测试。
4. **P2-1 / P2-2**:组织与口径层面,择机随手清理。
