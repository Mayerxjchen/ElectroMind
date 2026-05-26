# Wire demo (local browser UI)

中文读者：侧栏 **Wire demo（本地）** 或 [简体中文首页](/zh/)。命令与下文相同。

Full-stack example: **FastAPI** serves a chat UI; the browser consumes **`Agent.arun_wire()`** as `application/x-ndjson`.

::: tip 在线文档站不能代替本地 demo
GitHub Pages 只托管静态文档。要体验流式对话，请在本地启动服务。
:::

## Run

```bash
git clone https://github.com/SyncLionPaw/pagent.git
cd pagent
export DEEPSEEK_API_KEY="your-key"

uv run --with fastapi --with uvicorn python examples/wire_demo/server.py
```

Open **http://127.0.0.1:8765**

## Stop

- **Server:** `Ctrl+C` in the terminal
- **While streaming:** click **停止** in the UI (aborts the HTTP request)

## What it shows

- Chat UI with tool cards and optional reasoning block
- Side drawer with raw Wire NDJSON lines
- Same protocol as [Wire protocol](./wire) — not a separate message system

Source: [examples/wire_demo/](https://github.com/SyncLionPaw/pagent/tree/main/examples/wire_demo) on GitHub.
