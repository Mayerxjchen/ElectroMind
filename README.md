# ElectroMind

ElectroMind 是一个面向**科学计算与机器学习势函数（MLIP）工作流**的 AI Agent。它整合了第一性原理计算软件（VASP、CP2K、LAMMPS、DeepMD 等）的领域知识，能够在 local / Docker / Podman / SSH 多种 Sandbox 中执行计算任务、处理输入输出文件、分析结果，并通过可扩展的 Skills 系统持续积累科学工作流。

**核心能力：**

- 终端内多轮对话，流式输出与工具调用审批
- 本地（local）、容器（Docker / Podman）、远程（SSH / HPC）三种 Sandbox，适配计算集群
- **科学计算 Skills**：内建 CP2K、VASP、LAMMPS、DeepMD、MCMC 等软件的输入生成、输出解析与工作流编排
- 会话持久化与恢复：`--continue`、`--resume`、`session list`
- HTTP 与 Wire（stdio NDJSON）后端，供 Web UI、桌面端、VS Code 插件集成
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
git clone https://github.com/SyncLionPaw/pagent
cd pagent
uv sync
```

---

## 五分钟快速开始

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
├── electromind/         核心：运行时、Thread、对话持久化、Sandbox、Skills、工具、Trace
└── electromind_legacy/  旧版 API 兼容层
editors/
├── desktop/             Electron 桌面端
├── vscode/              VS Code 扩展
└── web/                 浏览器 Web UI（React + assistant-ui）
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
| 2 | `~/.electromind/electromind.toml` | 用户级配置（生产模式默认） |
| 3 | `./.electromind/electromind.toml` | 项目级配置（`--dev` 模式） |
| 4 | 包内模板 | 首次运行时自动从模板物化 |

**最小配置（`~/.electromind/electromind.toml`）：**

```toml
[provider]
api_key = "sk-xxxxxxxx"
model = "deepseek-v4-flash"

[permission]
mode = "prompt"  # prompt（逐个审批）| auto（自动批准）
```

也可通过环境变量 `DEEPSEEK_API_KEY` 或 `ELECTROMIND_HOME` 覆盖部分设置。

详细模板见 `src/template/pagent.toml`（注意：模板文件名因兼容性保留为 `pagent.toml`）。

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
├── electromind.toml      # 用户配置
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

## 桌面端、Web UI 与编辑器集成

### Web UI（浏览器访问）

```bash
cd editors/web
npm install
npm run dev
# 自动启动后端 + Vite 开发服务器，浏览器打开 http://localhost:5173
```

### Electron Desktop

```bash
cd editors/desktop
npm install
npm start
```

桌面端通过 Wire 协议与 `electromind --wire` 子进程通信，提供三栏工作台（会话列表 / 对话区 / 文件与 Artifacts 预览）。macOS 版本可在 [GitHub Releases](https://github.com/SyncLionPaw/pagent/releases) 下载。



## HTTP 与 Wire 集成

**HTTP 后端**（供 Web 前端、自定义客户端集成）：

```bash
electromind --http --host 127.0.0.1 --port 8848
# POST /command  → 发送命令
# GET  /events   → SSE 事件流
```

**Wire 后端**（供桌面端、VS Code 插件等进程间通信）：

```bash
electromind --wire
# stdin  → JSON-RPC 命令（NDJSON）
# stdout → JSON-RPC 事件（NDJSON）
```

Wire 协议的完整事件定义见 `src/electromind/adapters/`。

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
| 启动提示缺少 API Key | 运行 `electromind` 进入首次引导，或手动创建 `~/.electromind/electromind.toml` |
| Docker 容器未启动 | 确认 Docker / Podman 已运行，并构建了镜像 |
| SSH 连接失败 | 检查 `~/.ssh/config` 中 Host 别名和密钥配置 |
| 会话恢复找不到项目 | `--continue` 按 `project_path` 匹配当前目录；用 `--resume` 查看所有会话 |

---

MIT License
