# pagentv4 runtime 夯实计划

**范围**:`src/pagentv4/runtime/` 与 `src/pagentv4/sandbox/`。
**目标**:巩固 runner 继承链重构,消除遗留重复与约定漂移,不引入新功能。

**验收总则**:每项完成需满足 `ruff check` + `ruff format --check` 干净、`pytest tests/` 全绿、涉及英文文档改动时同步 `llms-full.txt`。

---

## 已完成

以下五项已落地并随代码提交,详情见对应 commit 与源码:

- **P0-1 三处资源初始化逻辑重复**:抽出 `assemble_run_resources` + `RunResources`([base_runner.py](../../src/pagentv4/runtime/base_runner.py)),三处统一调用,删除 `open_code_resources`。
- **P1-1 CodeRunner 初始化时序统一**:配置入口收敛到 `__init__`,`create` / `from_toml` 复用同一路径;懒 / 立即两条时序契约写进模块 docstring([code_runner.py](../../src/pagentv4/runtime/code_runner.py))。
- **P1-2 Thread.open_sandbox 与 backend 映射解耦**:backend 映射下沉到 `open_sandbox_for_spec` 工厂([sandbox.py](../../src/pagentv4/sandbox/sandbox.py)),`Thread.open_sandbox` 简化为委托调用。
- **P2-1 ThreadSpec 字段分组**:用 `toml_field(section, key, default)` 把 `[section] key` 绑定进 dataclass metadata,`to_dict` / `from_dict` 从 `section_bindings()` 推导([ithread/__init__.py](../../src/pagentv4/ithread/__init__.py))。
- **P2-2 backend 错误处理口径统一**:新增 `SandboxError` / `SandboxNotStartedError`([base.py](../../src/pagentv4/sandbox/base.py)),四类边界写进 `Backend` Protocol docstring,`docs/pagentv4/sandbox.md` 补错误处理表。

测试基线:`pytest tests/` 473 passed / 5 skipped。

---

## 待办

### P0-2 inbound 与 tool hooks 按新架构定型

**现状**
`Runner` 已继承 `BaseRunner`,但 inbound 检查点(`emit` 内 `_apply_inbound_drain`)、`RunCancelled` 捕获(`_event_source`)、hooks 调度(`run_tool_with_hooks`)三段逻辑沿用重构前实现,作为后续重构的参考保留(见 [runner.py](../../src/pagentv4/runtime/runner.py) L126-229)。checkpoint / drain 机制与 `emit` 骨架的边界尚未定型。REPL 实际使用带 inbound + hooks 的 `Runner.create()`(见 [repl.py](../../src/app/repl.py)),属当前生产路径。

**目标**
明确 inbound 与 hooks 作为「可叠加能力」挂进骨架的方式:界定 `emit` 检查点契约、`RunCancelled` 的传播路径、hooks 的前后置插入点,让 `Runner` 只覆写真差异点而不重写循环。保持公开 API(`runner.steer` / `cancel_run` / `permit_tool` / `deny_tool`、`Runner.create`)不变。

**验收**
`test_pagentv4_runner_inbound` / `test_pagentv4_inbound` / `test_pagentv4_tool_hooks` 全绿;REPL(`app/repl.py`、`app/tool_permit.py`)行为不变。

**说明**:独立且影响 REPL,单独一个迭代处理,配合回归测试。
