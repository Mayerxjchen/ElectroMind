"""JSON-RPC 2.0 wire encoding for :class:`~pagent.events.Event`.

Each agent event becomes a **notification** (no ``id`` field):

.. code-block:: json

   {"jsonrpc": "2.0", "method": "TextDelta", "params": {"text": "hi"}}

One JSON object per line (NDJSON) is typical for HTTP/SSE or WebSocket bridges.
See ``docs/wire.md``.
"""

import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import fields
from typing import Any

from .events import (
    Event,
    ReasoningDelta,
    RunBegin,
    StepEnd,
    TextDelta,
    ToolCallBegin,
    ToolResult,
    TurnBegin,
    TurnEnd,
)
from .llm import RunEnd

JSONRPC_VERSION = "2.0"

_EVENT_TYPES: dict[str, type] = {
    "RunBegin": RunBegin,
    "TurnBegin": TurnBegin,
    "TurnEnd": TurnEnd,
    "TextDelta": TextDelta,
    "ReasoningDelta": ReasoningDelta,
    "StepEnd": StepEnd,
    "ToolCallBegin": ToolCallBegin,
    "ToolResult": ToolResult,
    "RunEnd": RunEnd,
}


def usage_to_dict(usage: object | None) -> dict[str, int] | None:
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage
    model_dump = getattr(usage, "model_dump", None)
    if callable(model_dump):
        return model_dump()
    as_dict = getattr(usage, "dict", None)
    if callable(as_dict):
        return as_dict()
    out: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = getattr(usage, key, None)
        if value is not None:
            out[key] = value
    return out or None


def event_to_params(event: Event) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for field in fields(event):
        value = getattr(event, field.name)
        if field.name == "usage":
            params[field.name] = usage_to_dict(value)
        else:
            params[field.name] = value
    return params


def event_to_rpc(event: Event) -> dict[str, Any]:
    """Encode one event as a JSON-RPC 2.0 notification dict."""
    return {
        "jsonrpc": JSONRPC_VERSION,
        "method": type(event).__name__,
        "params": event_to_params(event),
    }


def rpc_to_event(msg: dict[str, Any]) -> Event:
    """Decode a JSON-RPC 2.0 notification into an :class:`~pagent.events.Event`."""
    if msg.get("jsonrpc") != JSONRPC_VERSION:
        raise ValueError(f"unsupported jsonrpc: {msg.get('jsonrpc')!r}")
    if "id" in msg:
        raise ValueError(
            "agent wire messages are notifications, not requests/responses"
        )
    method = msg.get("method")
    if not method or not isinstance(method, str):
        raise ValueError("missing or invalid method")
    cls = _EVENT_TYPES.get(method)
    if cls is None:
        raise ValueError(f"unknown event method: {method!r}")
    params = msg.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    allowed = {f.name for f in fields(cls)}
    filtered = {k: v for k, v in params.items() if k in allowed}
    return cls(**filtered)


def encode_event(event: Event) -> str:
    """Serialize one event to a JSON string (no trailing newline)."""
    return json.dumps(event_to_rpc(event), ensure_ascii=False)


def decode_event(data: str | bytes) -> Event:
    """Parse a JSON-RPC notification string into an event."""
    return rpc_to_event(json.loads(data))


def encode_event_line(event: Event) -> str:
    """NDJSON: one JSON-RPC notification per line."""
    return encode_event(event) + "\n"


def decode_event_line(line: str) -> Event:
    return decode_event(line.rstrip("\n\r"))


def iter_event_lines(events: Iterator[Event]) -> Iterator[str]:
    for event in events:
        yield encode_event_line(event)


async def aiter_event_lines(events: AsyncIterator[Event]) -> AsyncIterator[str]:
    async for event in events:
        yield encode_event_line(event)
