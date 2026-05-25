import json

import pytest

from pagent import Session, SlidingWindowSession
from pagent.tokens import count_tokens, tools_tokens


def test_session_starts_with_system():
    s = Session("SYS")
    assert s.messages == [{"role": "system", "content": "SYS"}]


def test_session_empty_system():
    s = Session("")
    assert s.messages == []


def test_session_iadd_dict_copies():
    s = Session("")
    d = {"role": "user", "content": "hi"}
    s += d
    d["content"] = "mutated"
    assert s.messages[-1]["content"] == "hi"


def test_session_iadd_list():
    s = Session("")
    s += [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
    assert len(s.messages) == 2


def test_session_iadd_rejects_str():
    s = Session("")
    with pytest.raises(TypeError):
        s += "oops"


def test_session_reset():
    s = Session("SYS")
    s += {"role": "user", "content": "x"}
    s.reset()
    assert s.messages == [{"role": "system", "content": "SYS"}]


def test_sliding_window_trims_by_tokens():
    s = SlidingWindowSession("SYS", max_tokens=80)
    s += {"role": "user", "content": "alpha " * 40}
    s += {"role": "assistant", "content": "beta " * 40}
    s += {"role": "user", "content": "gamma " * 40}
    s += {"role": "assistant", "content": "delta " * 40}
    assert count_tokens(s.messages) <= 80
    assert s.messages[0] == {"role": "system", "content": "SYS"}
    assert s.messages[-1]["content"] == "delta " * 40


def test_sliding_window_drops_assistant_with_tool_messages_together():
    s = SlidingWindowSession("", max_tokens=6)
    s += {"role": "user", "content": "old"}
    s += {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "x", "arguments": "{}"},
            }
        ],
    }
    s += {"role": "tool", "tool_call_id": "c1", "content": "ok"}
    s += {"role": "user", "content": "new"}
    s += {"role": "assistant", "content": "done"}
    assert s.messages == [
        {"role": "user", "content": "new"},
        {"role": "assistant", "content": "done"},
    ]


def test_sliding_window_max_tokens_must_be_positive():
    with pytest.raises(ValueError, match="max_tokens"):
        SlidingWindowSession(max_tokens=0)


def test_sliding_window_tools_reduce_conversation_budget():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": "x " * 15,
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    tools_n = tools_tokens(tools)
    max_tokens = 65
    msg = {"role": "user", "content": "payload " * 20}

    s_no = SlidingWindowSession("SYS", max_tokens=max_tokens)
    s_no += msg
    s_no += {"role": "assistant", "content": "reply " * 20}

    s_yes = SlidingWindowSession("SYS", max_tokens=max_tokens, tools=tools)
    s_yes += msg
    s_yes += {"role": "assistant", "content": "reply " * 20}

    assert count_tokens(s_yes.messages) <= max_tokens - tools_n
    assert len(s_yes.messages) < len(s_no.messages)


def test_session_save_to_file(tmp_path):
    s = Session("Hi")
    s += {"role": "user", "content": "there"}
    path = tmp_path / "m.json"
    s.save_to_file(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data[0] == {"role": "system", "content": "Hi"}
    assert data[1] == {"role": "user", "content": "there"}
