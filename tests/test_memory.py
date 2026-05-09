# memory 暂未从包根导出，见 ``pagent/memory.py`` 模块说明
import json

import pytest

from pagent.memory import Memory


def test_add_len_clear():
    m = Memory()
    m.add("a")
    m.add("b")
    assert len(m) == 2
    assert m.as_text() == "a\nb"
    assert m.as_text("|") == "a|b"
    m.clear()
    assert len(m) == 0


def test_save_load(tmp_path):
    m = Memory()
    m.add("one")
    p = tmp_path / "m.json"
    m.save_to_file(p)
    o = Memory.load_from_file(p)
    assert o.lines == ["one"]
    assert json.loads(p.read_text(encoding="utf-8")) == ["one"]


def test_load_not_list(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON array"):
        Memory.load_from_file(p)
