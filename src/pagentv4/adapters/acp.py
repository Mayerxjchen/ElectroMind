import json
from dataclasses import fields

from ..core.events import (
    Event,
    ReasoningDelta,
    RunBegin,
    TextDelta,
    ToolCallBegin,
    ToolResult,
    TurnBegin,
    TurnEnd,
)
from ..core.turn_result import TurnResult

JSONRPC_VERSION = "2.0"

EVENT_TYPES: dict[str, type] = {
    "RunBegin": RunBegin,
    "TurnBegin": TurnBegin,
    "TurnEnd": TurnEnd,
    "TextDelta": TextDelta,
    "ReasoningDelta": ReasoningDelta,
    "TurnResult": TurnResult,
    "ToolCallBegin": ToolCallBegin,
    "ToolResult": ToolResult,
}


def encode_event_line(event: Event) -> str:
    params = {f.name: getattr(event, f.name) for f in fields(event)}
    return (
        json.dumps(
            {
                "jsonrpc": JSONRPC_VERSION,
                "method": type(event).__name__,
                "params": params,
            },
            ensure_ascii=False,
        )
        + "\n"
    )


def decode_event_line(line: str) -> Event:
    msg = json.loads(line.rstrip("\n\r"))
    if msg.get("jsonrpc") != JSONRPC_VERSION:
        raise ValueError(f"unsupported jsonrpc: {msg.get('jsonrpc')!r}")
    if "id" in msg:
        raise ValueError(
            "event lines are JSON-RPC notifications, not requests/responses"
        )
    method = msg.get("method")
    if not method or not isinstance(method, str):
        raise ValueError("missing or invalid method")
    cls = EVENT_TYPES.get(method)
    if cls is None:
        raise ValueError(f"unknown event method: {method!r}")
    params = msg.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    allowed = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in params.items() if k in allowed})
