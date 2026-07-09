# 开发者文档

语言：中文 | [English](/development) | [日本語](/ja/development) | [四川话](/sc/development)

面向贡献者与需要改库内部的人。使用者请从 [文档首页](/zh/) 或 [快速开始](/zh/guide/quick-start) 看起。

## 仓库结构

```text
src/pagent/     v1 库
src/pagentv4/   v4 库（core、runtime、sandbox、skills）
src/app/        应用层（REPL 等，基于 pagentv4）
examples/       按分类放置的可运行示例（v4 见 examples/pagentv4/）
tests/          pytest
docs/           文档
```

核心模块：`agent.py`（循环）、`session.py`（对话与滑动窗口/压缩）、`llm.py`（Provider）、`tool.py`、`tokens.py`、`events.py`。

## 能力清单

| 模块 | 说明 |
|------|------|
| Session | API 形状消息；`SlidingWindowSession`（按 token 裁剪）；`CompactingSession`（LLM 压缩） |
| LLM | `invoke` / `invoke_stream`；`RunEnd` 为单次模型结果 |
| Agent | `run` / `arun` / `arun_events` |
| tokens | `count_tokens`、`count_tokens_detail`、`format_context` |
| events | `RunBegin`、`TextDelta`、`StepEnd`、`RunEnd` 等 — 见 [事件流](./events) |

## 刻意不实现

- 并行工具、RAG、MCP、内置文件/Shell、多模态、检查点等 — 见历史 README 讨论；需在业务层自建。
- `run()` 非流式；流式用 `arun()` / `arun_events()`。

## 与 LangChain / Claude Code

| | pagent | LangChain | Claude Code |
|---|--------|-----------|-------------|
| 定位 | 可嵌入小库 | 大框架 | 终端/IDE 产品 |
| 工具 | 自写 Python | 集成生态 | 内置为主 |
| 适合 | 实验、要透明循环 | 要全家桶集成 | 日常写代码 |

## 本地开发

开发环境推荐 [uv](https://docs.astral.sh/uv/)；不了解 uv 请看 [官方文档](https://docs.astral.sh/uv/)。

```bash
cd pagent
uv sync --group dev --extra search
pip install -e ".[search]"
uv run pre-commit install
uv run pytest -q
```

## 文档站

使用 [VitePress](https://vitepress.dev/)，配置在 `docs/.vitepress/config.mts`，正文在 `docs/`。

```bash
cd docs
npm install
npm run dev            # http://localhost:5173/pagent/
npm run build          # 输出到 docs/.vitepress/dist/
```

Node 依赖放在 `docs/`（`package.json`、`package-lock.json`），仓库根目录保持纯 Python。

**不要**把 `docs/.vitepress/dist/`、`site/` 提交进仓库（已在 `.gitignore`）；`main` 上只保留 `docs/` 里的 Markdown 源文件。

推送到 `main` 后，[docs.yml](https://github.com/SyncLionPaw/pagent/blob/main/.github/workflows/docs.yml) 会在 `docs/` 下执行 `npm run build`，把 `docs/.vitepress/dist/` 发布到 **`gh-pages`** 分支。在仓库 **Settings → Pages** 中选择 **Deploy from branch → gh-pages / root**。

## 发布

`.github/workflows/publish.yml` 在 GitHub Release 发布时推 PyPI；配置 Trusted Publishing（OIDC）：<https://docs.pypi.org/trusted-publishers/>

## 更多设计说明

- [事件类型](./events)
- [reasoning_content 示例](./reasoning)
