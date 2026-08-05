# CLI 完整接入核对 — 现状审计与差距矩阵

- 日期：2026-08-05
- 依据：`docs/superpowers/specs/2026-08-05-scope-contraction-cli-desktop.md` 第 4 节（CLI 职责）
- 结论先行：**基础交互面完整，两大结构性缺口：Plan 查看与批准、Artifact 查看**（M2/M6 模块未接线）；两个小缺口：doctor 无 live probe、无诊断包导出。

## 1. 命令清单核对

| 规范要求 | 现状 | 证据 |
| --- | --- | --- |
| `electromind` | ✅ TUI REPL（默认） | `repl.run_repl` → `concurrent_repl` |
| `--continue` | ✅ | `cli_parser` `continue_last` |
| `--resume`（选择器/ID） | ✅ 两种都支持 | `interactive.py` `resume_interactive` + picker |
| `--project /path` | ✅ | `cli_parser` `--project`（存绝对路径防漂移） |
| `--backend local/container/ssh` | ✅ + docker/podman | `cli_parser`；`open_runner` 经 `resolve_execution` 单一决策 |
| `session list` | ✅ + show/delete/export | `commands/session.py` |
| `config ...` | ✅ get/set/unset/edit/path/validate/sources/trust/untrust（多 scope + 脱敏 + fail-closed） | `commands/config.py` |
| `doctor` | ✅ 基础版（见缺口 B） | `commands/doctor.py` |

## 2. 覆盖清单核对

| 职责 | 状态 | 证据 / 缺口 |
| --- | --- | --- |
| 新建/恢复会话 | ✅ | `-c`/`-r`/picker、`/new`、`/resume`、`session` |
| 流式对话 | ✅ | `item/delta`（text/reasoning）、tool begin/result 渲染；TUI + blocking 双模式 |
| 工具审批 | ✅ | TUI：Enter 批准 / Esc 取消（无裸字母键）；blocking：`permit> y/N`；print 非 TTY：拒绝 exit 4 |
| Cancel / 追加输入 | ✅ | Esc/Ctrl+C 取消精确绑定 run_id（`tui/application.cancel_run`）；immediate steer（Enter=发送/steer，`client._drain_immediate`）；Tab 排队 FIFO |
| Skills 查看与诊断 | ✅ | `/skills` + `skills list/show/validate/paths/reload/doctor/install/uninstall/installed`（共享 CatalogService） |
| Sandbox 状态 | ⚠️ | `/status` 显示 backend/workdir/turns/context%；**doctor 对 container/ssh 为静态判断，无 live probe**（doctor 注释自认 CLI-5 TODO） |
| SSH/HPC 执行 | ✅ | `--target ssh`、`--ssh-host/--ssh-config/--ssh-workdir`；SSH 专项错误提示。Slurm 按用户指示不做 |
| **Plan 查看与批准** | ❌ **未接线** | M2 `PlanStore/PlanState/StepVerifier/Evidence` **0 处运行时引用**（engine/harness/app 全不引用，仅单测）；协议层无 `plan/*` 事件；REPL 无 `/plan`；TUI 无 Plan 面板 |
| **Artifact 查看** | ❌ **未接线** | M6 `ArtifactManifest/ArtifactRegistry` 仅库代码 + 单测；无 `artifact/*` 事件；REPL 无 `/artifacts`；print 模式 json 输出 `artifacts: []` 硬编码；wire.py 的 "artifacts" 只是 copy_to_host 路径语义 |
| Run 状态查看 | ✅ | `/tasks`（phase/turn/stop/排队输入）、`/status`、`run/state` 事件 |
| 故障恢复 | ✅ | `clean.py` 退出清理、`--continue`/`--resume` 恢复、harness recovery marker、`format_fatal_error` 分后端提示 |
| 日志/诊断包导出 | ⚠️ | `--log-file`、`doctor`、`session export` 单会话 JSON；**无打包 logs+config+threads 的诊断包导出命令** |

## 3. 基线数据（M1–M7 验收报告）

- tested_commit `dc540a3`：1672 tests pass / 0 fail，coverage 79.7%（关键模块合计 96% 分支），66/66 Golden Tasks
- 说明库层模块完成度高，但 **Plan/Artifact 的验收全部在库层单测，未到入口层**——这正是本次审计抓到的结构性缺口。

## 4. 差距与实施顺序

```text
G1  Plan/Artifact 接入执行链（最大缺口）—— 已完成（2026-08-05）
    RunEngine 产 plan/* 与 artifact/* 事件 → harness 协议 → CLI 呈现
    （CLI 与 Desktop 共用同一协议，一次接线两端受益）
G1b Agent 侧工具桥 —— 已完成（2026-08-05，见第 6 节）
    plan_propose / plan_step_update / artifact_register 模型工具 +
    引擎访问器 + expected_artifacts 证据自动化 + 默认白名单
G2  doctor live probe：container 引擎探测 / SSH 连通性 / 镜像存在性
G3  diagnostic bundle 命令：打包 logs + 配置 + threads 清单 + doctor 报告
```

接入时保持范围收缩边界：**只动 CLI + Wire + Desktop 三端**，HTTP/Web/VS Code 不适配。

## 5. G1 实施记录（2026-08-05）

