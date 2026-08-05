"""HPC 提交记录（P3.2/P3.3）。

每次 sbatch 前必须 consult 记录：
- 同 thread/run 已有 job_id → 禁止再次 sbatch（防重复提交）。
- sbatch 超时 / SSH 断线 → 不自动重试；保留记录，交给 reconcile 查询。

记录字段（goal 指定）：
  submission_id, thread_id, run_id, rsess_session, remote_workdir,
  script_sha256, input_sha256, job_id, state, stdout_path

持久化：JSONL 一行一记录，原子写 + .bak 备份（atomicfile），损坏自动
从 .bak 恢复。这是 HPC 侧唯一的"不丢记录"依赖。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..atomicfile import atomic_write_text, load_jsonl_recover
from ..paths import default_electromind_home

# 记录文件默认位置：<home>/hpc/submissions.jsonl
SUBMISSIONS_REL = Path("hpc") / "submissions.jsonl"


class HpcSubmissionError(RuntimeError):
    """HPC 提交记录非法操作（重复提交 / 记录冲突等）。"""


def default_submissions_path() -> Path:
    return default_electromind_home() / SUBMISSIONS_REL


def new_submission_id() -> str:
    return f"sub-{uuid.uuid4().hex[:12]}"


@dataclass(slots=True)
class SubmissionRecord:
    """一次 HPC 提交的不可变事实记录。"""

    submission_id: str
    thread_id: str
    run_id: str
    rsess_session: str = ""
    remote_workdir: str = ""
    script_sha256: str = ""
    input_sha256: str = ""
    job_id: str = ""
    state: str = ""  # queued | running | completed | failed | unknown | ...
    stdout_path: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SubmissionRecord":
        return cls(
            submission_id=str(d["submission_id"]),
            thread_id=str(d.get("thread_id", "")),
            run_id=str(d.get("run_id", "")),
            rsess_session=str(d.get("rsess_session", "")),
            remote_workdir=str(d.get("remote_workdir", "")),
            script_sha256=str(d.get("script_sha256", "")),
            input_sha256=str(d.get("input_sha256", "")),
            job_id=str(d.get("job_id", "")),
            state=str(d.get("state", "")),
            stdout_path=str(d.get("stdout_path", "")),
            created_at=float(d.get("created_at", time.time())),
            updated_at=float(d.get("updated_at", time.time())),
        )


class SubmissionStore:
    """提交记录库：原子写 + .bak 恢复 + 重复提交挡板。

    - :meth:`find_by_job_id` / :meth:`find_by_thread` 用于提交前检查。
    - :meth:`record_attempt`：写入一条"尝试提交"记录（无 job_id）。
    - :meth:`bind_job_id`：sbatch 成功后补 job_id。
    - :meth:`update_state`：reconcile 后更新 state。
    - 同一 (thread_id, run_id) 已有 job_id 时再次提交 → 抛
      ``HpcSubmissionError``。
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_submissions_path()
        self._records: dict[str, SubmissionRecord] = {}
        if self.path.exists():
            self._load()

    # ── 查询 ────────────────────────────────────────────────────────

    def all(self) -> list[SubmissionRecord]:
        return list(self._records.values())

    def find(self, submission_id: str) -> SubmissionRecord | None:
        return self._records.get(submission_id)

    def find_by_job_id(self, job_id: str) -> SubmissionRecord | None:
        for r in self._records.values():
            if r.job_id and r.job_id == job_id:
                return r
        return None

    def find_by_thread(self, thread_id: str) -> list[SubmissionRecord]:
        return [r for r in self._records.values() if r.thread_id == thread_id]

    def has_job_for(self, thread_id: str, run_id: str) -> bool:
        """该 thread+run 是否已有已提交的 job（禁止重复 sbatch）。"""
        return any(
            r.thread_id == thread_id and r.run_id == run_id and bool(r.job_id)
            for r in self._records.values()
        )

    # ── 写入 ────────────────────────────────────────────────────────

    def record_attempt(self, **kw) -> SubmissionRecord:
        """登记一次提交尝试。若 thread+run 已有 job_id → 拒绝（防重复 sbatch）。

        返回新记录（job_id 为空，等待 sbatch 成功后 bind）。
        """
        thread_id = str(kw.get("thread_id", ""))
        run_id = str(kw.get("run_id", ""))
        if self.has_job_for(thread_id, run_id):
            raise HpcSubmissionError(
                f"thread {thread_id} run {run_id} 已有提交的作业，禁止重复 sbatch"
            )
        record = SubmissionRecord(
            submission_id=kw.get("submission_id") or new_submission_id(),
            thread_id=thread_id,
            run_id=run_id,
            rsess_session=str(kw.get("rsess_session", "")),
            remote_workdir=str(kw.get("remote_workdir", "")),
            script_sha256=str(kw.get("script_sha256", "")),
            input_sha256=str(kw.get("input_sha256", "")),
            stdout_path=str(kw.get("stdout_path", "")),
        )
        self._records[record.submission_id] = record
        self._flush()
        return record

    def bind_job_id(self, submission_id: str, job_id: str) -> SubmissionRecord:
        """sbatch 成功后补记 job_id（幂等：重复 bind 同 job_id 允许）。"""
        record = self._require(submission_id)
        if record.job_id and record.job_id != job_id:
            raise HpcSubmissionError(
                f"submission {submission_id} 已绑定 job {record.job_id}，"
                f"不能改为 {job_id}"
            )
        record.job_id = job_id
        record.updated_at = time.time()
        self._flush()
        return record

    def update_state(self, submission_id: str, state: str) -> SubmissionRecord:
        record = self._require(submission_id)
        record.state = state
        record.updated_at = time.time()
        self._flush()
        return record

    # ── 内部 ────────────────────────────────────────────────────────

    def _require(self, submission_id: str) -> SubmissionRecord:
        record = self._records.get(submission_id)
        if record is None:
            raise HpcSubmissionError(f"submission 不存在: {submission_id}")
        return record

    def _flush(self) -> None:
        # P1.2/P1.3 同款原子写 + .bak。
        atomic_write_text(
            self.path,
            "".join(
                json.dumps(r.to_dict(), ensure_ascii=False) + "\n"
                for r in self._records.values()
            ),
            encoding="utf-8",
            backup=True,
        )

    def _load(self) -> None:
        # P1.3 同款损坏恢复：整份损坏 → 尝试 .bak；单条损坏 fail-soft 跳过。
        for d in load_jsonl_recover(self.path, parse_line=json.loads):
            try:
                record = SubmissionRecord.from_dict(d)
            except (ValueError, KeyError, TypeError):
                continue
            self._records[record.submission_id] = record
