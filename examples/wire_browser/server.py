"""Wire browser example: FastAPI + NDJSON stream from pagentv4 events.

Usage (from repo root):

    export DEEPSEEK_API_KEY="your-key"
    uv run --with fastapi --with uvicorn python examples/wire_browser/server.py

Open http://127.0.0.1:8765
"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from pagentv4 import AgentCore, DeepSeek, VanillaRunner, tool

STATIC_DIR = Path(__file__).resolve().parent / "static"

SYSTEM_PROMPT = """你是「小帕」，运行在 pagent wire browser example 里的对话助手。这是你的人设，必须始终遵守。

【怎么答】
- 用户用中文则用中文，用英文则用英文；默认中文。
- 自我介绍示例：「你好，我是小帕，这个示例里的助手，可以聊天、做简单计算。需要算什么或想了解 Wire，直接说就行。」
- 段落宜短，避免冗长套话。"""


@tool()
def calculate(expression: str) -> str:
    """Evaluate a math expression and return the result.

    Args:
        expression: A Python math expression, e.g. "2 + 3 * 4".
    """
    try:
        return str(eval(expression, {"__builtins__": {}}, {}))
    except Exception as e:
        return f"Error: {e}"


def make_runner() -> VanillaRunner:
    agent = AgentCore(
        DeepSeek("deepseek-v4-flash"),
        system=SYSTEM_PROMPT,
        tools=[calculate],
        max_turns=24,
    )
    return VanillaRunner(agent)


def make_agent() -> AgentCore:
    """Compatibility helper for tests that only need the configured AgentCore."""
    return AgentCore(
        DeepSeek("deepseek-v4-flash"),
        system=SYSTEM_PROMPT,
        tools=[calculate],
        max_turns=24,
    )


app = FastAPI(title="pagent wire browser")


class ChatRequest(BaseModel):
    message: str


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/chat")
async def chat(body: ChatRequest):
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="DEEPSEEK_API_KEY is not set on the server",
        )

    runner = make_runner()

    async def ndjson_stream():
        async for line in runner.run(message, return_type="acp"):
            yield line

    return StreamingResponse(ndjson_stream(), media_type="application/x-ndjson")


def main():
    import uvicorn

    host = os.getenv("PAGENT_WIRE_HOST", "127.0.0.1")
    port = int(os.getenv("PAGENT_WIRE_PORT", "8765"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
