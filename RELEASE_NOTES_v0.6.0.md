# pagent v0.6.0

VS Code 插件上线、用户级配置与 setup、Wire 更稳的后端启动；同时整理 sandbox / runtime / trace CLI。

---

## Highlights

- **VS Code 扩展**（`editors/vscode`）：侧栏 / 编辑器区聊天、流式回复、思考面板、工具卡与审批、会话恢复、local/SSH 切换
- **全局 CLI**：插件默认 `pagent --wire`，通过 `uv tool install pagent` 安装，不再在打开的工作区里 `uv run`
- **用户级配置** `~/.pagent/pagent.toml`：跨项目放 `api_key` / `model` / `base_url`
- **首次 setup**：缺 Key 时交互引导（终端 + 插件）
- **Wire 错误可见**：对话失败 / 进程退出 / 超时会出错误气泡，不再一直转圈
- **Trace CLI**：`pagent-openai`、`pagent-trace` 导出与 HTML 查看轨迹

## Install

```bash
uv tool install pagent
# 开发本仓库时：
# uv tool install --editable --force .
```

```bash
pagent                 # REPL
pagent --wire          # stdio NDJSON 后端（插件用）
pagent-trace …         # 轨迹 HTML
pagent-openai …        # OpenAI 风格导出
```

配置优先级：bundled 默认 → `~/.pagent/pagent.toml` → 项目 `./pagent.toml` → CLI。

## VS Code 插件

路径：`editors/vscode`（F5 扩展开发宿主调试）。

| 能力 | 说明 |
|------|------|
| Chat UI | 流式 Markdown、思考折叠、工具卡、slash 命令 |
| 会话 | 新会话 / 恢复会话（读 `~/.pagent/threads/`） |
| Sandbox | 输入区切换 local / docker / podman / ssh |
| Setup | 无 CLI 时引导 `uv tool install`；无 Key 时引导写入 `~/.pagent` |
| 错误 | Wire `Error` 事件 + 进程退出 / 60s 超时提示 |

会话与沙箱默认落在 `~/.pagent/`；工作区只用于项目级 `pagent.toml` / skills，不用于定位 Python 包。

## CLI / App

- `~/.pagent/pagent.toml`：用户级 provider 配置（setup 可写 api_key、model、base_url）
- Wire **惰性打开 runner**：先 `ready` 再收命令，避免切换 backend 时卡在空会话沙箱上
- Wire / 插件：打开失败、一轮失败、resume 失败会发 `Error` 控制事件
- REPL：缺 API Key 时 TTY 下交互 setup

## Runtime / Sandbox / Skills

- Runner `run_state` 阶段，REPL 展示状态
- Sandbox 后端解耦与统一错误 / 资源装配
- 容器 backend 自动探测；bundled 默认 docker
- Skills：YAML frontmatter 解析增强
- 路径与配置默认行为整理

## Trace

- `pagent-openai`：messages / thread → OpenAI 风格导出
- `pagent-trace`：轨迹 HTML 查看
- `pagentv4.trace` 模块整理

## Breaking / Notes

- 推荐安装方式从「在项目目录 `uv run pagent`」转向 **`uv tool install pagent`**（全局 `~/.local/bin/pagent`）
- API Key 勿再写进仓库内 `src/app/pagent.toml`；用 `~/.pagent/pagent.toml` 或 `DEEPSEEK_API_KEY`
- 会话 / workspace / conversation 默认在 `~/.pagent/`（与 cwd 解耦）；项目仍可用 `./pagent.toml`、`./.pagent/skills/`

## Links

- Docs: https://synclionpaw.github.io/pagent/
- Repo: https://github.com/SyncLionPaw/pagent
- Compare: https://github.com/SyncLionPaw/pagent/compare/v0.5.0...v0.6.0
