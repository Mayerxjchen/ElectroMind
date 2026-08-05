<div align="center">

# ⚡ ElectroMind

<img width="500" alt="ElectroMind banner" src="https://github.com/user-attachments/assets/c40443ce-679f-4d78-90b5-2cba92f39a07" />

[![Python](https://img.shields.io/badge/Python-≥3.11-blue?logo=python)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green)](./LICENSE)
[![uv](https://img.shields.io/badge/build-uv-orange?logo=uv)](https://docs.astral.sh/uv/)

**面向科学计算与机器学习势函数（MLIP）工作流的 AI Agent**

</div>

ElectroMind 整合了第一性原理计算软件（VASP、CP2K、LAMMPS、DeepMD 等）的领域知识，能够在 local / Docker / Podman / SSH 多种 Sandbox 中执行计算任务，并通过可扩展的 Skills 系统持续积累科学工作流。

**核心能力：**

- 终端内多轮对话，流式输出与工具调用审批
- 本地（local）、容器（Docker / Podman）、远程（SSH / HPC）三种 Sandbox，适配计算集群
- 科学计算 Skills：内建 CP2K、VASP、LAMMPS、DeepMD、MCMC 等软件的输入生成、输出解析与工作流编排
- 会话持久化与恢复：`--continue`、`--resume`、`session list`
- Wire（stdio NDJSON）内部传输层，驱动 Desktop；HTTP 后端（experimental）
- 可扩展的 Skills 系统与子 Agent 委托
- 内建工具：命令执行、文件读写、网页搜索、URL 抓取、计算结果可视化

---

## 环境要求与安装

- Python ≥ 3.11
- [uv](https://docs.astral.sh/uv/)（推荐包管理工具）

```bash
# 安装 uv（macOS）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 从 PyPI 安装（全局可用）
uv tool install electromind

# 或从源码可编辑安装（本地开发）
git clone https://github.com/Mayerxjchen/ElectroMind
cd ElectroMind
uv sync
```

---

## 执行内核架构（v0.8 起）

自 v0.8 起，ElectroMind 的执行内核收敛为**唯一 Run 生命周期**（正式入口：CLI 与 Desktop；Wire 为 Desktop 的内部传输层）：

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

- **RunEngine**（`electromind/engine/run_engine.py`）是唯一 Run 状态事实源：
  cancel / steer / permit / deny 全部经它（App 层不再直接操作
  `runner.inbound`）；事件带 per-thread 单调 `seq`；同一 Thread 同时最多
  一个可写 Run。
- **语义检查点**（`harness/checkpoints.py`）在循环的六个命名点
  （RUN_STARTED / BEFORE_MODEL / AFTER_MODEL / BEFORE_TOOL_BATCH /
  AFTER_TOOL_BATCH / BEFORE_FINALIZE）统一处理取消与立即输入注入，
  ToolCall 永不孤立。
- **Plan**（`execution/plan.py`）：`PlanState` / `PlanStore` /
  `StepVerifier`——已批准计划不可原地修改；无 Evidence 不得
  COMPLETED；无验证器结果不得 VERIFIED；指纹覆盖全部内容字段。
- **幂等**（`execution/idempotency.py`）：外部副作用（提交/删除/上传）
  必须带 `IdempotencyKey`；同 key 重放原结果，状态未知进入
  RECONCILING 不盲目重试。
- **上下文与预算**（`context/`）：模型调用前 Token 估算与 85% 阈值检查，
  超限先压缩；用户固定约束 100% 保留；Thread / Project / Artifact 三层
  记忆。
- **工具治理**（`execution/effects.py` / `tool_scheduler.py` /
  `permissions.py`）：工具必须声明 Effect（未声明不能注册正式 Runner）；
  只读可并行、写与外部提交串行；审批绑定 Thread/Run/ToolCall/Action/
  过期，跨域重放全部拒绝。
- **子 Agent**（`tools/delegate.py`）：结构化 `SubAgentResult` 交付；
  委派深度默认 1、系统最大 2；token/工具调用/超时预算硬限制；工具
  白名单与读写路径边界。
- **Artifact**（`artifacts/`）：`ArtifactManifest` + `ArtifactRegistry`，
  completed ≠ validated ≠ accepted 严格分离（Parser 通过才 VALIDATED，
  用户或独立 Reviewer 确认才 ACCEPTED），SHA-256 完整性校验。
- **Provider 可靠性**（`core/capabilities.py` / `retry.py` /
  `budget.py`）：能力协商（保守默认）、指数退避重试（429/5xx/超时）、
  Run 级预算（token/调用次数/墙钟/外部成本，子 Agent 计入父 Run）。

### 接口支持级别

```text
Supported interfaces（正式支持）:
- CLI        —— 最完整、最稳定的基准入口，核心功能的参考实现
- Desktop    —— CLI 能力的图形化呈现，经 Wire 驱动，不复制 Agent 状态机

Experimental interfaces（暂停开发，maintenance-only）:
- HTTP       —— 不承诺兼容，新功能不要求适配
- Web        —— 同上
- VS Code    —— 同上
```

边界原则：**CLI 是完整功能入口，Desktop 是 CLI 能力的图形化呈现，Wire 只是连接
Desktop 与 Core 的内部传输层**（不作为公开 API 承诺长期兼容）。细节与验收范围
见 `docs/superpowers/specs/2026-08-05-scope-contraction-cli-desktop.md`。

---

### Golden Task 评测（evals/）

```bash
python -m evals list          # 列出全部任务
python -m evals run           # 运行全部（JSON 报告）
python -m evals baseline      # 保存/刷新基线
```

66 个确定性 Golden Tasks（Planning / Tool Use / Safety / Context /
Scientific / Recovery 六类 ≥10 个）用脚本化 Provider 驱动，验证引擎的
状态、工具、副作用与 Artifact 行为；safety 与 recovery 类 100% 通过
是发布门槛。

---

## 快速开始

```bash
# 1. 首次运行，按引导配置 API Key
electromind

# 2. 开始对话
electromind --continue    # 恢复上次会话
electromind --resume       # 从历史会话中选择
electromind session list   # 查看所有会话

# 3. 切换 Sandbox（默认 local）
electromind --backend container    # Docker / Podman
electromind --backend ssh --ssh-host myserver
```

REPL 内可用命令：`/exit` `/resume` `/sessions` `/pwd` `/ls` `/skills` `/history`

---

## 项目目录

```
src/
├── app/                 CLI、REPL、配置、会话管理、HTTP/Wire 后端、Dockerfile
└── electromind/         核心：运行时、Thread、对话持久化、Sandbox、Skills、工具、Trace
editors/
├── desktop/             Electron 桌面端（正式支持，经 Wire 协议驱动 Core）
├── vscode/              VS Code 扩展（experimental，暂停开发）
└── web/                 浏览器 Web UI（experimental，暂停开发）
skills/                  科学计算领域 Skills（CP2K / VASP / LAMMPS / DeepMD / MCMC 等）
tests/                   应用、核心、Sandbox 与协议测试
scripts/                 质量检查与发布脚本
```

---

## 配置

配置文件为 TOML 格式，加载优先级如下：

| 优先级 | 位置 | 说明 |
|---|---|---|
| 1 | `--config <file>` | CLI 显式指定，覆盖以下所有 |
| 2 | `<project>/.electromind/config.local.toml` | 项目内本机私有设置 |
| 3 | `<project>/.electromind/config.toml` | 项目级配置（仅受信任项目） |
| 4 | `~/.electromind/config.toml` | 用户级配置（生产模式默认；缺失时从内置默认物化） |
| 5 | 包内默认 | `src/electromind/resources/default-config.toml`，唯一内置默认 |

**最小配置（`~/.electromind/config.toml`）：**

```toml
[provider]
api_key = "sk-xxxxxxxx"
model = "deepseek-v4-flash"

[permission]
mode = "prompt"  # prompt（逐个审批）| auto（自动批准）
```

也可通过环境变量 `DEEPSEEK_API_KEY` 或 `ELECTROMIND_HOME` 覆盖部分设置。

全字段参考见包内默认 `src/electromind/resources/default-config.toml`。

---

## 常用 CLI 命令

```bash
electromind                         # 新建会话
electromind --continue              # 恢复当前项目最近一次对话
electromind --resume                # 打开交互式会话选择器
electromind --resume <thread-id>    # 按 ID 直接恢复
electromind session list            # 表格列出所有历史会话
electromind --blocking              # 阻塞 REPL 模式
electromind --auto                  # 自动批准所有工具调用
electromind --project /path/to/proj # 绑定工作目录
electromind --dev                   # 开发模式（数据落在 ./.electromind）
```

---

## 数据保存位置

```
~/.electromind/
├── config.toml           # 用户配置
├── threads/              # 会话数据（每条一个 thread-* 目录）
│   └── <thread-id>/
│       ├── thread.toml   # 会话配置（创建时冻结）
│       ├── metainfo.json # 标题、时间、消息数
│       ├── messages/     # 对话记录
│       └── workspaces/   # Sandbox 工作区
├── skills/               # 用户级 Skills
└── desktop.json          # 桌面端设置
```

---

## Sandbox

ElectroMind 支持四种 Sandbox 后端，Agent 的工具调用在 Sandbox 内执行。SSH 后端可连接 HPC 计算集群：

| 后端 | 说明 |
|---|---|
| `local` | 直接在宿主机执行（默认，无需额外依赖） |
| `container` | 自动探测 Docker 或 Podman，隔离执行 |
| `docker` / `podman` | 显式指定容器引擎 |
| `ssh` | 通过 SSH 在远程主机执行（适用于 HPC 计算集群） |

```bash
electromind --backend local
electromind --backend container
electromind --backend ssh --ssh-host myserver --ssh-config ~/.ssh/config
```

需要浏览器渲染 HTML / 导出 PDF 时，先构建 browser 镜像：

```bash
docker build -t electromind:browser -f src/app/Dockerfile.browser src/app
```

然后在配置中设置 `[sandbox.container] image = "electromind:browser"`。

---

## 桌面端（正式支持）与实验性编辑器

### Electron Desktop（正式支持）

```bash
cd editors/desktop
npm install
npm start
```

桌面端通过 Wire 协议与 `electromind --wire` 子进程通信，提供三栏工作台（会话列表 / 对话区 / 文件与 Artifacts 预览）。

> **安装包状态：** Desktop 打包脚本已提供（`editors/desktop/scripts/package.js`），
> 预构建安装包**尚未正式发布**（GitHub Releases 暂无产物）。当前请从源码运行
> Desktop，并确保本机已安装 `electromind` CLI（`uv tool install electromind`）——
> Desktop 是图形壳，Agent 能力由 CLI 的 `--wire` 子进程提供。

### Web UI 与 VS Code 扩展（experimental，暂停开发）

代码保留但不在开发计划内，不承诺兼容；新功能不要求适配。仅维护既有测试防腐化。

- **Web UI**：`cd editors/web && npm install && npm run dev`（Vite :5173）
- **VS Code 扩展**：`editors/vscode/`



## Wire（内部协议）与 HTTP（experimental）

**Wire 后端**（Desktop 的内部传输层）：

```bash
electromind --wire
# stdin  → JSON-RPC 命令（NDJSON）
# stdout → JSON-RPC 事件（NDJSON）
```

Wire 不承诺对外长期兼容（仅供 Desktop 使用）；协议的完整事件定义见 `src/electromind/adapters/`。

**HTTP 后端**（experimental，暂停开发）：

```bash
electromind --http --host 127.0.0.1 --port 8848
# POST /command  → 发送命令
# GET  /events   → SSE 事件流
```

---

## Python API

ElectroMind 核心包可通过 `electromind` 导入：

```python
import asyncio
from electromind import DeepSeek, Runner

async def main():
    provider = DeepSeek("deepseek-v4-flash", apikey="sk-...")
    runner = await Runner.create("thread-demo", provider)
    async for event in runner.run("用 Python 写一个快速排序"):
        print(f"[{event.kind}] {event}")

asyncio.run(main())
```

`Runner.create` 的详细参数与 `electromind.ithread.ThreadSpec` 配置请参考 `AGENTS.md`。

---

## 本地开发

```bash
uv sync --group dev          # 安装开发依赖
uv run pytest                # 运行测试
uv run ruff check src/       # 代码检查
uv run electromind --dev     # 开发模式启动（数据落在 ./.electromind，不污染 ~/.electromind）
pre-commit install           # 安装 pre-commit hooks
```

### 常见问题

| 问题 | 解决方法 |
|---|---|
| 启动提示缺少 API Key | 运行 `electromind` 进入首次引导，或手动创建 `~/.electromind/config.toml` |
| Docker 容器未启动 | 确认 Docker / Podman 已运行，并构建了镜像 |
| SSH 连接失败 | 检查 `~/.ssh/config` 中 Host 别名和密钥配置 |
| 会话恢复找不到项目 | `--continue` 按 `project_path` 匹配当前目录；用 `--resume` 查看所有会话 |

---

MIT License
