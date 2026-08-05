# ElectroMind Desktop V2 — 设计规范（D3）

- 日期：2026-08-05
- 目标界面：OpenAI Codex Desktop 的交互框架（见 `docs/design/codex-reference.md`）
- 设计约束与验收工具：`ui-ux-pro-max` skill（Design Tokens / 布局 / 对比度 /
  可访问性 / 图标 / 间距 / 动效一致性 / 交付前 UX 审查）
- **边界**：Codex 只是交互模型参考；开发由本仓库（ElectroMind）自身完成。
  Skill 不自行决定产品结构，不使用与 Codex 冲突的产品风格（营销 Landing /
  Bento Dashboard / Glassmorphism / 紫粉 AI 渐变）。

## 1. 领域语义映射

| Codex | ElectroMind |
| --- | --- |
| Project / Repository | 科学计算项目 |
| Agent Thread | 计算任务 Thread |
| Branch / Worktree | Workspace / Sandbox |
| Local / Cloud | Local / Container / SSH |
| Code Diff | 输入文件与结果变更 |
| Test Results | Preflight / Parser / Validation |
| Changed Files | Artifacts / Modified Files |
| Background Task | HPC Job |
| Review Changes | 科学结果审查 |
| Skills | Scientific Skills |
| Approval | 工具执行与作业提交审批 |

## 2. 信息结构

```text
Projects
└── Tasks / Threads
```

左侧导航：

```text
ElectroMind
＋ 新任务
搜索

PROJECTS
▾ Water MLIP
    CP2K initial labeling
    DeePMD training
    LAMMPS exploration
▾ VASP Study
    Structure relaxation
    DOS calculation
────────────
Skills
Settings
```

- D3.1 阶段按现有 `projectPath` 对 Thread 分组（不改后端 Schema）。

## 3. 中央 Thread Timeline（D3.3）

统一渲染：Message / Activity / Approval / Job / Artifact / Plan / Recovery / Error。

- 工具调用聚合为 Activity："▾ Worked for 1m 31s → ✓ Inspected · ✓ Generated input · ✓ Validated"。
- 运行完成默认折叠，失败自动展开。
- 所有交互（审批、Job 状态、Artifact 验收、恢复事件）内联在线程中。

## 4. 任务状态体系

| 状态 | UI |
| --- | --- |
| Running | 微型活动指示器 |
| Waiting approval | 黄色点 + `Review` |
| Waiting external job | 空心圆 + Job 状态 |
| Completed | 对勾 |
| Failed | 红色错误图标 |
| Interrupted | 暂停图标 |
| Needs input | 蓝色通知点 |

图标 + 文本并用，不只用颜色表达。

## 5. 布局（D3.2）

```text
┌──────────────────────────────────────────────────────────────┐
│ ElectroMind                                      Settings    │
├─────────────────┬────────────────────────────────────────────┤
│ ＋ New task      │ CP2K initial labeling                     │
│ Search          │ Water MLIP · SSH · Running                 │
│                 ├────────────────────────────────────────────┤
│ PROJECTS        │  中央 Thread（时间线 + 内联 Activity + 审批） │
│ ▾ Water MLIP    │                                            │
│   Initial label │  ┌──────────────────────────────────────┐  │
│   ...           │  │ Ask ElectroMind to continue…        │  │
│ Skills          │  │ ＋  SSH ▾   Plan ▾              ↑  │  │
│ Settings        │  └──────────────────────────────────────┘  │
└─────────────────┴────────────────────────────────────────────┘
```

- 主界面视觉权重：Thread 70% / Navigation 20% / Status 10%。
- Inspector（Plan / Changes / Artifacts / Jobs / Environment）**默认关闭**，
  点击对应内容（Plan 摘要 / 文件变更 / Artifact / Slurm Job / 环境）时打开。
- 删除永久右栏、Resizer、资源监控 Footer、重复的设置/主题/文档入口。

## 6. Review Inspector（D3.4）

Codex Diff Review 的科学计算映射：

```text
Changes                 Results
water64_force_energy.inp   energy          -1098.462 Ha
+ RUN_TYPE ENERGY_FORCE    max force        0.031 Ha/Bohr
+ CUTOFF 600               SCF converged    Yes
- CUTOFF 400               parser status   Validated
                           scientific      Awaiting review

用户操作：Open file · Compare · Accept · Request revision
```

## 7. Composer（D3.5）

```text
描述你希望 ElectroMind 完成的任务
＋  本机 ▾   计划模式 ▾   模型 ▾       发送
```

- `＋` 菜单：引用文件 / 添加结构 / 添加 Artifact / 选择 Skill / 添加图片 / 添加已有计算结果。
- 运行时发送按钮变 Stop。
- 权限用文本：`Permissions: Ask` / `Permissions: Auto`（替换闪电图标）。
- Project 与 Runtime 选择集中于此，不再分散。

## 8. 视觉体系（D3.6）

Design Tokens：`design-system/electromind-codex/MASTER.md`（ui-ux-pro-max 生成，
Variance 2 / Motion 3 / Density 5，暗色 + run green）。

- 保留系统字体（12/13/14/16/20）；4/8/12/16/24 间距；6/8/12 圆角。
- 主界面无阴影；Drawer/Popover/Modal 才有。
- 无装饰渐变、无大面积玻璃模糊；Hover 120–160ms、Drawer 180–220ms、支持 reduced motion。

## 9. 验收标准

### 与 Codex 目标一致

- [ ] 信息结构为 Project → Thread
- [ ] 用户可以快速切换多个长期任务
- [ ] 当前 Thread 是绝对视觉中心
- [ ] Agent 执行步骤在线程中显示
- [ ] 用户可在线程中完成审批
- [ ] 用户可审查 Changes 和 Artifacts
- [ ] 右侧 Inspector 默认关闭
- [ ] 新任务从 Project 和大输入框开始
- [ ] Local / Container / SSH 以简洁状态显示
- [ ] Background/HPC Job 在任务列表中持续显示状态

### 简洁性

- [ ] 默认永久区域只有导航与主内容
- [ ] 首屏主按钮不超过 8 个
- [ ] 设置只有一个入口
- [ ] 文档只有一个入口
- [ ] 主题只有一个入口
- [ ] 无永久 CPU/内存/磁盘条
- [ ] 无永久文件树
- [ ] 无永久 Terminal
- [ ] 无重复 Plan 展示

### ElectroMind 能力不丢失

- [ ] Plan / Files / Artifacts / Sandbox / Terminal-Logs 可访问
- [ ] Approval 可操作；Cancel/Resume 可操作
- [ ] Skills 可选择
- [ ] Standalone/Companion 行为一致
- [ ] **不修改 Wire 与 RunEngine 语义**

## 10. 实施顺序

```text
D3.0 设计基准（本文档 + codex-reference + design-system/electromind-codex）✅
D3.1 Project + Thread 导航（按 projectPath 分组）
D3.2 Codex 风格 Shell（左侧导航 + 中央 Thread + 极简标题 + Inspector 默认关闭）
D3.3 Thread Timeline（Activity 聚合渲染）
D3.4 Review Inspector（Plan/Changes/Artifacts/Jobs/Environment）
D3.5 Composer（附件 + 位置 + 模式 + 权限文本 + Send/Stop）
D3.6 视觉精修与验收
```
