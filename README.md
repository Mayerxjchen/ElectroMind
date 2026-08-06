<div align="center">

<img width="400" alt="ElectroMind" src="docs/assets/cat.png" />

# ⚡ ElectroMind

**AI Agent for Scientific Computing**

用自然语言运行、分析并自动化科学计算工作流。

**CP2K · VASP · LAMMPS · DeepMD · HPC**

[![Python](https://img.shields.io/badge/Python-≥3.11-blue?logo=python)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green)](./LICENSE)
[![uv](https://img.shields.io/badge/build-uv-orange?logo=uv)](https://docs.astral.sh/uv/)

</div>

---

## Why ElectroMind?

传统科学计算流程：

```text
写输入文件 → 提交 HPC → 查看输出 → 修改参数 → 重复
```

每一步都是手动的，结果散落在不同终端和目录里。

ElectroMind：

```text
自然语言任务
    ↓
Agent 分析项目
    ↓
生成 / 修改输入文件
    ↓
执行计算（本地 / 容器 / HPC）
    ↓
自动检查结果
    ↓
保存完整过程记录
```

对话式驱动第一性原理计算（CP2K/VASP）与机器学习势函数（DeepMD/LAMMPS）工作流，
并保留每一步的可追溯记录——**任务完成 ≠ 结果可信**，所有产物都要经过校验与确认。

---

## Features

### 🤖 AI 科学助手

用自然语言描述任务，Agent 负责分析项目、准备计算、执行与检查：

> “用 PBE-D3 准备一个 CP2K 水盒子计算”
> “检查这个 LAMMPS 输出的能量是否收敛”
> “把上一轮的构型提交到集群跑一次结构优化”

### 🧪 科学工作流 Skills

内置 CP2K / VASP / LAMMPS / DeepMD / MCMC 等领域技能，提供：

- 输入文件生成
- 工作流指引
- 结果检查与解析
- 输出文件快速预览

Skills 可扩展、可安装、可信任管理（见 [Skills](#skills)）。

### 🖥️ Desktop 桌面应用

三栏工作台：会话列表 · 对话区 · 文件/结果/任务。支持：

- Project → Thread 会话管理
- 审批、计划、产物（Artifact）检查
- HPC 任务状态与恢复信息
- Skills 管理面板（安装 / 信任 / 更新 / 移除）
- 独立的本地 Agent 进程（Wire 通信），崩溃自动恢复

### 🖥️ HPC 集群支持

```text
Desktop → 本地 Agent → rsess（远端 tmux 持久会话）→ hpc-submit → Slurm/PBS
```

- SSH 连接集群，tmux 会话断线不丢
- 提交记录防重复 sbatch，断线后自动 reconcile 恢复状态
- 输出经 rsync 拉取并校验 SHA
- 桌面端关闭后，远端作业继续运行

### ✅ 科学结果可信度

ElectroMind 严格区分三个状态：

| 状态 | 含义 |
|---|---|
| **COMPLETED** | 任务结束（退出码 0） |
| **VALIDATED** | 输出经确定性 Parser 校验通过（如 CP2K 正常收敛、能量齐全） |
| **ACCEPTED** | 用户（或独立 Reviewer）确认，可用于科学工作流 |

**Scheduler 说成功 ≠ 科学成功**——只有 Parser 通过并用户确认的产物，才能进入
后续流程（如 DeePMD 训练数据）。

---

## Installation

### Option A：Desktop（推荐）

1. 下载最新 dmg：[Releases](https://github.com/Mayerxjchen/ElectroMind/releases)
   （发布后可用；或本地构建，见下）
2. 打开 dmg，把 `electromind Desktop.app` 拖入 Applications
3. 首次启动后配置：

```text
设置 → API Key → 新建项目 → 开始
```

> 桌面端为 **Standalone** 模式：内置完整的 Agent 二进制，不依赖 Python / uv /
> 全局 CLI，macOS 干净环境开箱即用。

从源码构建 dmg（macOS）：

```bash
scripts/build-standalone.sh        # 1. Agent 单文件二进制
cd editors/desktop
node scripts/package.js --agent-bin ../../dist/electromind-<ver>-<plat>   # 2. 打包 .app
cd ../..
scripts/build-dmg.sh               # 3. dmg 安装包
```

### Option B：CLI

```bash
git clone https://github.com/Mayerxjchen/ElectroMind
cd ElectroMind
uv sync

# 首次运行，按引导配置 API Key
uv run electromind
```

也可全局安装：

```bash
uv tool install electromind
```

---

## Quick Start

1. **创建一个项目目录**（例如 `~/projects/water`），把输入文件放进去
2. **启动 ElectroMind**（CLI 或 Desktop），绑定该目录
3. **用自然语言描述任务**：

> “为这个水分子创建 CP2K 结构优化输入，PBE-D3 泛函”

4. Agent 会：

```text
✓ 检查项目文件
✓ 生成输入文件
✓ 执行计算（默认本地，无需 Docker）
✓ 检查输出并展示结果
✓ 记录产物（SHA-256 可追溯）
```

CLI 常用命令：

```bash
electromind                    # 新建会话
electromind --continue         # 恢复最近一次会话
electromind --resume           # 从历史会话中选择
electromind session list       # 列出全部会话
electromind --project ~/projects/water   # 绑定项目目录
```

REPL 内：`/exit` `/resume` `/sessions` `/pwd` `/ls` `/skills` `/history`

---

## Permission Modes

工具调用（执行命令、写文件、提交作业）默认需要审批：

| 模式 | 行为 | 适用场景 |
|---|---|---|
| **Prompt**（默认） | 每个工具调用逐个询问 | HPC 提交、文件修改 |
| **Auto-safe** | 只自动放行后端判定为**安全**的只读操作，其余仍询问 | 日常使用推荐 |
| **Full access** | 全部自动批准，无交互 | 仅限一次性/隔离环境 |

CLI：

```bash
electromind --auto            # 等价 Full access
```

Desktop：Composer 的 Autonomy 选择器切换；YOLO 按钮开启自动审批。

---

## Sandbox

Agent 的工具调用在 Sandbox 内执行：

| 后端 | 说明 |
|---|---|
| `local` | 直接在宿主机执行（**默认**，无需额外依赖） |
| `container` | 自动探测 Docker / Podman，隔离执行（需要容器运行时） |
| `ssh` | 通过 SSH 在远程执行（适用于 HPC 集群） |

```bash
electromind --backend local
electromind --backend container
electromind --backend ssh --ssh-host myserver
```

> Sandbox 不可用时**明确报错**，不会静默回退到 local——计算环境必须可预期。

---

## Running on HPC

以集群 `ikkemhpc`（Slurm）为例：

1. **连接并保持会话**——`rsess` 在远端建立 tmux 持久 shell，断线不丢：

```bash
rsess open my-work ikkemhpc
rsess run my-work "module load cp2k"
```

2. **让 Agent 提交任务**——在 Desktop/CLI 中说：

> “在集群上跑这个 CP2K 计算”

3. 背后发生的事情：

```text
本地 Agent
  ↓ rsess（远端 tmux shell，保持 cwd/环境）
hpc-submit Skill
  ↓
prepare_submission.py  登记脚本/输入 SHA，防止重复提交
sbatch                 → job_id 写回记录
  ↓
reconcile_job.py       经 squeue/sacct 恢复状态（查询失败显示 UNKNOWN，绝不猜测）
  ↓
collect_outputs.py     rsync 拉取产物 + SHA 校验
```

4. **桌面端关掉也不怕**：远端作业继续运行；下次启动后自动经 rsess 恢复任务状态，
   不会重复提交。

集群恢复冒烟（需要真实集群，CI 不跑）：

```bash
node scripts/hpc-recovery-smoke.mjs [--host ikkemhpc] [--sleep 45]
```

---

## Skills

Skills 扩展 ElectroMind 的能力（输入生成、输出解析、工作流编排）。

```bash
electromind skills list          # 查看已发现的 Skills
electromind skills add <git-url> # 安装（固定来源 commit）
electromind skills trust <name>  # 授予信任（安装 ≠ 信任）
electromind skills remove <name> # 移除
```

Desktop：Skills 面板支持安装（Git/本地目录）、信任/撤销、更新、移除，并显示
来源与内容 Digest。

内置技能包括：**CP2K · VASP · LAMMPS · DeepMD · MCMC · rsess · hpc-submit** 等。

---

## Data Safety

所有状态文件（会话配置、消息、产物、HPC 提交记录、桌面设置）**原子写入**
（临时文件 + rename），崩溃不留半写文件；主文件损坏时自动从 `.bak` 恢复，
损坏文件留存为 `.corrupt` 便于排查。

```bash
electromind doctor --data        # 诊断：线程配置 / 消息 / 产物 SHA / 写权限 / 磁盘空间
```

数据位置：`~/.electromind/`（线程、产物、HPC 记录、日志、Skills）。

---

## Configuration

配置文件：`~/.electromind/config.toml`（项目级 `.electromind/config.toml` 优先）。

最小配置：

```toml
[provider]
api_key = "sk-xxxxxxxx"
model = "deepseek-v4-flash"

[permission]
mode = "prompt"   # prompt | auto-safe | auto
```

环境变量：`DEEPSEEK_API_KEY`、`ELECTROMIND_HOME`。

---

## Developer?

运行原理、Wire 协议、测试与发布流程见 [docs/](docs/)：

- [架构](docs/architecture.md) — RunEngine / 状态机 / Plan / Artifact 验证
- [开发](docs/development.md) — 环境、质量闸门、常见问题
- [测试](docs/testing.md) — 测试套件与 CI 分层
- [Wire 协议](docs/wire-protocol.md) — Desktop 内部传输层
- [发布](docs/release.md) — Standalone 构建 / 打包 / dmg

---

<div align="center">

MIT License · 面向计算化学与材料科学工作流

</div>
