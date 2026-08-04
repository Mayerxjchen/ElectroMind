"""stream-json 输出：每行一个 Protocol v2 事件（NDJSON JSON-RPC 2.0 notification）。

Envelope 契约与 wire ``_emit_jsonrpc`` 一致：EventBroker 打 per-thread seq /
event_id / protocol_version / timestamp，写入 ``params``。
"""

from __future__ import annotations

import json
import sys

from electromind.harness.protocol_v2 import EventBroker, EventEnvelope


class StreamJsonWriter:
    def __init__(self, *, stream=None) -> None:
        self._stream = stream or sys.stdout
        self._broker = EventBroker()

    def write_line(self, line: dict) -> None:
        """直接写出客户端事件行（envelope 已由客户端打 seq/event_id）。"""
        self._stream.write(json.dumps(line, ensure_ascii=False) + "\n")
        self._stream.flush()

    # -- 底层 emit：对齐 wire._emit_jsonrpc -----------------------------

    def emit(
        self,
        thread_id: str,
        method: str,
        params: dict,
        *,
        run_id: str | None = None,
        item_id: str | None = None,
    ) -> None:
        envelope = EventEnvelope.create(
            thread_id,
            method,
            params,
            run_id=run_id,
            item_id=item_id,
        )
        tracked = self._broker.emit(envelope)
        params["seq"] = tracked.seq
        params["event_id"] = tracked.event_id
        params["protocol_version"] = tracked.protocol_version
        params["timestamp"] = tracked.timestamp
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        self._stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._stream.flush()

    # -- Run 生命周期事件 ------------------------------------------------

    def run_started(
        self,
        thread_id: str,
        run_id: str,
        *,
        mode: str = "run",
        model: str = "",
        max_iterations: int = 0,
    ) -> None:
        self.emit(
            thread_id,
            "run/started",
            {
                "thread_id": thread_id,
                "run_id": run_id,
                "session_mode": mode,
                "model": model,
                "max_iterations": max_iterations,
            },
            run_id=run_id,
        )

    def run_completed(
        self,
        thread_id: str,
        run_id: str,
        *,
        stop_reason: str,
        usage: dict | None = None,
    ) -> None:
        self.emit(
            thread_id,
            "run/completed",
            {
                "thread_id": thread_id,
                "run_id": run_id,
                "stop_reason": stop_reason,
                "usage": usage or {},
            },
            run_id=run_id,
        )

    # -- Item 事件 -------------------------------------------------------

    def item_started(
        self,
        thread_id: str,
        run_id: str,
        item_id: str,
        *,
        kind: str,
        name: str = "",
    ) -> None:
        params = {
            "thread_id": thread_id,
            "run_id": run_id,
            "item_id": item_id,
            "kind": kind,
        }
        if name:
            params["name"] = name
        self.emit(thread_id, "item/started", params, run_id=run_id, item_id=item_id)

    def item_delta(
        self,
        thread_id: str,
        run_id: str,
        item_id: str,
        *,
        kind: str,
        text: str,
    ) -> None:
        self.emit(
            thread_id,
            "item/delta",
            {
                "thread_id": thread_id,
                "run_id": run_id,
                "item_id": item_id,
                "kind": kind,
                "text": text,
            },
            run_id=run_id,
            item_id=item_id,
        )

    def item_completed(
        self,
        thread_id: str,
        run_id: str,
        item_id: str,
        *,
        kind: str,
        ok: bool = True,
    ) -> None:
        self.emit(
            thread_id,
            "item/completed",
            {
                "thread_id": thread_id,
                "run_id": run_id,
                "item_id": item_id,
                "kind": kind,
                "ok": ok,
            },
            run_id=run_id,
            item_id=item_id,
        )
