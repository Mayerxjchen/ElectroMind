"""P1.2/P1.3: 原子写与损坏检测 + .bak 恢复。"""

from __future__ import annotations

import json

from electromind.atomicfile import (
    atomic_write_bytes,
    atomic_write_text,
    load_json_recover,
    load_jsonl_recover,
    load_toml_recover,
)

# ── 原子写 ──────────────────────────────────────────────────────────────


def test_atomic_write_text_creates_file(tmp_path):
    p = tmp_path / "a.txt"
    atomic_write_text(p, "hello")
    assert p.read_text(encoding="utf-8") == "hello"


def test_atomic_write_text_no_leftover_tmp(tmp_path):
    p = tmp_path / "a.txt"
    atomic_write_text(p, "v1")
    atomic_write_text(p, "v2")
    assert p.read_text(encoding="utf-8") == "v2"
    leftovers = [f for f in tmp_path.iterdir() if f.suffix == ".tmp"]
    assert leftovers == []


def test_atomic_write_bytes(tmp_path):
    p = tmp_path / "b.bin"
    atomic_write_bytes(p, b"\x00\x01\x02")
    assert p.read_bytes() == b"\x00\x01\x02"


def test_atomic_write_backup_keeps_previous(tmp_path):
    p = tmp_path / "c.txt"
    atomic_write_text(p, "v1", backup=True)
    atomic_write_text(p, "v2", backup=True)
    assert p.read_text(encoding="utf-8") == "v2"
    bak = tmp_path / "c.txt.bak"
    assert bak.read_text(encoding="utf-8") == "v1"


# ── 损坏检测 + .bak 恢复 ────────────────────────────────────────────────


def test_load_json_recover_from_backup(tmp_path):
    p = tmp_path / "m.json"
    atomic_write_text(p, json.dumps({"a": 1}), backup=True)
    atomic_write_text(p, json.dumps({"a": 2}), backup=True)
    # 主文件损坏 → 自动恢复 .bak
    p.write_text("{ corrupted !!", encoding="utf-8")
    assert load_json_recover(p) == {"a": 1}
    # 损坏主文件被改名留存
    assert (tmp_path / "m.json.corrupt").exists()


def test_load_json_recover_no_backup_returns_default(tmp_path):
    p = tmp_path / "m.json"
    p.write_text("{ bad", encoding="utf-8")
    assert load_json_recover(p, default={}) == {}
    assert (tmp_path / "m.json.corrupt").exists()


def test_load_toml_recover_from_backup(tmp_path):
    p = tmp_path / "t.toml"
    atomic_write_text(p, '[agent]\nname = "a"\n', backup=True)
    atomic_write_text(p, '[agent]\nname = "b"\n', backup=True)
    p.write_text("[[[[ not toml", encoding="utf-8")
    assert load_toml_recover(p)["agent"]["name"] == "a"


def test_load_jsonl_recover_partial_corruption_failsoft(tmp_path):
    p = tmp_path / "lines.jsonl"
    p.write_text('{"i": 1}\n{"i": 2}\nNOT_JSON\n{"i": 3}\n', encoding="utf-8")
    parsed = load_jsonl_recover(p, parse_line=json.loads)
    assert [d["i"] for d in parsed] == [1, 2, 3]
    # 单条损坏不至于整体损坏 → 主文件不改名
    assert not (tmp_path / "lines.jsonl.corrupt").exists()


def test_load_jsonl_recover_whole_corrupt_falls_to_backup(tmp_path):
    p = tmp_path / "lines.jsonl"
    atomic_write_text(p, '{"i": 0}\n', backup=True)
    atomic_write_text(p, '{"i": 1}\n{"i": 2}\n', backup=True)  # 产生 .bak
    # 主文件几乎全坏（截断的半写文件）
    p.write_text('{"i": 1\n{"i', encoding="utf-8")
    parsed = load_jsonl_recover(p, parse_line=json.loads)
    # .bak 保存的是上一次写盘内容（{"i": 0}），整体损坏时回退到它
    assert [d["i"] for d in parsed] == [0]
    assert (tmp_path / "lines.jsonl.corrupt").exists()


def test_load_jsonl_recover_empty_file_returns_default(tmp_path):
    p = tmp_path / "lines.jsonl"
    p.write_text("", encoding="utf-8")
    assert load_jsonl_recover(p, parse_line=json.loads) == []


def test_load_jsonl_recover_strict_ratio(tmp_path):
    p = tmp_path / "strict.jsonl"
    # 3 好 1 坏 → good ratio 0.75；要求 0.9 时整体视为损坏（严格模式）
    p.write_text('{"i": 1}\n{"i": 2}\n{"i": 3}\nBAD\n', encoding="utf-8")
    parsed = load_jsonl_recover(
        p, parse_line=json.loads, min_good_ratio=0.9, default=["sentinel"]
    )
    assert parsed == ["sentinel"]
