# 开发

## 项目结构

```
src/
├── app/                 CLI、REPL、配置、会话管理、HTTP/Wire 后端、Dockerfile
└── electromind/         核心：运行时、Thread、对话持久化、Sandbox、Skills、工具、Trace
editors/
└── desktop/             Electron 桌面端（正式支持，经 Wire 协议驱动 Core）
skills/                  科学计算领域 Skills（CP2K / VASP / LAMMPS / DeepMD / MCMC 等）
tests/                   应用、核心、Sandbox 与协议测试
scripts/                 质量检查与发布脚本
evals/                   确定性 Golden Tasks
docs/                    架构、开发、测试、协议与发布文档
```

## 本地开发环境

```bash
uv sync --group dev          # 安装开发依赖
uv run electromind --dev     # 开发模式启动（数据落在 ./.electromind）
```

Desktop：

```bash
cd editors/desktop
npm install
npm start
```

## 质量闸门

```bash
uv run ruff check src/       # 代码检查
uv run ruff format --check . # 格式
uv run pytest                # 测试
./scripts/ci-check.sh        # 提交前本地闸门（ruff + format + pytest + coverage + 产物完整性）
pre-commit install           # 安装 pre-commit hooks
```

Desktop 单独验证：

```bash
cd editors/desktop
npm run check                    # TypeScript 类型检查
node --test scripts/*.test.mjs   # 单元测试（含 Agent 进程树 / CDP 冒烟）
```

## 常见问题

| 问题 | 解决方法 |
|---|---|
| 启动提示缺少 API Key | 运行 `electromind` 进入首次引导，或手动创建 `~/.electromind/config.toml` |
| Docker 容器未启动 | 确认 Docker / Podman 已运行，并构建了镜像 |
| SSH 连接失败 | 检查 `~/.ssh/config` 中 Host 别名和密钥配置 |
| 会话恢复找不到项目 | `--continue` 按 `project_path` 匹配当前目录；用 `--resume` 查看所有会话 |

## 数据布局

```
~/.electromind/
├── config.toml           # 用户配置
├── threads/              # 会话数据（每条一个 thread-* 目录）
│   └── <thread-id>/
│       ├── thread.toml   # 会话配置（创建时冻结）
│       ├── metainfo.json # 标题、时间、消息数
│       ├── messages/     # 对话记录
│       ├── artifacts.jsonl # 产物 Provenance 记录（SHA-256 版本链）
│       └── workspaces/   # Sandbox 工作区
├── hpc/
│   └── submissions.jsonl # HPC 提交记录（防重复 sbatch、reconcile 依据）
├── logs/                 # desktop.log / agent.log / wire.log（桌面端）
├── skills/               # 用户级 Skills
└── desktop.json          # 桌面端设置
```

关键状态文件一律**原子写**（临时文件 + rename）；读取时主文件损坏自动尝试
`.bak`，并把损坏文件改名 `.corrupt` 留存。
