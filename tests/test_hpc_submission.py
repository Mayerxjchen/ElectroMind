"""P3: HPC 提交记录库 + reconcile 测试。

验收语义：
- 同 thread+run 已有 job_id → 禁止再次 sbatch（绝不重复提交）。
- sbatch 超时 / SSH 断线 → 不自动重试，按记录 reconcile。
- 查询失败 → UNKNOWN，不猜测成功/失败。
- 记录原子写 + .bak 恢复 + 损坏恢复。
"""

from __future__ import annotations

import pytest

from electromind.hpc import (
    RECONCILED_UNKNOWN,
    HpcSubmissionError,
    SubmissionRecord,
    SubmissionStore,
    query_job_status,
    reconcile_submission,
)


def _attempt(store: SubmissionStore, **kw):
    base = dict(thread_id="t1", run_id="r1", script_sha256="a" * 64)
    base.update(kw)
    return store.record_attempt(**base)


# ── 记录库基本读写 ──────────────────────────────────────────────────────


def test_record_and_find(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "electromind.hpc.submission.default_submissions_path",
        lambda: tmp_path / "subs.jsonl",
    )
    store = SubmissionStore()
    rec = _attempt(store, run_id="rX")
    assert rec.submission_id.startswith("sub-")
    assert store.find(rec.submission_id) is rec
    assert store.find_by_thread("t1") == [rec]
    assert store.find_by_job_id("123") is None


def test_record_persists_across_instances(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "electromind.hpc.submission.default_submissions_path",
        lambda: tmp_path / "subs.jsonl",
    )
    store = SubmissionStore()
    rec = _attempt(store, run_id="rX", job_id=None)
    store.bind_job_id(rec.submission_id, "sb-42")
    store.update_state(rec.submission_id, "running")

    store2 = SubmissionStore()
    loaded = store2.find(rec.submission_id)
    assert loaded is not None
    assert loaded.job_id == "sb-42"
    assert loaded.state == "running"


# ── P3.3: 禁止重复提交 ─────────────────────────────────────────────────


def test_double_submit_same_thread_run_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "electromind.hpc.submission.default_submissions_path",
        lambda: tmp_path / "subs.jsonl",
    )
    store = SubmissionStore()
    rec = _attempt(store, run_id="r1")
    store.bind_job_id(rec.submission_id, "sb-1")
    with pytest.raises(HpcSubmissionError, match="禁止重复 sbatch"):
        _attempt(store, run_id="r1")


def test_bind_job_id_idempotent_and_conflict(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "electromind.hpc.submission.default_submissions_path",
        lambda: tmp_path / "subs.jsonl",
    )
    store = SubmissionStore()
    rec = _attempt(store)
    store.bind_job_id(rec.submission_id, "sb-1")
    store.bind_job_id(rec.submission_id, "sb-1")  # 幂等
    with pytest.raises(HpcSubmissionError, match="不能改为"):
        store.bind_job_id(rec.submission_id, "sb-2")


def test_has_job_for(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "electromind.hpc.submission.default_submissions_path",
        lambda: tmp_path / "subs.jsonl",
    )
    store = SubmissionStore()
    rec = _attempt(store, run_id="r1")
    assert not store.has_job_for("t1", "r1")  # 还没 job_id
    store.bind_job_id(rec.submission_id, "sb-9")
    assert store.has_job_for("t1", "r1")


# ── 损坏恢复（P1.3 复用） ───────────────────────────────────────────────


def test_corrupt_record_recovers_from_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "electromind.hpc.submission.default_submissions_path",
        lambda: tmp_path / "subs.jsonl",
    )
    store = SubmissionStore()
    rec = _attempt(store, run_id="rX")
    store.bind_job_id(rec.submission_id, "sb-1")
    store.update_state(rec.submission_id, "running")
    store.update_state(rec.submission_id, "running")  # 再写一次 → .bak 含 running
    # 主文件损坏 → .bak 恢复
    p = tmp_path / "subs.jsonl"
    p.write_text('{"submission_id": "trunc', encoding="utf-8")
    store2 = SubmissionStore()
    assert store2.find(rec.submission_id).job_id == "sb-1"
    assert store2.find(rec.submission_id).state == "running"
    assert (tmp_path / "subs.jsonl.corrupt").exists()


# ── reconcile：查询 / 不猜测 ────────────────────────────────────────────


def _run_sacct(state: str):
    def run(cmd: str):
        if "sacct" in cmd:
            return 0, f"123|job|{state}"
        return 1, ""

    return run


def test_query_job_status_sacct_completed():
    q = query_job_status("123", run=_run_sacct("COMPLETED"))
    assert q.ok and q.state == "completed"


def test_query_job_status_sacct_failed():
    q = query_job_status("123", run=_run_sacct("FAILED"))
    assert q.ok and q.state == "failed"


def test_query_job_status_squeue_pending():
    def run(cmd):
        if "sacct" in cmd:
            return 0, ""  # sacct 静默
        return 0, "PENDING"

    q = query_job_status("123", run=run)
    assert q.ok and q.state == "queued"


def test_query_failure_returns_unknown():
    def run(cmd):
        raise ConnectionError("ssh drop")

    q = query_job_status("123", run=run)
    assert not q.ok
    assert q.error  # 有错误信息，状态未知


def test_reconcile_unknown_does_not_guess(tmp_path, monkeypatch):
    """查询失败 → UNKNOWN；记录 state 不被改成成功/失败。"""
    monkeypatch.setattr(
        "electromind.hpc.submission.default_submissions_path",
        lambda: tmp_path / "subs.jsonl",
    )
    store = SubmissionStore()
    rec = _attempt(store, run_id="r1")
    store.bind_job_id(rec.submission_id, "sb-1")

    def run(cmd):
        raise ConnectionError("ssh drop")

    state, changed = reconcile_submission(rec, run=run, store=store)
    assert state == RECONCILED_UNKNOWN
    assert changed is False
    assert store.find(rec.submission_id).state == ""  # 未改


def test_reconcile_updates_terminal_state(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "electromind.hpc.submission.default_submissions_path",
        lambda: tmp_path / "subs.jsonl",
    )
    store = SubmissionStore()
    rec = _attempt(store, run_id="r1")
    store.bind_job_id(rec.submission_id, "sb-1")
    state, changed = reconcile_submission(rec, run=_run_sacct("COMPLETED"), store=store)
    assert state == "completed" and changed is True
    assert store.find(rec.submission_id).state == "completed"


def test_reconcile_no_job_id_returns_unknown():
    rec = SubmissionRecord(submission_id="sub-x", thread_id="t", run_id="r")
    state, changed = reconcile_submission(rec, run=lambda cmd: (0, ""))
    assert state == RECONCILED_UNKNOWN and changed is False
