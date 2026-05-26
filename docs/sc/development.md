# 开发者文档

语言：四川话 | [English](/development) | [普通话](/zh/development) | [日本語](/ja/development)

给要改库内部的贡献者看。用库的先去 [文档首页](/sc/) 或 [赶紧上手](./guide/quick-start)。

## 仓库结构

```text
src/pagent/     库代码
examples/       能跑的示例
tests/          pytest
docs/           文档
```

核心：`agent.py`（循环）、`session.py`（对话、滑动窗口/压缩）、`llm.py`（Provider）、`tool.py`、`tokens.py`、`events.py`。

## 能力清单

| 模块 | 说明 |
|------|------|
| Session | API 形状消息；`SlidingWindowSession`（按 token 裁）；`CompactingSession`（LLM 压缩） |
| LLM | `invoke` / `invoke_stream`；`RunEnd` 是单次模型结果 |
| Agent | `run` / `arun` / `arun_events` / `arun_wire` |
| tokens | `count_tokens`、`count_tokens_detail`、`format_context` |
| events | `RunBegin`、`TextDelta`、`StepEnd`、`RunEnd` 等 — 见 [事件流](./events) |

## 刻意莫做

- 并行工具、RAG、MCP、内置文件/Shell、多模态、检查点 — 业务层自己整。
- `run()` 非流式；流式用 `arun()` / `arun_events()`。

## 本地开发

```bash
cd pagent
uv sync --group dev --extra search
pip install -e ".[search]"
uv run pre-commit install
uv run pytest -q
```

## 文档站

[VitePress](https://vitepress.dev/)，配置在 `docs/.vitepress/config.mts`。

```bash
cd docs
npm install
npm run dev
npm run build
```

推 `main` 后 [docs.yml](https://github.com/SyncLionPaw/pagent/blob/main/.github/workflows/docs.yml) 把 `docs/.vitepress/dist/` 发到 **`gh-pages`**。仓库 **Settings → Pages** 选 **gh-pages / root**。

## 更多

- [事件类型](./events)
- [reasoning_content 例子](./reasoning)
