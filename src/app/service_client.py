"""ServiceAgentClient — HTTP Service 客户端（CLI-6）。

与 EmbeddedAgentClient 同一方法面（send_input / cancel_run / resolve_approval /
snapshot / events），通过 ``POST /command`` + ``GET /events``（SSE）接入常驻
Harness Service（``electromind service start``）。CLI、Desktop、HTTP 与脚本
复用同一 Harness 协议。

传输可注入（``_post`` / ``_sse_lines``），测试用假传输；默认 urllib + 线程。
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from collections import deque

from electromind.harness.inbound import InputReceipt

AUTH_ENV = "ELECTROMIND_SERVER_TOKEN"


class ServiceAgentClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8848",
        *,
        auth_token: str | None = None,
        event_sink=None,
        buffer_limit: int = 500,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._auth = auth_token or os.environ.get(AUTH_ENV, "")
        self._event_sink = event_sink  # callable(dict event line)
        self._events_task: asyncio.Task | None = None
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._pending: dict[str, asyncio.Future] = {}  # request_id → future
        self._thread_buffer: dict[str, deque] = {}  # thread_id → 最近事件
        self._buffer_limit = buffer_limit
        self._closed = False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """建立 SSE 事件订阅。"""
        if self._events_task is None:
            self._events_task = asyncio.create_task(self._sse_reader())

    async def close(self) -> None:
        self._closed = True
        if self._events_task is not None:
            self._events_task.cancel()
            try:
                await self._events_task
            except asyncio.CancelledError:
                pass
            self._events_task = None
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    # ------------------------------------------------------------------
    # 传输（可注入）
    # ------------------------------------------------------------------

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._auth:
            headers["Authorization"] = f"Bearer {self._auth}"
        return headers

    async def _post(self, payload: dict) -> dict:
        """POST /command；返回 {"ok": true}。"""

        def _do() -> dict:
            request = urllib.request.Request(
                f"{self.base_url}/command",
                data=json.dumps(payload).encode("utf-8"),
                headers=self._headers(),
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))

        return await asyncio.to_thread(_do)

    async def _sse_lines(self):
        """SSE 行流（线程生产 + 队列消费，不整体缓冲）；结束返回 None。"""
        import threading

        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _produce() -> None:
            try:
                request = urllib.request.Request(
                    f"{self.base_url}/events", headers=self._headers()
                )
                with urllib.request.urlopen(request, timeout=None) as resp:
                    for raw in resp:
                        loop.call_soon_threadsafe(queue.put_nowait, raw)
            except Exception:
                pass
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=_produce, daemon=True).start()
        while True:
            raw = await queue.get()
            if raw is None:
                break
            yield raw
        yield None

    async def _sse_reader(self) -> None:
        """SSE 消费：data 帧 → 事件行；request_id 关联完成 pending future。"""
        buffer = b""
        try:
            async for raw in self._sse_lines():
                if raw is None:
                    break
                buffer += raw
                while b"\n\n" in buffer:
                    frame, buffer = buffer.split(b"\n\n", 1)
                    data = None
                    for line in frame.splitlines():
                        if line.startswith(b"data:"):
                            data = line[5:].strip()
                    if data is None:
                        continue
                    try:
                        line = json.loads(data.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        continue
                    self._handle_line(line)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass  # 连接中断：由调用方决定是否重连
        finally:
            if not self._closed:
                # 一次性连接结束 → 通知等待者
                for fut in list(self._pending.values()):
                    if not fut.done():
                        fut.set_exception(
                            ConnectionError("service events stream closed")
                        )
                self._pending.clear()

    def _handle_line(self, line: dict) -> None:
        params = line.get("params", {}) or {}
        thread_id = str(params.get("thread_id", ""))
        if thread_id:
            buf = self._thread_buffer.setdefault(
                thread_id, deque(maxlen=self._buffer_limit)
            )
            buf.append(line)
        request_id = str(params.get("request_id", ""))
        if request_id and request_id in self._pending:
            fut = self._pending.pop(request_id)
            if not fut.done():
                fut.set_result(line)
        if self._event_sink is not None:
            self._event_sink(line)

    # ------------------------------------------------------------------
    # AgentClient 面
    # ------------------------------------------------------------------

    async def send_input(
        self,
        thread_id: str,
        text: str,
        *,
        delivery: str = "auto",
        mode: str | None = None,
        request_id: str | None = None,
        timeout: float = 15.0,
    ) -> InputReceipt:
        """POST input/send；等待同 request_id 的 input/state ACK 返回 receipt。"""
        from electromind.harness.identity import new_request_id

        request_id = request_id or new_request_id()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[request_id] = fut
        try:
            await self._post(
                {
                    "cmd": "input/send",
                    "thread_id": thread_id,
                    "text": text,
                    "delivery": delivery,
                    "mode": mode or "",
                    "request_id": request_id,
                }
            )
        except Exception:
            self._pending.pop(request_id, None)
            raise
        ack = await asyncio.wait_for(fut, timeout)
        params = ack.get("params", {}) or {}
        return InputReceipt(
            message_id=str(params.get("message_id", "")),
            thread_id=str(params.get("thread_id", thread_id)),
            state=_state_from_str(str(params.get("state", "accepted"))),
            detail=str(params.get("detail", "")),
            target_run_id=params.get("target_run_id") or None,
        )

    async def cancel_run(self, thread_id: str, run_id: str | None = None) -> bool:
        """取消指定 Thread 的 Run（wire 的 cancel 作用于当前选中 thread）。

        验收 P0-4：run_id 原样传给服务端校验，旧 Run 的迟到 Cancel 被拒绝。
        """
        # 先切到目标 thread（后台 Run 不受影响），再 cancel
        await self._post({"cmd": "resume", "thread_id": thread_id})
        await self._post(
            {"cmd": "cancel", "thread_id": thread_id, "run_id": run_id or ""}
        )
        return True

    async def resolve_approval(
        self,
        thread_id: str,
        run_id: str,
        approval_id: str,
        approved: bool,
        tool_call_id: str | None = None,
    ) -> bool:
        await self._post(
            {
                "cmd": "permit" if approved else "deny",
                "tool_call_id": tool_call_id or "",
                "approval_id": approval_id,
                "thread_id": thread_id,
                "run_id": run_id,
            }
        )
        return True

    async def snapshot(self, thread_id: str, *, timeout: float = 15.0) -> dict:
        """请求 thread/snapshot，从事件流取回快照响应。"""
        from electromind.harness.identity import new_request_id

        request_id = new_request_id()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[request_id] = fut
        try:
            await self._post(
                {
                    "cmd": "thread/snapshot",
                    "thread_id": thread_id,
                    "request_id": request_id,
                }
            )
        except Exception:
            self._pending.pop(request_id, None)
            raise
        response = await asyncio.wait_for(fut, timeout)
        return response.get("params", {})

    def events(self, thread_id: str, after_seq: int = 0) -> list[dict]:
        """缓冲区内 after_seq 之后的事件（断线重连的增量恢复）。"""
        buf = self._thread_buffer.get(thread_id, deque())
        return [
            line
            for line in buf
            if int(line.get("params", {}).get("seq", 0)) > after_seq
        ]

    @property
    def thread_ids(self) -> list[str]:
        return list(self._thread_buffer.keys())


def _state_from_str(state: str):
    from electromind.harness.state import InputDeliveryState

    try:
        return InputDeliveryState(state)
    except ValueError:
        return InputDeliveryState.ACCEPTED
