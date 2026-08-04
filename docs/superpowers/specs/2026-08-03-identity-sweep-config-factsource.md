# 清除 pAgent 遗留与重复配置事实源（设计文档第 3 项）

日期：2026-08-03
状态：已实现
来源：用户粘贴的设计文档第 3 项

## 目标

1. 冻结配置事实源为四层，消除仓库内互相声称自己是默认的三份 TOML。
2. 全仓库执行一次 Identity Sweep：pagent / electromindv4 / 旧仓库 URL / 旧镜像名 /
   旧数据目录 / 旧测试命名 / 旧文档站点。
3. 重写 AGENTS.md 为当前开发者架构说明。

## 配置事实源（冻结后）

优先级从低到高：

| 层 | 位置 | 说明 |
|---|---|---|
| 1 | `src/electromind/resources/default-config.toml` | 包内**唯一**内置默认（随 wheel 打包） |
| 2 | `~/.electromind/config.toml` | 用户设置（生产模式 home） |
| 3 | `<project>/.electromind/config.toml` | 项目设置（仅受信任项目；dev 模式 home 即项目目录，不重复加载） |
| 4 | `<project>/.electromind/config.local.toml` | 本机私有设置 |
| — | `--config <file>` | CLI 显式叠加（最高） |

home 二选一语义不变（`activate_home`：prod → `~/.electromind`，dev → `<root>/.electromind`）。

### 已删除的重复默认

- `src/app/pagent.toml`（旧运行时默认，4142 B）
- `src/app/electromind.toml`（6333 B 全字段模板）
- `src/template/pagent.toml` / `src/template/electromind.toml`（与上两份之一完全相同）
- `src/template/` 目录整体删除

### 兼容迁移（一次性）

旧文件名 `electromind.toml` / `electromind.local.toml` 只在新名缺失时改名继承
（`app.config._adopt_legacy`，三个 scope 都走），之后全链路只认新名。根目录遗留的
`./electromind.toml` 不读取（与既有行为一致，`.gitignore` 追加忽略）。

## Identity Sweep 结果

| 类别 | 旧 → 新 |
|---|---|
| 仓库 URL | `github.com/SyncLionPaw/pagent` → `github.com/Mayerxjchen/ElectroMind`（git remote 已是该地址） |
| 文档站点 | `synclionpaw.github.io/pagent|electromind` → `mayerxjchen.github.io/electromind`（用户确认，站点尚未上线） |
| 镜像名 | `pagent:latest` / `pagent:browser` → `electromind:latest` / `electromind:browser`（含默认 config 与 Dockerfile 注释） |
| 数据目录 | `~/.pagent` / `./.pagent` → `~/.electromind` / `./.electromind` |
| 占位符 | `{pagent_home}` → `{electromind_home}`（兼容旧 `{home}` 展开逻辑不变） |
| 助手标签 | `assistant_label = "pagent"` → `"electromind"` |
| SSH 远端目录 | `~/pagent` → `~/electromind` |
| 模块名 | `pagentv4` → `electromind`（docstring / 注释 / trace CLI 文案） |
| 测试命名 | `tests/test_pagentv4_*.py`（25 个）→ `test_electromind_*.py`；`PAGENTV4_*` 环境变量 → `ELECTROMIND_*` |
| VS Code 插件 | 全套 rebrand：`pagent-vscode` → `electromind-vscode`，命令/视图/配置命名空间 `pagent.*` → `electromind.*`，publisher → `mayerxjchen`，home 解析 `~/.pagent/pagent.toml` → `~/.electromind/config.toml`，删除旧 vsix 产物 |
| Desktop 端 | `onInstallPagent` → `onInstallElectromind`，`electromind.toml` → `config.toml`，文档 URL 更新 |

### 未改动（有意保留）

- `LICENSE` 版权行 `Copyright (c) 2026 gongyulei / SyncLionPaw` —— 法律归属，未获指示不改。
- `docs/superpowers/` 历史设计文档（plans/specs）里对旧文件名的引用 —— 历史记录，不追改。

## AGENTS.md 重写

删除 `electromindv4` 目录描述、`llms.txt` / 文档站点指针（均已不存在），
改为当前架构：`src/electromind/`（core / ithread / conversation / runtime / sandbox /
skills / execution / harness / adapters / tools / trace / paths）+ `src/app/`（CLI/REPL/
wire/http）+ `editors/` + `skills/` + 四层配置事实源 + 关键约定（Wire、thread.toml 冻结、
Skills SSOT、Workspace Trust）+ CI 闸门。

## 顺带修复

- `scripts/ci-check.sh`：删除 `cd docs && npm ci && npm run build` 步骤（docs/ 已无
  package.json，该步骤必然失败；文档站点已随 docs 收敛拆除）。
- 开发环境：`.venv/bin/*` 入口脚本 shebang 指向旧仓库路径
  `/Users/chenxuanjie/agent/pagent/.venv/bin/python3`（仓库改名后 venv 未重建），
  重建 .venv 修复。
- `src/electromind/skills/scopes.py` E741 一行修复（未提交工作中文件，格式化随 ci-check 一起过）。
