# electromind Desktop

electromind 的 Electron 桌面端：三栏工作台（会话历史 / 对话 / 沙箱 · Artifacts），通过 Wire 协议（JSON-RPC NDJSON）与 `electromind --wire` 子进程通信。

## 环境准备

桌面端本身只需要 Node.js，但它在运行时会拉起 `electromind` 后端子进程，所以还需要 Python 侧的 `uv`。

### 1. Node.js（用 nvm 管理）

```bash
# 安装 nvm 后
nvm install --lts
nvm use --lts        # 需要 Node 18+，Electron 37 在 LTS 上验证过
```

### 2. Python 后端（用 uv 管理）

后端是仓库根目录的 `electromind` 包，需要 Python ≥ 3.11。桌面端优先用 `uv run` 拉起它，不需要预先手动装依赖，但要保证 `uv` 在 PATH 里。

```bash
# 安装 uv（macOS）
curl -LsSf https://astral.sh/uv/install.sh | sh
# uv 会落在 ~/.local/bin，桌面端会自动把该目录加进 PATH

# 在仓库根目录同步后端依赖（首次运行前执行一次）
cd /path/to/electromind
uv sync
```

桌面端拉起后端的方式见 [src/shared/agent.ts](src/shared/agent.ts)：
优先 `uv run --project <repo-root> electromind --wire --backend local`，找不到 `uv` 时回退到 PATH 里的 `pagent`。

### 3. API Key

后端调用 DeepSeek，需要 API Key，二选一：

```bash
export DEEPSEEK_API_KEY=sk-xxx
# 或写入生效的 home 配置：./.pagent/electromind.toml 或 ~/.electromind/electromind.toml
# [provider]
# api_key = "sk-xxx"
```

## 本地运行

```bash
npm install
npm run start        # 先 esbuild 编译，再启动 electron
```

其它脚本：

```bash
npm run compile      # 只编译（node esbuild.js）
npm run check        # 类型检查（tsc --noEmit）
```

## Sandbox backend 与镜像

桌面端启动参数默认 `--backend local`（见 [src/shared/agent.ts](src/shared/agent.ts) 的 `resolveElectromindWireInvocation`），
**不依赖 Docker/Podman**，开箱即用。

新建任务时会弹出配置面板，可按会话选择沙箱类型（local / container / ssh）、容器镜像与项目目录；
选中的 `backend` / `image` 会随 wire `reset` 写入该 thread 的 `thread.toml`，不需要重启进程。

输入框旁的闪电按钮可开启 **YOLO**（自动审批工具调用）：会写入 `~/.electromind/desktop.json`，并重启 wire
（带 `--permission-mode auto`）后生效。

如果要改用容器沙箱（把 agent 的命令执行隔离进容器），需要构建镜像并调整配置。

### 构建默认 agent 镜像

默认镜像 `electromind:latest`（Alpine + uv 管理的 Python + Node），定义在 [src/app/Dockerfile](../../src/app/Dockerfile)：

```bash
cd /path/to/electromind
docker build -t electromind:latest -f src/app/Dockerfile src/app
# 用 podman 同理：podman build -t electromind:latest -f src/app/Dockerfile src/app
```

镜像预装：`bash` `curl` `jq` `git` `uv` `node/npm`。

### 构建 browser 镜像（可选，用于渲染 HTML / 导出 PDF）

在默认镜像基础上加 headless Chromium 与 Noto CJK 字体，定义在 [src/app/Dockerfile.browser](../../src/app/Dockerfile.browser)：

```bash
cd /path/to/electromind
docker build -t electromind:browser -f src/app/Dockerfile.browser src/app
```

### 切到容器 backend

在生效的 `electromind.toml`（`./.pagent/electromind.toml` 或 `~/.electromind/electromind.toml`）里配置：

```toml
[sandbox]
backend = "container"    # 运行时按 docker → podman 顺序探测本机可用的 CLI
image = "electromind:latest"  # 想渲染网页/PDF 就换成 electromind:browser
container_ttl = 300      # 容器主进程 sleep <ttl> 秒，到期 --rm 自清理；0 或不设则 sleep infinity
```

注意：CLI 默认仍是 `--backend local`，但新建任务面板里选中的 backend / image 会覆盖到该次 `reset`。
`container_ttl` 仍从配置读取（面板暂未暴露）。

镜像缺失时不会自动构建或拉取：`docker run` 直接失败并把错误抛回桌面端。上容器 backend 前先确认镜像已 build。

## 目录结构

```text
src/main/       Electron 主进程：拉起 electromind --wire 子进程、IPC、文件预览
src/preload/    contextBridge 桥接层
src/renderer/   渲染进程：三栏 UI、Wire 事件渲染、快捷键、主题
src/shared/     主/渲染共享的协议类型与 Wire 解析、后端拉起逻辑
```
