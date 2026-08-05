"""HPC 最小稳定闭环（P3）。

只做一件事：把"提交 → 查询 → 恢复"的每个动作落成一个**不可丢失的
JSON 记录**，并用它挡住重复 sbatch、断线后的盲重试、以及把
"查询失败"当成"作业失败"的猜测。

路径固定：Desktop → 本地 Agent → rsess Skill → 远端 tmux shell →
hpc-submit Skill → Slurm/PBS。Desktop 不直接调用 Scheduler API。

模块
- ``submission``：SubmissionStore（原子写 + .bak 恢复 + 禁止重复提交）
- ``reconcile``：按记录查 squeue/sacct，查询失败 → UNKNOWN
- 三个入口脚本在 ``skills/tools/hpc-submit/scripts/``：
  prepare_submission.py / reconcile_job.py / collect_outputs.py
"""

from __future__ import annotations

from .reconcile import (
    RECONCILED_UNKNOWN,
    query_job_status,
    reconcile_submission,
)
from .submission import (
    HpcSubmissionError,
    SubmissionRecord,
    SubmissionStore,
    new_submission_id,
)

__all__ = [
    "HpcSubmissionError",
    "SubmissionRecord",
    "SubmissionStore",
    "new_submission_id",
    "reconcile_submission",
    "query_job_status",
    "RECONCILED_UNKNOWN",
]
