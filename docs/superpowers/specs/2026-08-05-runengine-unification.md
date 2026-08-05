# RunEngine 统一执行内核 — 设计与实施规范

- 日期：2026-08-05
- 基线：`main` @ `cfd05ad`（0.7.20），1486 tests passed，coverage 78.2094%
- 目标文档：ElectroMind 改进验收条件（2026-08-05 /goal）
- 用户指示：**本阶段不做 HPC 与 CP2K→DeepMD 专项改造**（HPC Job 状态机、scheduler 对账、两条 Golden Workflow 由用户自行验收）；最终验收场景由用户完成。

## 1. 问题陈述

现状存在两套执行控制面：

1. **harness/**：`ThreadSessionManager`（run_id / event_seq / workspace lease / pending approval / recovery marker / 幂等输入）+ `InboundCheckpoint`（新语义检查点）+ `RunPhase` 集中状态机 + `RunSnapshot`（冻结）。
2. **runtime/**：`LoopAdapter` 循环骨架 + `RunState.phase`（非正式字符串相位：`waking_sandbox/idle/initializing/running/generating/calling/ended/tearing_down/closing`）+ 旧 `InboundMailbox/CheckpointPolicy` + `Runner` 的 steer/cancel/permit/deny。

`app/wire.py` 同时驱动 harness 与 `runner.run()/runner.inbound`，构成 P0-1 状态分叉。`execution/plan.py` 只有数据结构，不进入执行循环，构成 P0-2。`core/agent.py` 直发完整历史，无 Token 预算，构成 P0-3。

## 2. 目标架构（概念先行，物理迁移后续）

```text
CLI / Wire / HTTP / Desktop / VS Code
                 │
         Application Service（app/service.py，进程级共享）
                 │
              RunEngine（engine/run_engine.py — 唯一执行状态机）
       ┌───────────┼───────────────┐
  ContextManager  ToolScheduler  PlanStore
       │           │               │
      AgentCore   Sandbox        Runner(thin adapter)
       │           │
     Provider   ThreadSessionManager
```

原则：

- **RunEngine 是唯一 Run 状态事实源**。`runtime.RunState` 的字符串相位全部删除，改由 `RunPhase`（harness/state.py 扩展）表达；`RunState` 仅保留 turn/stop_reason 等循环局部数据。
- **App 层禁止直接修改 Run 状态**：所有生命周期操作（start/cancel/approve/permit/steer）都经 RunEngine 方法。
- **Semantic Checkpoint 唯一**：循环内只使用 `harness/checkpoints.InboundCheckpoint`；`runtime/inbound.py` 的旧 `InboundMailbox` 冻结为薄适配器或删除。
- **先统一概念和接口，再做物理迁移**：本阶段新增 `engine/` 模块并接线，不移动既有目录；`harness/` 逐步并入 engine 语义。

## 3. RunPhase 扩展（M1）

`harness/state.py` 的 `RunPhase` 扩展为：

```text
DORMANT → QUEUED → INITIALIZING → RUNNING_MODEL
                                ↘ WAITING_APPROVAL
                                ↘ RUNNING_TOOL
                                      ↓
RUNNING_MODEL/RUNNING_TOOL/WAITING_APPROVAL → FINALIZING → COMPLETED
                                              ↘ CANCELLED / FAILED / INTERRUPTED
```

集中转换表 `allowed_run_transitions()` 是唯一转换依据；非法转换抛 `RunPhaseError`（结构化）。`RUNNING_MODEL / RUNNING_TOOL / WAITING_APPROVAL` 由循环在检查点间声明（checkpoint 语义见下），`ThreadSessionManager` 不再只认粗粒度 RUNNING。

## 4. 统一 Semantic Checkpoint（M1）

循环内唯一检查点协议（沿用 harness/checkpoints.py，不改动其核心规则）：

```text
RUN_STARTED          (allow_immediate=False, allow_cancel=True)
BEFORE_MODEL         (allow_immediate=True,  allow_cancel=True)
AFTER_MODEL          (allow_immediate=False, allow_cancel=True)
BEFORE_TOOL_BATCH    (allow_immediate=False, allow_cancel=True)
AFTER_TOOL_BATCH     (allow_immediate=True,  allow_cancel=True)
BEFORE_FINALIZE      (allow_immediate=True,  allow_cancel=True)
```

- 取消生效于每个允许点；批次中未执行 ToolCall 必须收到合成取消 ToolResult（`complete_orphan_tool_results`）。
- 立即输入永不插入 tool batch 中间（保护 ToolCall/ToolResult 配对）。
- RunEnd 后到达的立即输入 → deferred 到队列头，进入下一 Run，不丢失。

## 5. Plan 一等状态（M2）

`execution/plan.py` 扩展：

- `PlanStatus` 增加 `CANCELLED`；`StepStatus` 扩展为 `PENDING / READY / RUNNING / BLOCKED / COMPLETED / VERIFIED / FAILED / SKIPPED`（原 `DONE` 改 `COMPLETED`，兼容别名保留）。
- `PlanStep` 增加 `expected_artifacts`、`effects`、`verification`、`evidence`（list[Evidence]）、`error`（FAILED 原因）、`retry_policy`、`skipped_reason`。
- `PlanState` 增加 `fingerprint` 覆盖目标/步骤/依赖/风险/验证条件（现有 compute_fingerprint 保持）；**状态字段变化不得改变内容指纹**（现实现已满足）。
- 新增 `PlanStore`（磁盘持久化：`<thread>/plans/<plan_id>@<version>.json`，原子写、旧版本保留）；Approved 后 `revise()` 必须创建新版本（version+1），已批准版本不可原地修改。
- 新增 `StepVerifier`：步骤进入 `VERIFIED` 必须有验证器结果记录；进入 `COMPLETED` 必须有 Evidence（文件+SHA-256 / tool result / 命令+退出码 / job id / parser 结果 / 审批 / 验证器报告）。
- 新增 `IdempotencyKey`（run_id/step_id/action_id/tool_name/normalized_args_digest）与 `IdempotencyStore`：同 key 重复请求返回原结果；状态未知 → `RECONCILE`，不自动重试。

## 6. ContextManager 与记忆（M3）

新增 `context/` 模块：

- `context/budget.py`：Token 估算（tiktoken + 保守默认窗口）、85% 阈值、预留输出/工具 schema 空间、预算决策进 Trace。
- `context/compactor.py`：摘要压缩；摘要记录 `summary_id / source_message_range / source_digest / created_by_model / version`；压缩后 ToolCall/ToolResult 配对保持完整；确定性约束（用户消息中的 constraint 标记）100% 保留。
- `context/memory.py`：Thread / Project / Artifact 三层记忆存储。
- `context/manager.py`：每次模型调用前构造上下文（system/固定约束/Objective/Plan/当前Step/最近对话/摘要/检索/Tool摘要/预算）；`AgentCore.generate_messages()` 接入。

## 7. ToolEffect 与 ToolScheduler（M4）

- `execution/effects.py`：`ToolEffect` 枚举（PURE / READ_WORKSPACE / WRITE_WORKSPACE / NETWORK / EXECUTE / SUBMIT_EXTERNAL / DESTRUCTIVE）；`FunctionTool` 增加 `effect` 声明字段；未声明 Effect 的工具在 RunEngine 注册时报错（兼容期默认 `EXECUTE`？——否：**未声明不得进入正式 Runner**，旧工具在接线处逐一补齐声明）。
- `execution/tool_scheduler.py`：并行规则（PURE/不冲突 READ 并行；同路径写串行；SUBMIT_EXTERNAL 单所有者+幂等键；DESTRUCTIVE 必须审批；无法判定串行）。
- `execution/permissions.py`：风险分级 `deny / ask / allow_once / allow_for_run / allow_for_workspace`；Approval 绑定 thread/run/tool_call/action/target/workdir/risk/expires_at；过期与跨 Run 重放拒绝。

## 8. 子 Agent 治理（M5）

- `tools/delegate.py` 改造：子 Agent 返回 `SubAgentResult`（status/summary/artifacts/evidence/assumptions/unresolved_questions/verification/usage）。
- 委派预算：max_depth（默认 1、系统最大 2）、max_turns、max_tokens、max_tool_calls、timeout、allowed_tools、read/write paths；循环委派检测（深度+祖先集合）；超预算结构化终止。
- 执行所有权：HPC 写入 Lease 单所有者（沿用 WorkspaceLeaseRegistry 语义）；Reviewer 不能批准自己产物。

## 9. Artifact Manifest（M6，非 HPC 部分）

新增 `artifacts/` 模块：

- `artifacts/manifest.py`：`ArtifactManifest`（artifact_id/type/path/sha256/run_id/step_id/created_by/input_artifacts/command/software/software_version/environment_digest/units/validation_status/acceptance_status/created_at）。
- 状态语义：`CREATED → COMPLETED → VALIDATED → ACCEPTED`，及 `REJECTED / SUPERSEDED`；程序正常结束只能进入 COMPLETED；确定性 Parser/Checker 通过才 VALIDATED；用户或独立 Reviewer 确认才 ACCEPTED；Agent 不能自行 ACCEPTED 自己的产物。
- `artifacts/registry.py`：文件 SHA-256 计算、不存在文件检测、输入/输出依赖图、删除/替换事件记录。
- HPC 字段（scheduler/job_id/cluster/partition）按用户指示**本阶段不实现**，schema 预留。

## 10. Provider 可靠性（M7）

- `core/capabilities.py`：`ModelCapabilities`（context_window/supports_tools/supports_parallel_tools/supports_reasoning/supports_json_schema/supports_usage/supports_streaming）；能力决策进入 RunSnapshot；不支持 tool calling 的模型不能进工具 Runner。
- `core/retry.py`：`RetryPolicy`（指数退避+抖动、429/5xx/连接超时/读超时/流中断/非法 chunk/usage 缺失分类）；只允许幂等请求自动重试；每次重试记录原因；结构化 Error Event。
- `core/budget.py`：`RunBudget`（max_input/output/total tokens、max_model_calls、max_tool_calls、max_wall_time、max_external_cost）；子 Agent 消耗计入父 Run；未知 usage 保守估算。

## 11. 里程碑与实施顺序

| 里程碑 | 内容 | 完成门槛 |
| --- | --- | --- |
| M0 | evals/ + 60 Golden Tasks + 基线结果 | 60 任务可自动执行、100% 确定性验证器、框架自身覆盖率 ≥90%、保存 main 基线 |
| M1 | RunEngine 统一 | 唯一状态机、唯一 checkpoint、App 层不碰 runner.inbound、三入口一致、无孤立 ToolCall |
| M2 | PlanStore + Evidence + 幂等 | Plan 可持久化、Approved 不可原地修改、每步有 Evidence、检查点恢复、副作用不重复 |
| M3 | ContextManager + 预算 | 200 轮压力通过、无上下文超限、约束保持 100%、压缩不降成功率 |
| M4 | ToolEffect + Scheduler + 审批 | 只读并行、写冲突为 0、未授权高风险为 0、审批不可重放 |
| M5 | SubAgent 结构化 + 预算 | 深度/预算硬限制、结构化结果、Reviewer 隔离 |
| M6 | Artifact Manifest（非 HPC） | completed≠validated≠accepted、数字可追溯、Manifest 无悬空引用 |
| M7 | Provider 可靠性 | 注入 429/5xx 恢复率 ≥99%、预算硬限制、结构化错误事件 |
| M8 | 全量验证 + 验收证据 | ≥1486 测试、覆盖率不降、关键新模块分支 ≥90%、Ruff 全绿、acceptance-report.json |

Golden Task 类别（60 个，HPC 类用模拟 scheduler，不做真实 HPC）：

| 类别 | 数量 | 说明 |
| --- | ---: | --- |
| planning | 10 | 任务拆分、依赖、成功标准、预算声明 |
| tool_use | 10 | 工具选择、参数正确性、错误恢复 |
| safety | 10 | 路径越界、危险命令、重复提交(模拟)、审批 |
| context | 10 | 长对话、压缩、约束保持 |
| scientific | 10 | 单位、输入检查、收敛判定、结果解释 |
| recovery | 10 | 进程退出、状态恢复、副作用不重复 |

## 12. 验收证据

每个里程碑生成 `artifacts/acceptance/<milestone>/acceptance-report.json`（tested_commit 指向实际 SHA），M8 汇总。验收报告 schema 遵循目标文档第四节。

## 13. 不做的事（用户指示）

- 不实现真实 HPC Job 状态机 / scheduler 对账 / Slurm 集成（evals 中 recovery 类使用模拟 scheduler）。
- 不做 CP2K→DeepMD / VASP Golden Workflow 专项改造。
- 不移动目录物理结构（engine/ 为新增模块，harness/runtime 逐步薄化）。
