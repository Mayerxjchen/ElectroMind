import json

import pytest

from pagent import Session


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


def test_session_save_to_file(tmp_path):
    s = Session("Hi")
    s += {"role": "user", "content": "there"}
    path = tmp_path / "m.json"
    s.save_to_file(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data[0] == {"role": "system", "content": "Hi"}
    assert data[1] == {"role": "user", "content": "there"}
