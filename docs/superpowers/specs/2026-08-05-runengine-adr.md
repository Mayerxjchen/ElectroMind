# ADR: RunEngine 是唯一 Run 状态事实源

- 日期：2026-08-05
- 状态：已接受
- 关联规范：`docs/superpowers/specs/2026-08-05-runengine-unification.md`

## 背景

v0.7 之前存在两套执行控制面：`runtime/`（LoopAdapter 循环 + RunState
字符串相位 + InboundMailbox 事件轮询检查点）与 `harness/`（ThreadSessionManager
生命周期 + InboundCheckpoint 语义检查点 + RunSnapshot）。`app/wire.py`
同时驱动两者，Cancel/Approval/Steer 语义随入口漂移；恢复时无法确认
哪个状态是事实源。

## 决策

1. **`RunEngine`（`src/electromind/engine/run_engine.py`）是唯一 Run 生命周期实现**。
   CLI/Wire/HTTP/Desktop 全部经它；App 层禁止直接操作 `runner.inbound`。
2. **`ThreadSessionManager` 是唯一状态权威**：所有相位转换（含
   RUNNING_MODEL/RUNNING_TOOL/WAITING_APPROVAL 精细相位）走集中转换表
   `allowed_run_transitions()`；非法转换返回 False 或抛结构化错误。
3. **循环内只使用语义检查点**（`harness/checkpoints.InboundCheckpoint`）：
   六个命名检查点统一处理取消与立即输入注入；旧的
   `InboundMailbox`+`CheckpointPolicy` 事件轮询废弃（保留类以兼容，
   Runner 不再使用）；`InboundMailbox` 仅保留 permit/deny 等待语义。
4. **终态转换（complete/cancel/fail）与 workspace 释放由引擎统一完成**
   （try/finally 保证异常路径也收尾），wire/client 只做传输封装与
   事件编码。
5. **事件 `seq` 由 manager 的 per-thread 计数器统一分配**，传输层
   （broker/编码）只做封装。

## 后果

- 正面：Cancel/Approval/Resume 语义单一；三入口（CLI/Wire/HTTP）对
  相同输入产生一致状态转换（`tests/test_run_engine_consistency.py` 锁定）；
  异常路径不泄漏 RUNNING 状态。
- 代价：`runtime.RunState.phase` 字符串在引擎路径不再参与状态权威
  （保留为循环局部可观测信号）；wire.py 的 run_user_turn 成为薄适配器。
- 迁移：`harness/` 逐步并入 engine 语义（物理目录迁移后续进行）；
  旧 `runner.inbound.steer/cancel` 调用点已全部切换。

## 验证

- `tests/test_run_engine.py`（12）：状态机/控制面绑定/单 Run/seq/终态。
- `tests/test_run_engine_consistency.py`（4）：多入口一致性。
- 全量 1654 passed；66/66 Golden Tasks；Ruff 全绿。
