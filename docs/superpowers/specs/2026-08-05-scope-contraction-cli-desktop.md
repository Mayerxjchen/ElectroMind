# 产品范围收缩：CLI + Desktop 双正式入口 — 设计与实施规范

- 日期：2026-08-05
- 基线：`main`（当前工作树；RunEngine 统一 M1–M6 已完成并提交）
- 来源：用户粘贴的产品范围设计（同日期），本文件为其持久化
- 用户指示：**现在就收缩范围**。只把 CLI 与 Desktop 作为正式入口；Web / VS Code / HTTP 降级为 experimental，不删除代码、不承诺长期兼容，新功能不再同步适配。

## 1. 问题陈述

ElectroMind 同时维护四个前端（CLI / Desktop / Web / VS Code）+ 两个服务后端（HTTP / Wire），放大器共三处：

1. **协议成本**：每个入口都要对齐同一套命令/事件 JSON（wire 的 stdio NDJSON、HTTP 的 SSE、Web 与 VS Code 各自的会话层）。
2. **状态同步成本**：Run / Plan / Approval / Artifact 状态在多个传输层上保持一致，任何一处漂移都要修四遍。
3. **兼容性成本**：把 Wire、HTTP 当公开 API 承诺长期兼容，等于给未定型协议背上包袱。

个人 / 小团队推进阶段，正确做法是：**一个执行内核 + 两个正式入口**，先把 Core 与 CLI、Desktop 做稳定，再恢复 Web / VS Code / 公共服务端。

## 2. 产品边界

```text
ElectroMind Core
├── RunEngine
├── Plan / Recovery
├── Sandbox / SSH / Slurm
├── Skills
├── Artifact / Provenance
└── Context / Permission
        │
        ├── CLI
        └── Desktop
              │
              └── Wire 协议
```

**关键边界：**

> 只支持 CLI 和 Desktop，不等于可以删除 Wire。

Desktop 当前通过 `electromind --wire` 子进程驱动 Agent，因此 **Wire 保留为 Desktop 的内部协议层**，但不作为公开产品接口承诺长期兼容。

**边界原则：**

> CLI 是完整功能入口，Desktop 是 CLI 能力的图形化呈现，Wire 只是连接 Desktop 与 Core 的内部传输层。

## 3. 暂缓范围（从 1.0 移除）

- Web UI
- HTTP/SSE 服务
- VS Code 扩展
- 浏览器远程访问
- 多用户服务端
- 云端 Runner
- 公共 REST API
- 跨设备同步
- Web 身份认证和权限系统
- 浏览器部署相关 Docker 镜像（`Dockerfile.browser`）
- Web、Desktop、VS Code 三端一致性测试

**代码处理：** 不立即删除，标记为 `experimental / unsupported / maintenance-only`；新功能不再要求同步适配这些入口。

## 4. CLI 职责（基准入口）

CLI 是**最完整、最稳定**的基准入口，至少支持：

```bash
electromind
electromind --continue
electromind --resume
electromind --project /path
electromind --backend local
electromind --backend container
electromind --backend ssh
electromind session list
electromind config ...
electromind doctor
```

完整覆盖：新建/恢复会话、流式对话、Plan 查看与批准、工具审批、Cancel 与追加输入、Skills 查看与诊断、Sandbox 状态、SSH/HPC 执行、Artifact 查看、Run 状态查看、故障恢复、日志与诊断包导出。

**CLI 是核心功能的参考实现**：Desktop 出现行为争议时，以 CLI 与 RunEngine 的语义为准。

## 5. Desktop 职责（图形化呈现）

Desktop 不重新实现 Agent 逻辑，只负责**展示与发送命令**。保留的界面：

1. 会话列表 — 创建/恢复/删除；运行、等待审批、失败、完成状态
2. 对话区 — 流式文本、Thinking、Tool Call / Result、Cancel、Immediate Input
3. Plan 面板 — 当前目标、步骤与依赖、状态、Evidence、批准或要求修改
4. Approval 卡片 — 命令、工作目录、风险等级、目标环境、预计副作用、Permit / Deny
5. Artifact 面板 — 文件列表、输入输出关系、验证状态、Provenance、基础预览
6. 运行状态 — 当前阶段、当前 Step、Slurm Job ID、Token 与工具预算、错误及恢复建议

