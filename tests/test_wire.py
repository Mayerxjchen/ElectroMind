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
        ToolResult("id1", "echo", "ok"),
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
