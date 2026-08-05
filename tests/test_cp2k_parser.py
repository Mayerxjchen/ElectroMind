"""P2.2/P2.3: CP2K 确定性 Parser + 真实 fixture 文件。

验收语义：
- Scheduler COMPLETED（退出码 0）≠ 科学成功。Parser 判定是唯一依据：
  只有 terminated_cleanly + 能量齐全 + 非截断 才能 VALIDATED。
"""

from __future__ import annotations

from pathlib import Path

from electromind.parsers import ParseOutcome, parse_file

FIXTURES = Path(__file__).parent / "fixtures" / "cp2k"


def test_success_out_is_valid():
    r = parse_file(FIXTURES / "success.out", parser="cp2k")
    assert r.outcome is ParseOutcome.VALID
    assert r.valid
    assert r.terminated_cleanly
    assert not r.truncated
    assert r.scf_converged is True
    assert r.scf_iterations == 4
    assert r.energy is not None and abs(r.energy - (-17.1234567893)) < 1e-9
    assert r.energy_unit == "Hartree"
    assert len(r.forces) == 3
    assert abs(r.forces[0]["magnitude"] - 0.12) < 1e-6
    assert r.force_unit  # a.u.


def test_not_converged_is_not_valid():
    r = parse_file(FIXTURES / "not_converged.out", parser="cp2k")
    assert r.outcome is ParseOutcome.NOT_CONVERGED
    assert not r.valid  # 程序正常结束，但科学上不可信
    assert r.terminated_cleanly
    assert r.scf_converged is False
    assert r.energy is not None


def test_timeout_is_failed():
    r = parse_file(FIXTURES / "timeout.out", parser="cp2k")
    assert r.outcome is ParseOutcome.FAILED
    assert not r.valid
    assert not r.terminated_cleanly
    assert (
        "timed out" in r.summary.lower()
        or "timeout" in r.summary.lower()
        or "deadline" in r.summary.lower()
    )


def test_oom_is_failed():
    r = parse_file(FIXTURES / "oom.out", parser="cp2k")
    assert r.outcome is ParseOutcome.FAILED
    assert not r.valid
    assert not r.terminated_cleanly
    assert "内存不足" in r.summary or "OOM" in r.summary


def test_truncated_out_is_truncated():
    r = parse_file(FIXTURES / "truncated.out", parser="cp2k")
    assert r.outcome is ParseOutcome.TRUNCATED
    assert not r.valid
    assert not r.terminated_cleanly
    assert r.truncated
    # 有能量，但没有"正常结束"标志 → 绝不视为成功
    assert r.energy is not None


def test_unknown_parser_returns_unknown():
    r = parse_file(FIXTURES / "success.out", parser="vasp")
    assert r.outcome is ParseOutcome.UNKNOWN
    assert not r.valid


def test_missing_file_returns_unknown(tmp_path):
    r = parse_file(tmp_path / "nope.out", parser="cp2k")
    assert r.outcome is ParseOutcome.UNKNOWN
    assert not r.valid


def test_empty_output_returns_unknown(tmp_path):
    f = tmp_path / "empty.out"
    f.write_text("   \n\n", encoding="utf-8")
    r = parse_file(f, parser="cp2k")
    assert r.outcome is ParseOutcome.UNKNOWN
    assert not r.valid


def test_md_steps_counted():
    r = parse_file(FIXTURES / "success.out", parser="cp2k")
    assert r.md_steps == 0  # 该 fixture 是单点能量，无 MD 步


def test_parse_result_serializable():
    r = parse_file(FIXTURES / "success.out", parser="cp2k")
    d = r.to_dict()
    assert d["outcome"] == "valid"
    assert d["valid"] is True
    assert "energy" in d and "forces" in d and "energy_unit" in d
