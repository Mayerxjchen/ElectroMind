# 架构

## 执行内核

自 v0.8 起，执行内核收敛为**唯一 Run 生命周期**（CLI 与 Desktop 是正式入口；
Wire 为 Desktop 的内部传输层）。

```text
CLI         Desktop
 │            │
 │        Wire（内部协议，非公开接口）
 │            │
 └────┬───────┘
ApplicationService（app/service.py，进程级共享）
          │
      RunEngine（electromind.engine — 唯一执行状态机）
   ┌──────┼───────────┬──────────────┐
ContextManager  ToolScheduler  PlanStore  ThreadSessionManager
   │              │            │            │
AgentCore      Sandbox      Runner      RunSnapshot
```

- **RunEngine**（`src/electromind/engine/run_engine.py`）是唯一 Run 状态事实源：
  cancel / steer / permit / deny 全部经它；事件带 per-thread 单调 `seq`；
  同一 Thread 同时最多一个可写 Run。
- **语义检查点**（`src/electromind/harness/checkpoints.py`）在循环的六个命名点
  （RUN_STARTED / BEFORE_MODEL / AFTER_MODEL / BEFORE_TOOL_BATCH /
  AFTER_TOOL_BATCH / BEFORE_FINALIZE）统一处理取消与立即输入注入。
- **Plan**（`src/electromind/execution/plan.py`）：`PlanState` / `PlanStore` /
  `StepVerifier`——已批准计划不可原地修改；无 Evidence 不得 COMPLETED；
  无验证器结果不得 VERIFIED。
- **幂等**（`src/electromind/execution/idempotency.py`）：外部副作用（提交/删除/
  上传）必须带 `IdempotencyKey`；同 key 重放原结果，状态未知进入
  RECONCILING 不盲目重试。
- **上下文与预算**（`src/electromind/context/`）：模型调用前 Token 估算与阈值
  检查，超限先压缩；Thread / Project / Artifact 三层记忆。
- **工具治理**（`execution/effects.py` / `tool_scheduler.py` / `permissions.py`）：
  工具必须声明 Effect；只读可并行、写与外部提交串行；审批绑定
  Thread/Run/ToolCall/Action/过期，跨域重放全部拒绝。
- **子 Agent**（`src/electromind/tools/delegate.py`）：结构化 `SubAgentResult`
  交付；委派深度默认 1、系统最大 2；token/工具调用/超时预算硬限制。
- **Artifact**（`src/electromind/artifacts/`）：`ArtifactManifest` +
  `ArtifactRegistry`，completed ≠ validated ≠ accepted 严格分离，SHA-256
  完整性校验与版本链（同 id 异 SHA → 旧版本 SUPERSEDED 保留）。
- **Provider 可靠性**（`core/capabilities.py` / `retry.py` / `budget.py`）：
  能力协商、指数退避重试（429/5xx/超时）、Run 级预算。

## 接口支持级别

| 接口 | 状态 |
|---|---|
| CLI | 正式支持——最完整、最稳定的基准入口 |
| Desktop | 正式支持——CLI 能力的图形化呈现，经 Wire 驱动 |
| HTTP | experimental，暂停开发（maintenance-only） |

边界原则：**CLI 是完整功能入口，Desktop 是 CLI 能力的图形化呈现，Wire 只是
Desktop 与 Core 的内部传输层**（不承诺长期兼容）。

## Sandbox

四种后端：`local`（默认，直接执行）/ `container`（自动探测 docker/podman）/
`docker` / `podman`（显式）/ `ssh`。容器后端统一走 `ContainerBackend`
（`src/electromind/sandbox/backends/container.py`）：bind mount 同一路径，
文件 API 与 exec 都落到容器侧，避免 Linux 跨 uid 写权限问题。

## Skills 系统

- 进程级共享目录服务（`skills/catalog_service.py`）：discovery → catalog →
  generation（内容或信任变化时 +1）
- 安装器（`skills/installer.py`）：git/本地/归档安装，固定来源 commit，
  安装 ≠ 信任（`trust_granted` 显式授予）
- 运行时快照按 Run 冻结（generation freeze）；面板实时目录来自
  `skills/list|reload` 响应

## HPC 模块

`src/electromind/hpc/`：`SubmissionStore`（JSONL 原子写 + flock 防竞态 +
`.bak` 恢复）、`reconcile.py`（squeue/sacct 查询，失败 → UNKNOWN 不猜测）。
查询经 rsess 注入的 `run(cmd)` 完成，不直接执行 ssh。