不做：Desktop 内完整 IDE、代码编辑器、复杂图表平台、多窗口协作。

## 6. 精简后的验收范围

### 入口一致性（必须）

- CLI 与 Desktop 共用**同一个** RunEngine。
- Desktop 经 Wire 驱动，**不得复制 Agent 状态机**。
- 相同任务下 CLI 与 Desktop 必须产生一致的：Run 状态、Plan 状态、Tool 调用、Approval 结果、Artifact、Stop Reason。
- Desktop 关闭不能导致外部 HPC Job 被取消。
- Desktop 重启后能恢复 Thread、Run、Plan、Approval、Artifact 状态。
- Wire 断开不得导致状态损坏或重复执行。

### 不再验收

- HTTP 与 CLI 一致性
- Web 与 Desktop 一致性
- VS Code 与 Desktop 一致性
- SSE 重连、浏览器并发连接、REST API 兼容性

## 7. 1.0 必须完成项

| 域 | 内容 |
| --- | --- |
| 核心内核 | 统一 RunEngine、Semantic Checkpoint、Plan 与 Step、Recovery 与 Idempotency、Context Manager、Tool Effect 与 Scoped Approval、Artifact Provenance、SSH/Slurm 状态恢复、Agent Eval |
| CLI | 完整会话生命周期、Plan 与审批交互、Cancel / Resume / 诊断、SSH/HPC 工作流、Artifact 与状态查看 |
| Desktop | 会话管理、对话与工具卡片、Plan UI、Approval UI、Artifact UI、Run 状态与恢复、Wire 重连与历史回放 |
| 科学工作流 | CP2K → DeepMD 最小完整工作流、VASP 标准最小工作流、completed ≠ validated ≠ accepted 分离、数值/单位/Provenance 可追踪 |

## 8. 代码处理方式

**正式支持：**

```text
src/electromind/
src/app/cli* src/app/repl* src/app/wire.py
editors/desktop/
```

**暂停开发（experimental / maintenance-only）：**

```text
src/app/http_server.py
```

**已删除（2026-08-05，见第 11 节更新记录）：**

```text
editors/web/
editors/vscode/
```

文档声明：

```text
Supported interfaces:
- CLI
- Desktop

Experimental interfaces:
- HTTP
- Web
- VS Code
```

**CI 两层（契约）：**

```text
required（阻断）:    core / cli / wire / desktop
non-blocking（不阻断）: http / web / vscode
```

已有 HTTP、Web、VS Code 测试**不删除**，先改为非发布阻断，避免代码在不知情的情况下腐化。注：当前仓库尚无 GitHub Actions CI，只有 `scripts/ci-check.sh`（本地提交前闸门）；两层契约先在文档落实，真实 CI 落地时按本契约执行，`ci-check.sh` 维持现状（全量测试，是当前唯一保护网，暂不削弱）。

## 9. 开发顺序

```text
1. RunEngine（已完成，M1–M6 提交）
2. CLI 完整接入
3. Wire 薄协议化
4. Desktop 接入
5. Plan / Approval / Artifact UI
6. Recovery 与重连
7. CP2K → DeepMD 端到端验收
8. VASP 端到端验收
9. 1.0 稳定与文档
```

## 10. 不做的事（本阶段）

- 不删除 HTTP 代码与测试（Web / VS Code 已于 2026-08-05 按用户决定删除，见下）
- 不给新功能同步适配 experimental 入口
- 不把 Wire / HTTP 作为公开 API 承诺兼容（Wire 仅作 Desktop 内部传输层）
- 暂不落地真实 CI 流水线（先落文档契约）

## 11. 更新记录

**2026-08-05（用户决定）：删除 Web 与 VS Code。**

- `editors/web/`、`editors/vscode/` 整体删除（`git rm -r`，历史版本可从 git 找回）。
- 本节原「不删除」表述作废：范围收缩进入第二阶段——不再是"标记 experimental 保留"，
  而是直接移除不使用的入口。
- 同步更新：README（支持级别/目录/章节）、AGENTS.md（布局与支持级别）。
- 仍在 maintenance-only 的 experimental 入口：`src/app/http_server.py`（HTTP），保留代码与测试。
- 影响面：无运行时代码引用这两个目录（wire/cli 注释中的「插件/前端」泛指已不指向具体产品）；
  三端一致性验收项从验收范围移除。
