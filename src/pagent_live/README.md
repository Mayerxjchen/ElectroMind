# pagent_live

- **LiveAgent** — `Agent` + `bus`
- **DuplexBus** — `push_owire` / `get_owire` / `push_iwire` / `get_iwire`
- **context** — `ToolContext.emit` → owire；Agent `poll_iwire` ← iwire；会合用 `wait_reply`

See [spec.md](spec.md)（出站 emit / 入站检查点）。

**Interactive demo:** [examples/demo2/README.md](../../examples/demo2/README.md) — includes a full **猜人游戏** walkthrough using `ask_user`.
