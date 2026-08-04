"""HTTP 后端：与 wire 共享同一套命令处理核，只换传输壳。

对齐关系（一字不改命令/事件 JSON）：

- wire 的 stdin（收 JSON 命令）  → ``POST /command``（body 是同一个命令对象）
- wire 的 stdout（出事件流）      → ``GET /events``（SSE，每行事件一个 data 帧）

会话模型沿用 wire 的"单进程·单会话·单 runner·一次一轮"，正是 cloud
agent-in-the-pod 形态（一个 pod 服务一个会话）。server 跑在 uvicorn 的
asyncio loop，``inbound.permit/deny/cancel`` 与 ``run`` 同 loop，无跨线程 marshal。

依赖 fastapi / uvicorn，装 ``electromind[server]`` 才可用。
"""

import asyncio
import os

from .config import ReplConfig
from .transport import FanoutSink, set_active_sink
from .wire import (
    clean_empty_threads,
    handle_command,
    log,
    parse_command,
    slash_commands_line,
)

AUTH_ENV = "ELECTROMIND_SERVER_TOKEN"


class WireHttpSession:
    """HTTP 会话视图：串行化命令分派（对齐 wire 主循环的顺序处理）。

    状态模型与 CLI 的 EmbeddedAgentClient 对齐在同一 Harness 层：
    - 多 Thread 的 Runner / 后台 Run 生命周期在 wire 的 ``state["_runners"]``
      与模块级 ``_harness_manager``（ThreadSessionManager）里，逐 Thread 独立
    - ``self.runner`` 只是“当前选中 Thread”的视图指针（resume 切换），
      与 Desktop 的 wire 客户端同一语义；切换/取消不触碰其他 Thread
    """

    def __init__(self, config: ReplConfig, sink: FanoutSink) -> None:
        self.config = config
        self.sink = sink
        self.runner = None  # 当前选中 Thread 的 Runner 视图指针
        self.state: dict = {"turn": None, "client_features": {}}
        self.had_user_turn = False
        self._lock = asyncio.Lock()

    async def dispatch(self, command: dict) -> None:
        """处理一条命令；同一时刻只处理一条（user 起后台 turn 后立即返回）。

        runner 生命周期委托 wire 命令核：多 Thread 并行、切换不关闭 Runner、
        取消只作用于选中 Thread——与 CLI 客户端同一 Harness 状态模型。
        """
        async with self._lock:
            prev_count = (
                len(self.runner.messages.data) if self.runner is not None else 0
            )
            self.runner = await handle_command(
                command, self.runner, self.config, self.state
            )
            if self.runner is not None and len(self.runner.messages.data) > prev_count:
                self.had_user_turn = True

    async def close(self) -> None:
        task = self.state.get("turn")
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self.runner is not None:
            thread_id = self.runner.thread.id
            await self.runner.close()
            clean_empty_threads(
                keep_thread_ids={thread_id} if self.had_user_turn else set()
            )


def check_auth(header_value: str | None) -> bool:
    """校验 Authorization: Bearer <token>。未设 ELECTROMIND_SERVER_TOKEN 时放行。"""
    token = os.getenv(AUTH_ENV, "").strip()
    if not token:
        return True
    if not header_value:
        return False
    prefix = "Bearer "
    if not header_value.startswith(prefix):
        return False
    return header_value[len(prefix) :].strip() == token


def sse_frame(line: str) -> str:
    """把一行事件包成一个 SSE data 帧。"""
    return f"data: {line.rstrip()}\n\n"


async def event_stream(sink: FanoutSink):
    """一个 SSE 连接的事件生成器：先回放 slash 菜单，再转发 sink 广播直到哨兵。"""
    queue = sink.subscribe()
    try:
        # 新连接先回放 slash 菜单，对齐 wire 启动即下发的行为。
        yield sse_frame(slash_commands_line())
        while True:
            line = await queue.get()
            if line is None:
                break
            yield sse_frame(line)
    finally:
        sink.unsubscribe(queue)


def build_app(config: ReplConfig):
    """构造 FastAPI 应用。进程级把事件出口切到 FanoutSink，命令核复用 wire。"""
    from contextlib import asynccontextmanager

    from fastapi import FastAPI, Header, HTTPException, Request
    from fastapi.responses import StreamingResponse

    sink = FanoutSink()
    set_active_sink(sink)
    session = WireHttpSession(config, sink)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        await session.close()
        sink.close()

    app = FastAPI(title="electromind http backend", lifespan=lifespan)

    def require_auth(authorization: str | None) -> None:
        if not check_auth(authorization):
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/health")
    async def health():
        """公共健康检查：不鉴权、不调模型、不读密钥、不创建线程。"""
        return {"ok": True, "service": "electromind"}

    @app.get("/events")
    async def events(authorization: str | None = Header(default=None)):
        require_auth(authorization)
        return StreamingResponse(event_stream(sink), media_type="text/event-stream")

    @app.post("/command")
    async def command(
        request: Request, authorization: str | None = Header(default=None)
    ):
        require_auth(authorization)
        raw = await request.body()
        parsed = parse_command(raw.decode("utf-8"))
        if parsed is None:
            raise HTTPException(status_code=400, detail="invalid command")
        await session.dispatch(parsed)
        return {"ok": True}

    return app


def run_http(config: ReplConfig, *, host: str = "127.0.0.1", port: int = 8848) -> int:
    """启动 uvicorn 跑 HTTP 后端。缺 fastapi/uvicorn 时给出安装提示。"""
    try:
        import uvicorn
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "HTTP 后端需要 fastapi/uvicorn：安装 `pip install 'electromind[server]'`"
        ) from exc

    if not os.getenv(AUTH_ENV, "").strip():
        log(f"[http] 未设 {AUTH_ENV}，接口不鉴权（仅建议本机/受信任内网）")

    app = build_app(config)
    log(f"[http] ready on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0
