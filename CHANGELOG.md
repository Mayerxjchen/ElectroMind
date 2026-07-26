# Changelog

各版本 Release 说明集中在此文件。**发新版时**在下方 `## Unreleased` 写好内容，发版后把该节标题改成 `## 0.x.y — YYYY-MM-DD`。

提取某一版正文用于 GitHub Release：

```bash
./scripts/release-notes.sh 0.7.10
# 或管道给 gh：
./scripts/release-notes.sh 0.7.10 | gh release create v0.7.10 --title v0.7.10 --notes-file -
```

---

## Unreleased

（下次发版前写在这里）

---

## 0.7.20 — 2026-07-26

Subagent 委托、HTTP 后端、配置/路径 SSOT，以及 Desktop 三平台打包与子代理 UI。

### Highlights

- **Subagent**：Runner 帧栈委托（`delegate` tool），子对话与 per-agent workspace 落盘；Desktop / VS Code 展示子代理进度
- **HTTP 后端**：`pagent --http`（SSE `/events` + `POST /command`），与 wire 共用命令核；Desktop 可切 HttpBridge
- **配置 SSOT**：显式 prod/dev home（`~/.pagent` / `--dev`）；`[project.local|cloud]`、`[runner]`、嵌套 sandbox；前端统一读 `~/.pagent`
- **Desktop**：macOS / Windows / Linux 矩阵打包上传 Release；删除会话确认弹窗；入门文档重写
- **CLI**：banner 显示 project；`--yolo` 别名；ascii logo

### Install

```bash
uv tool install --force pagent
```

- VS Code：`pagent-vscode-0.7.20.vsix`
- 桌面端：
  - macOS Apple Silicon：`pagent-Desktop-0.7.20-mac-arm64.zip`
  - Windows x64：`pagent-Desktop-0.7.20-win-x64.zip`
  - Linux x64：`pagent-Desktop-0.7.20-linux-x64.tar.gz`

### Links

- Compare: https://github.com/SyncLionPaw/pagent/compare/v0.7.12...v0.7.20

---

## 0.7.12 — 2026-07-22

沙箱工具白名单，以及 Desktop 新建会话时选择本地容器镜像。

### Highlights

- **沙箱工具白名单**：可配置允许的 sandbox 工具集合
- **Desktop 新建会话**：按 backend 选择本机已有的 `pagent*` 容器镜像，并补充相关文档与默认镜像选项

### Install

```bash
uv tool install --force pagent
```

- VS Code：`pagent-vscode-0.7.12.vsix`
- 桌面端（macOS Apple Silicon）：`pagent-Desktop-0.7.12-arm64.zip`

### Links

- Compare: https://github.com/SyncLionPaw/pagent/compare/v0.7.10...v0.7.12

---

## 0.7.10 — 2026-07-19

Desktop 首次设置向导、环境自检，以及 setup 后 API Key 立即生效。

### Highlights

- **首次设置**：环境 → API Key → 沙箱；未就绪时硬拦截，配置完成前无法使用主界面
- **设置 · 环境自检**：状态灯（uv / CLI / Key / 容器 / 镜像）+ `~/.pagent` 与镜像磁盘占用
- **API Key**：写入 `~/.pagent/pagent.toml` 后，wire 打开会话前从磁盘刷新；Desktop 保存后重启 bridge
- **文档**：Desktop 用户指南补充首次设置与自检说明

### Install

```bash
uv tool install --force pagent
```

- VS Code：`pagent-vscode-0.7.10.vsix`
- 桌面端（macOS Apple Silicon）：`pagent-Desktop-0.7.10-arm64.zip`

### Links

- Compare: https://github.com/SyncLionPaw/pagent/compare/v0.7.9...v0.7.10

---

## 0.7.9 — 2026-07-19

修复 macOS 下载后「已损坏」说明，以及打包版打开黑屏。

### Highlights

- **黑屏修复**：`marked` 打包改用 ESM 入口；打包后 `userData` 不再写入 `.app` 内只读目录
- **后端**：Release 版使用 PATH 里的 `pagent`（`uv tool install pagent`），不再误指 `.app` 内路径
- **macOS**：zip 内附 `打开说明.txt`；文档写明 `xattr -cr` 去掉隔离标记
- 含 0.7.8 CI 修复（桌面 Release 自动构建）

### Install

```bash
uv tool install --force pagent
```

- VS Code：`pagent-vscode-0.7.9.vsix`
- 桌面端（macOS Apple Silicon）：`pagent-Desktop-0.7.9-arm64.zip`

若提示「已损坏」：

```bash
xattr -cr "/Applications/pagent Desktop.app"
```

### Links

- Compare: https://github.com/SyncLionPaw/pagent/compare/v0.7.8...v0.7.9

---

## 0.7.8 — 2026-07-19

修复 Release CI 桌面端打包失败。

### Highlights

- **CI**：desktop job 安装 vscode 共享依赖；`tsconfig` paths 解析 `dompurify` / `marked`
- 其余功能同 0.7.7（上下文圆环、停止按钮、孤立工具卡修复、桌面文档等）

### Install

```bash
uv tool install --force pagent
```

- VS Code：`pagent-vscode-0.7.8.vsix`
- 桌面端（macOS Apple Silicon）：`pagent-Desktop-0.7.8-arm64.zip`

### Links

