# electromind — instructions for coding agents

You are working with **electromind**（ElectroMind）：面向科学计算与机器学习势函数（MLIP）工作流的
AI Agent —— async Python 库（Agent + Runner + Sandbox + Skills）+ 终端 REPL + Desktop 编辑器。
用下面的布局与约定定位代码，别猜 API。

## 接口支持级别（2026-08-05 起，详见 docs/superpowers/specs/2026-08-05-scope-contraction-cli-desktop.md）

- **正式支持**：CLI（`src/app/cli*` `src/app/repl*`）与 Desktop（`editors/desktop/`）。
  CLI 是完整功能入口与参考实现；Desktop 是 CLI 能力的图形化呈现。
- **Wire（--wire）**：Desktop 的**内部传输层**，不做公开 API 兼容承诺，仅服务 Desktop。
- **Experimental / maintenance-only**：`src/app/http_server.py`。不删除、不新适配功能、
  不承诺兼容；既有测试保留以防腐化。
- **已删除**（2026-08-05）：`editors/web/`、`editors/vscode/`（历史版本可从 git 找回）。
- 新功能改动核心时只要求 CLI + Desktop + Wire 保持一致；不验收 HTTP 一致性。

## 仓库布局

```text
src/electromind/            核心库
  core/                     AgentCore / Message / Provider / Tool / Event（事件模型）
  ithread/                  IThread Protocol + ThreadSpec（thread.toml 结构）
  conversation/             ConversationStore：JSONL / SQLite 对话持久化
  runtime/                  Runner（base / chat / code / vanilla）、loop_core、inbound
                            （Steer/Cancel/Permit/Deny）、thread、hooks、run_state
  sandbox/                  Backend + Sandbox 门面；backends/（local / container / ssh）、
                            tools（run_command / read_file / write_file / str_replace / …）
  skills/                   SKILL.md 发现、catalog、激活、挂载、运行时、watcher
  execution/                执行模式上下文 / plan / probe / resolver
  harness/                  执行生命周期与持久化：SessionManager、checkpoints、
                            mutations、inbound 审批、protocol_v2（wire/http/CLI 共用）、
                            workspace 状态
  adapters/                 ACP 等外部协议编解码（Wire 序列化）
  tools/                    harness 工具实现：web_search / fetch_url / delegate_to_subagent
  trace/                    messages.jsonl 轨迹可视化 / OpenAI 导出
  paths.py                  数据根与配置路径常量
  resources/default-config.toml   包内唯一内置默认配置
src/app/                    CLI / REPL 应用层（`uv run electromind` 入口）
  cli.py cli_parser.py      CLI 入口与参数
  config.py                 ReplConfig / Settings 多 scope 加载与合并
  repl.py                   TUI REPL；concurrent_repl.py 并发模型
  wire.py                   --wire stdio NDJSON 后端（Desktop 内部传输层）
  http_server.py            --http SSE 后端（experimental / maintenance-only）
  sessions.py setup.py     会话管理 / 首次 API Key 引导
  commands/ output/ tui/   子命令、输出渲染、TUI 组件
editors/                    desktop（Electron，正式支持）
skills/                     内建科学计算技能包（CP2K / VASP / LAMMPS / DeepMD / MCMC），
                            经 uv_build data 打进安装产物
tests/                      pytest（应用 / 库 / sandbox / 协议）
scripts/                    ci-check.sh（提交前本地闸门）、release.sh、build-standalone.sh
docs/superpowers/           设计文档（plans / specs）
```

## 配置事实源（四层，优先级低 → 高）

1. `src/electromind/resources/default-config.toml` —— 包内**唯一**内置默认
2. `~/.electromind/config.toml` —— 用户设置（生产模式 home）
3. `<project>/.electromind/config.toml` —— 项目设置（仅受信任项目；dev 模式 home 就是项目目录）
4. `<project>/.electromind/config.local.toml` —— 本机私有设置
外加 `--config <file>` 显式叠加（最高）。

home 二选一由入口 `activate_home()` 定一次：prod → `~/.electromind`，dev（`--dev`）→ `<root>/.electromind`；
配置 / threads / skills 同根。旧文件名 `electromind.toml` 只在 `config.toml` 缺失时一次性改名继承
（`app.config._adopt_legacy`），之后全链路只认新名，不再产生第二事实源。

## 关键约定

- **Wire（--wire）**：stdout 每行一个 JSON-RPC 2.0 notification（`method` = 事件类名，无 `id`）；
  stdin 每行一个 `{"cmd": ...}` 命令。序列化见 `src/electromind/adapters/acp.py`。
- **入站控制面**（cancel / steer / permit / deny）不属于 Wire 事件流：Wire 里经 stdin 命令驱动，
  HTTP 层由宿主实现（`src/app/http_server.py` + `src/electromind/runtime/inbound.py`）。
- **thread.toml 冻结**：新建会话时把 sandbox / agent / skills / `[sub.*]` 从合并配置冻结进
  thread.toml，之后以磁盘为准（resume 不漂移）。
- **Skills SSOT**：运行时只读 thread.toml 里冻结的 `[agent] skills`；项目 skills 自动发现由
  `thread.spec.project_path` 驱动。
- **Workspace Trust**：未受信任项目不加载 Project / Local 配置（fail-closed）；
  `electromind config trust` 管理。
- 库层新增功能进 `src/electromind/`，CLI 专属逻辑进 `src/app/`，不要互相倒灌。

## 常用命令

```bash
uv run electromind              # REPL（prod 模式）
uv run electromind --dev        # dev 模式：数据落在 ./.electromind
uv run electromind --wire       # stdio NDJSON 后端
uv run electromind --http       # SSE 后端
uv run pytest tests/            # 测试
```

## CI before commit / push

**总是先跑** `./scripts/ci-check.sh`（= `uv sync --group dev --frozen` + ruff check + ruff format
--check + pytest --cov），本地不绿别提交。可选 git hook（一次性）：

```bash
git config core.hooksPath .githooks
chmod +x scripts/ci-check.sh .githooks/pre-push
```

## 发布

见 `RELEASING.md`：`uv build` 出 wheel/sdist，`scripts/build-standalone.sh` 出单文件，
`scripts/release.sh --publish` 出 GitHub Release。仓库：`github.com/Mayerxjchen/ElectroMind`。
