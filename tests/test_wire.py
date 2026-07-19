import json
from dataclasses import fields

import pytest

from pagent import (
    ReasoningDelta,
    RunBegin,
    RunEnd,
    StepEnd,
    TextDelta,
    ToolCallBegin,
    ToolResult,
    TurnBegin,
    TurnEnd,
    decode_event,
    decode_event_line,
    encode_event_line,
    event_to_rpc,
    rpc_to_event,
)
from pagent.wire import usage_to_dict
from pagentv4.adapters import decode_event_line as decode_v4_event_line
from pagentv4.adapters import encode_event_line as encode_v4_event_line
from pagentv4.core.events import RunBegin as V4RunBegin
from pagentv4.core.events import RunEnd as V4RunEnd
from pagentv4.core.events import TurnBegin as V4TurnBegin
from pagentv4.core.events import TurnEnd as V4TurnEnd
from pagentv4.core.message import ToolCall as V4ToolCall
from pagentv4.core.turn_result import TurnResult as V4TurnResult


class FakeUsage:
    prompt_tokens = 10
    completion_tokens = 5
    total_tokens = 15


@pytest.mark.parametrize(
    "event",
    [
        RunBegin("hello"),
        TurnBegin(1),
        TurnEnd(1, stopped=False),
        TextDelta("a"),
        ReasoningDelta("think"),
        StepEnd("c", [{"id": "1"}], "r", FakeUsage()),
        ToolCallBegin("id1", "echo", "{}"),
        ToolResult("id1", "echo", "ok", ok=True),
        ToolResult("id2", "echo", "fail", ok=False),
        RunEnd(content="done", reasoning_content="why", usage=FakeUsage()),
    ],
)
def test_event_rpc_roundtrip(event):
    line = encode_event_line(event)
    assert line.endswith("\n")
    restored = decode_event_line(line)
    if isinstance(event, (StepEnd, RunEnd)):
        for field in fields(event):
            if field.name == "usage":
                assert restored.usage == usage_to_dict(event.usage)
            else:
                assert getattr(restored, field.name) == getattr(event, field.name)
    else:
        assert restored == event


def test_v4_turn_result_wire_roundtrip_with_typed_tool_call():
    event = V4TurnResult(
        tool_calls=[
            V4ToolCall(
                type="function",
                id="c1",
                name="echo",
                arguments='{"msg":"ping"}',
            )
        ]
    )

    restored = decode_v4_event_line(encode_v4_event_line(event))

    assert isinstance(restored.tool_calls[0], V4ToolCall)
    assert restored.tool_calls[0].id == "c1"
    assert restored.tool_calls[0].name == "echo"


def test_v4_turn_result_wire_roundtrip_with_usage():
    event = V4TurnResult(
        content="done",
        usage={
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "prompt_tokens_details": {"cached_tokens": 8},
        },
    )

    restored = decode_v4_event_line(encode_v4_event_line(event))

    assert restored == event


@pytest.mark.parametrize(
    "event",
    [
        V4RunBegin("hello"),
        V4TurnBegin(1),
        V4TurnEnd(1, stopped=True, stop_reason="no_tool_calls"),
        V4RunEnd(1, stop_reason="no_tool_calls"),
    ],
)
def test_v4_event_wire_roundtrip(event):
    restored = decode_v4_event_line(encode_v4_event_line(event))

    assert restored == event


def test_event_to_rpc_shape():
    msg = event_to_rpc(TextDelta("hi"))
    assert msg == {
        "jsonrpc": "2.0",
        "method": "TextDelta",
        "params": {"text": "hi"},
    }


def test_usage_to_dict():
    assert usage_to_dict(None) is None
    d = usage_to_dict(FakeUsage())
    assert d == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }


def test_rpc_rejects_request_with_id():
    with pytest.raises(ValueError, match="notifications"):
        rpc_to_event({"jsonrpc": "2.0", "method": "TextDelta", "params": {}, "id": 1})


def test_rpc_unknown_method():
    with pytest.raises(ValueError, match="unknown"):
        rpc_to_event({"jsonrpc": "2.0", "method": "Nope", "params": {}})


def test_decode_event_from_json_string():
    raw = json.dumps({"jsonrpc": "2.0", "method": "RunEnd", "params": {"content": "x"}})
    e = decode_event(raw)
    assert isinstance(e, RunEnd)
    assert e.content == "x"