- Compare: https://github.com/SyncLionPaw/pagent/compare/v0.7.7...v0.7.8

---

## 0.7.7 — 2026-07-19

CLI、VS Code 插件、桌面端。

### Highlights

- **上下文用量圆环**：composer 显示当前回合 token 用量与模型上限估算
- **停止按钮**：运行中可将发送键切换为停止，取消当前回合
- **孤立工具卡修复**：中断或异常退出后不再长期显示「运行中」
- **桌面端文档**：用户菜单「扫码看文档」、文档站 [Desktop 新手指南](https://synclionpaw.github.io/pagent/zh/desktop)
- **桌面端会话**：新建任务可选沙箱类型（local / container / ssh）、YOLO 自动审批
- **发版**：桌面端 `npm run package` 脚本；CI 在 Release 时自动上传 macOS zip

### Install

**CLI（后端，三端共用）**

```bash
uv tool install --force pagent
```

**VS Code 插件** — 下载 `pagent-vscode-0.7.7.vsix`，Extensions → **Install from VSIX...**

**桌面端（macOS Apple Silicon）** — 下载 `pagent-Desktop-0.7.7-arm64.zip`，解压后拖入「应用程序」。

> **macOS 首次打开**：安装包未公证，若被拦截请 **右键 → 打开 → 仍要打开**。

### 配置 API Key

桌面端**不会**首次引导配置，请先创建 `~/.pagent/pagent.toml` 或设置 `DEEPSEEK_API_KEY`。详见 [桌面端文档](https://synclionpaw.github.io/pagent/zh/desktop)。

### Links

- Docs: https://synclionpaw.github.io/pagent/
- Compare: https://github.com/SyncLionPaw/pagent/compare/v0.7.5...v0.7.7

---

## 0.7.5 — 2026-07-17

CLI、VS Code 插件、桌面端三条产品线齐备。

### Highlights

- **桌面端上线**（`editors/desktop`）：Electron 三栏工作台——会话历史 / 对话 / 沙箱 · Artifacts，通过 Wire 拉起 `pagent --wire`
- **三端齐备**：同一 Wire 后端支撑终端 REPL、VS Code 插件、桌面 App
- **`@` 文件引用**：项目与沙箱文件补全，按来源加 `@user:` / `@sandbox:` 前缀
- **Artifacts 富渲染**：Markdown / HTML / PDF / 代码高亮；内联预览可展开为右侧面板
- **主题与快捷键**：明暗主题；`⌘L` / `⌘R` 收侧栏、`⌘K` 快捷键面板

### Install

```bash
uv tool install --force pagent
```

- VS Code：`pagent-vscode-0.7.5.vsix`
- 桌面端（macOS arm64）：`pagent-Desktop-0.7.5-arm64.zip`

### Notes

- 桌面 `.app` 未公证，分发到其他 Mac 首次打开需右键 → 打开
- API Key：`~/.pagent/pagent.toml` 或 `DEEPSEEK_API_KEY`

### Links

- Compare: https://github.com/SyncLionPaw/pagent/compare/v0.7.0...v0.7.5

---

## 0.7.0 — 2026-07-16

桌面端早期 macOS 构建与插件打包。

### Links

- Compare: https://github.com/SyncLionPaw/pagent/compare/v0.6.1...v0.7.0

---

## 0.6.1 — 2026-07-15

统一 pagent home、会话列表与 SSH 工作目录；修复 VS Code「恢复会话」找错路径。

### Highlights

- **统一 home**：配置 / threads / skills 共用同一根（工作区 `.pagent/` 或 `~/.pagent/`）
- **恢复会话**：插件发 `list_threads`，由后端按 cwd 解析 home
- **SSH 默认 workdir**：`~/pagent`（远端自动 mkdir）
- **VS Code**：setup 写入当前 home 的 `pagent.toml`

### Install

```bash
uv tool install --force pagent
```

扩展：`pagent-vscode-0.1.1.vsix`

### Notes

- 旧 thread 若冻结了 `ssh.workdir = "~/"`，需**新会话**才会用 `~/pagent`

### Links

- Compare: https://github.com/SyncLionPaw/pagent/compare/v0.6.0...v0.6.1

---

## 0.6.0 — 2026-07-15

VS Code 插件上线、用户级配置与 setup、Wire 更稳的后端启动。

### Highlights

- **VS Code 扩展**：侧栏 / 编辑器区聊天、流式回复、思考面板、工具卡与审批、会话恢复、local/SSH 切换
- **全局 CLI**：`uv tool install pagent` + `pagent --wire`
- **用户级配置** `~/.pagent/pagent.toml`
- **首次 setup**：缺 Key 时交互引导（终端 + 插件）
- **Wire 错误可见**：失败 / 退出 / 超时出错误气泡
- **Trace CLI**：`pagent-openai`、`pagent-trace`

### Install

```bash
uv tool install pagent
pagent              # REPL
pagent --wire       # 插件 / 桌面端后端
```

### Breaking / Notes

- 推荐 **`uv tool install pagent`**，不再依赖在项目目录 `uv run`
- API Key 勿写进仓库内 `pagent.toml`

### Links

- Compare: https://github.com/SyncLionPaw/pagent/compare/v0.5.0...v0.6.0

---

## 0.5.0 及更早

见 [GitHub Releases](https://github.com/SyncLionPaw/pagent/releases)。
