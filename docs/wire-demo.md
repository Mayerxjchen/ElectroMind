# Wire demo (browser UI)

Full-stack example: FastAPI + single-page chat consuming `Agent.arun_wire()`.

## Run

```bash
export DEEPSEEK_API_KEY="your-key"
uv run --with fastapi --with uvicorn python examples/wire_demo/server.py
```

Open **http://127.0.0.1:8765**

## Stop

- **Server:** `Ctrl+C` in the terminal
- **Streaming reply:** click **停止** in the UI

Details: [`examples/wire_demo/README.md`](https://github.com/SyncLionPaw/pagent/blob/main/examples/wire_demo/README.md)

See also [Wire protocol](./wire.md).
