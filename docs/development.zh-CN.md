# 开发者文档

语言：中文 | [English](./development.md)

面向贡献者与需要改库内部的人。使用者请从 [文档首页](/zh/) 或 [快速开始](/zh/guide/quick-start) 看起。

## 仓库结构

```text
src/pagent/     库代码
examples/       可运行示例
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
| events | `RunBegin`、`TextDelta`、`StepEnd`、`RunEnd` 等 — 见 [events.zh-CN.md](./events.zh-CN.md) |

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

- [事件类型](./events.zh-CN.md)
- [reasoning_content 示例](./reasoning.zh-CN.md)
