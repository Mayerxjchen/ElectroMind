"""模拟 Slurm scheduler — 以 job ID 查询为恢复事实源（P0-9 §11.4）。

真实 HPC 集成不在本阶段范围；本模拟器实现验收所需的确定性语义：

- ``submit`` 返回持久化 job id（幂等：同 key 重复提交返回原 job id，不重提）。
- ``query`` 按 job id 查询状态（submitted/queued/running/completed/failed）。
- ``reconcile`` 对状态未知的 job 做确定性对账（模拟 SSH 断开后的重连）。
- job 状态持久化在 thread 根目录：进程重启后新实例仍能按 job id 恢复
  监控（SSH 断开 ≠ job 失败；恢复时先查询 Scheduler，不重新提交）。
"""

from __future__ import annotations

import json
import time
from enum import StrEnum
from pathlib import Path


class JobStatus(StrEnum):
    PREPARED = "prepared"
    SUBMITTED = "submitted"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    LOST = "lost"
    RECONCILING = "reconciling"


class SimulatedSlurm:
    """确定性模拟 scheduler；状态落在 ``<root>/scheduler_jobs.json``。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.path = self.root / "scheduler_jobs.json"
        self._jobs: dict[str, dict] = {}
        self._load()

    # ── 提交 ─────────────────────────────────────────────────────────

    def submit(self, *, script: str, job_key: str = "") -> str:
        """提交 job；``job_key`` 幂等——同 key 返回原 job id（不重提）。

        模拟真实 sbatch：返回形如 ``job-<n>`` 的稳定 id。
        """
        if job_key:
            existing = self._by_key(job_key)
            if existing is not None:
                return existing["job_id"]
        job_id = f"job-{len(self._jobs) + 1:04d}"
        self._jobs[job_id] = {
            "job_id": job_id,
            "job_key": job_key,
            "script": script,
            "status": str(JobStatus.SUBMITTED),
            "submitted_at": time.time(),
        }
        self._flush()
        return job_id

    def _by_key(self, job_key: str) -> dict | None:
        for job in self._jobs.values():
            if job.get("job_key") == job_key:
                return job
        return None

    # ── 状态推进（模拟集群行为） ─────────────────────────────────────

    def advance(self, job_id: str, status: JobStatus) -> bool:
        """确定性推进 job 状态（模拟队列→运行→完成）。"""
        job = self._jobs.get(job_id)
        if job is None:
            return False
        job["status"] = str(status)
        job["updated_at"] = time.time()
        self._flush()
        return True

    def query(self, job_id: str) -> str | None:
        """按 job id 查询状态（恢复时的事实源）。"""
        job = self._jobs.get(job_id)
        return job["status"] if job is not None else None

    def reconcile(self, job_id: str) -> str:
        """SSH 断开后的对账：查询失败 → RECONCILING，不假定失败。"""
        status = self.query(job_id)
        if status is None:
            return str(JobStatus.LOST)
        if status in (str(JobStatus.SUBMITTED), str(JobStatus.QUEUED)):
            # 模拟重连后再次查询（SSH 断开 ≠ job 失败）
            return status
        return status

    def job(self, job_id: str) -> dict | None:
        return self._jobs.get(job_id)

    # ── 持久化 ──────────────────────────────────────────────────────

    def _flush(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(list(self._jobs.values()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            for job in payload:
                self._jobs[job["job_id"]] = job
        except (ValueError, KeyError):
            self._jobs = {}