| 层 | 改动 | 证据 |
| --- | --- | --- |
| 引擎 | `RunEngine` 新增 per-thread `PlanTracker`+`PlanStore`（`<thread>/plans/`）与 `ArtifactRegistry`（`<thread>/artifacts.jsonl`），惰性初始化+磁盘恢复；公开 `plan_state/propose/approve/revise/cancel/update_step`、`artifacts/register/complete/validate/accept/reject`；`state_emitter` 同步钩子 | `engine/run_engine.py` |
| PlanTracker | 新增 `restore()`（磁盘恢复当前计划，Approved 计入历史保版本门） | `execution/plan.py` |
| 协议 | `plan/state`、`artifact/state` 事件 + 12 个命令进 v2 协议；`thread/snapshot` 携带 plan/artifacts（Desktop 重启恢复） | `harness/protocol_v2.py`、`app/wire.py` |
| Wire | 6+6 个命令处理器（引擎错误以 `emit_error` 转述）；`_get_engine()` 挂接 state_emitter | `app/wire.py` |
| CLI | `/plan`（propose/approve/revise/cancel）、`/artifacts`（register/accept/reject）；`EmbeddedAgentClient` 委托方法；TUI（app.client）与阻塞 REPL（client 参数）双通道 | `app/repl.py`、`app/client.py` |
| 测试 | `tests/test_engine_plan_artifacts.py` 10 个（生命周期/持久化恢复/版本门/Evidence 门/转换门/emitter/协议常量） | 全绿 |

边界：G1 做状态接入与呈现；G1b 补上模型侧 producer，闭环完整。

## 6. G1b 实施记录（2026-08-05）

| 层 | 改动 | 证据 |
| --- | --- | --- |
| 访问器 | `engine/accessor.py`：进程级 `set_engine/get_engine`（wire `_get_engine()` 与 CLI client `__init__` 注册；未注册返回 None 不崩溃） | `engine/accessor.py`、`app/wire.py`、`app/client.py` |
| 工具桥 | `tools/plan_artifacts.py` 三工具（effect 均 WRITE_WORKSPACE，过 M4 注册门）：`plan_propose`（结构化步骤 → 引擎冻结 READY）、`plan_step_update`（M2 Evidence 门：completed 无证据拒绝并引导登记产物）、`artifact_register`（经 sandbox.files 跨后端读文件 + SHA-256，created_by="agent" 保证用户可 accept） | `tools/plan_artifacts.py` |
| 证据自动化 | artifact_register 的 step_id 匹配步骤 `expected_artifacts`（含 basename 匹配）→ 自动附加 `Evidence.file(path, sha256, by="agent")`（确定性来源），步骤随后可 COMPLETED | 同上 + e2e 冒烟 |
| 装配 | `assemble_harness_tools` 白名单 + 报错信息更新；`default-config.toml` `[agent] tools` 默认加三个（新 thread 生效，旧 thread 冻结不漂移） | `runtime/base_runner.py`、`resources/default-config.toml` |
| 测试 | `tests/test_tool_plan_artifacts.py` 13 个（accessor/三工具/证据自动化/自证守卫/M6 全链/装配） | 全绿 |

**端到端冒烟实录**（脚本化模型，非真 LLM）：

```
1) 模型提议: 计划已提议（default@1，状态 ready）：生成 CP2K 输入并运行
2) 用户批准: status = approved
3) 模型登记产物: 已登记产物 cp2k.inp（data，sha256 47e4807f）；步骤 s1 已附加文件证据，可标记 completed
4) 步骤完成: 步骤 s1 → completed
5) 用户验收: status = accepted
6) 最终计划: steps: [('s1','completed',1条证据), ('s2','pending',0)]（依赖步骤保持 pending）
```

回归：全量 1703 passed / 0 failed（sci-011 为已知 ELECTROMIND_HOME env 泄漏
顺序 flaky，单独/重跑通过，与 G1b 无关）；ruff 全绿。

下一步（规范第 9 节顺序）：CLI + Desktop 完整集成验收（G1/G1b 产物可经
Desktop wire 协议全量可见——命令/事件/快照均已就绪）。

## 7. D1 Desktop Plan/Artifact UI（2026-08-05，规范第 5 步）

| 层 | 改动 | 证据 |
| --- | --- | --- |
| 协议 | `shared/protocol.ts`：PlanState/PlanStepState/PlanEvidence/ArtifactManifest 类型（镜像后端）+ WireCommand 扩展 12 个 plan/artifact 命令 | 与后端 `execution/plan.py`、`artifacts/manifest.py` 字段一一对应 |
| 安全边界 | preload + main 双白名单扩展（能力边界：只有清单内命令可过桥） | `preload/index.ts`、`main/index.ts` |
| Store | ThreadState 加 `plan`/`artifacts`；ThreadStore 处理 `plan/state`/`artifact/state` 事件 + applySnapshot 恢复（重启五态恢复） | `store/types.ts`、`store/ThreadStore.ts` |
| UI | PlanPanel（新）+ PlanCard 接线（原为无数据源预留组件）：类型对齐协议、M2 全 StepStatus 映射、Evidence 展示、批准/修订/取消按钮；InspectorShell 加 Plan tab（badge）；Artifacts tab 加 ManifestPanel（状态徽章 + 完成/验证/接受/驳回操作） | `react/components/` |
| CSS | manifest 徽章色 + evidence/失败样式 | `style.css` |
| 验证 | tsc 干净；node --test 69/69；esbuild 编译通过；**wire 端到端**：`plan/state → propose(ready) → approve(approved) → artifact/state` 四条事件完整回流 | 实测 |

Desktop 侧闭环：PlanPanel 发 `plan/approve` → wire → RunEngine → `plan/state` 事件回流 → ThreadStore → UI 自动刷新。CLI（/plan）与 Desktop（Plan 面板）操作同一状态源，无本地状态复制（符合"Desktop 不复制 Agent 状态机"验收）。
