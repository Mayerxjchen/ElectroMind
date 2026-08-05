"""HPC 作业状态 reconcile（P3.4/P3.6）。

铁律：
- sbatch 超时 / SSH 断线 → **不自动重试**。查询已有记录，按记录 reconcile。
- 查询 squeue/sacct 失败（ssh 不可达 / 命令超时 / 输出不可解析）→ 状态
  记为 ``UNKNOWN``。**绝不猜测**为失败、成功或重复提交。
- 只有查询明确返回终端状态（COMPLETED / FAILED / CANCELLED / TIMEOUT）
  才更新记录；否则保持当前 state 并加 ``unknown`` 标记。

查询经 ``rsess run`` 完成（P3 主路径固定为 rsess；不使用内置 SshBackend
管理同一远程任务）。本模块不直接执行 ssh —— 由调用方注入 ``runner``
（一个 ``run(cmd) -> (exit_code, stdout)`` 可调用对象），便于测试与
换实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .submission import SubmissionRecord, SubmissionStore

# 不可判定的状态值（查询失败 / 无作业）
RECONCILED_UNKNOWN = "unknown"

# 明确的终端状态（squeue 一般只显示未结束作业，sacct 才给终端态）
TERMINAL_STATES = frozenset(
    {"completed", "failed", "cancelled", "timeout", "oom", "node_fail"}
)

# sacct 常见 State 值 → 归一化
_STATE_MAP = {
    "COMPLETED": "completed",
    "COMPLETING": "running",  # 结算中，仍算运行
    "RUNNING": "running",
    "PENDING": "queued",
    "CONFIGURING": "queued",
    "FAILED": "failed",
    "CANCELLED": "cancelled",
    "CANCELLED+": "cancelled",
    "TIMEOUT": "timeout",
    "OUT_OF_MEMORY": "oom",
    "OOM": "oom",
    "NODE_FAIL": "node_fail",
    "BOOT_FAIL": "failed",
    "DEADLINE": "timeout",
}

# 查询命令。用 sacct 查历史（含终端态），squeue 兜底查活跃。
_SACCT_CMD = "sacct -n -P -o JobID,JobName,State -j {job_id} 2>/dev/null"
_SQUEUE_CMD = "squeue -h -o %T -j {job_id} 2>/dev/null"


class JobQueryError(RuntimeError):
    """查询远端作业状态失败（ssh 不可达 / 超时 / 输出异常）。"""


@dataclass(slots=True)
class JobQuery:
    """一次查询的结果。``ok=False`` 表示查询本身失败 → 调用方记 UNKNOWN。"""

    ok: bool
    state: str = ""
    raw: str = ""
    error: str = ""


def normalize_sacct_state(raw: str) -> str | None:
    """把 sacct 输出归一化成我们的 state；无法识别返回 None。

    sacct ``-n -P`` 用 ``|`` 分隔字段，State 是最后一个字段（可能带
    计数后缀如 ``COMPLETED+``）。取最后一个 ``|``/空白分隔的 token。
    """
    tokens = [t for t in raw.strip().replace("|", " ").split() if t]
    if not tokens:
        return None
    state = tokens[-1].upper()
    if state in _STATE_MAP:
        return _STATE_MAP[state]
    # sacct State 可能带后缀如 COMPLETED+；取主字段
    for key in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "RUNNING", "PENDING"):
        if state.startswith(key):
            return _STATE_MAP[key]
    return None


def query_job_status(
    job_id: str,
    *,
    run: Callable[[str], tuple[int, str]],
) -> JobQuery:
    """经 rsess 查询一个 job 的当前状态。

    ``run``：``(cmd) -> (exit_code, stdout)``，由调用方绑定到 rsess
    session。本函数负责构造查询命令并解析输出；查询失败不抛错，
    而是返回 ``ok=False``。
    """
    if not job_id:
        return JobQuery(ok=False, error="no job_id")

    # 先查 sacct（能给出终端态）
    try:
        rc, out = run(_SACCT_CMD.format(job_id=job_id))
    except Exception as exc:  # noqa: BLE001 — ssh 层抛什么都不能让它把状态当成功
        return JobQuery(ok=False, error=f"sacct query raised: {exc}")
    if rc == 0 and out.strip():
        state = normalize_sacct_state(out)
        if state is not None:
            return JobQuery(ok=True, state=state, raw=out)

    # sacct 没给出（作业还在排队/运行，或集群不写 sacct）→ 兜底 squeue
    try:
        rc2, out2 = run(_SQUEUE_CMD.format(job_id=job_id))
    except Exception as exc:  # noqa: BLE001
        return JobQuery(ok=False, error=f"squeue query raised: {exc}")
    if rc2 == 0:
        state = out2.strip().upper()
        if state in _STATE_MAP:
            return JobQuery(ok=True, state=_STATE_MAP[state], raw=out2)
        # squeue 无输出 → 作业已不在队列，但不确定是成功还是失败
        if not out2.strip():
            return JobQuery(ok=False, error="job not in squeue and sacct silent")
        return JobQuery(ok=False, error=f"unparseable squeue state: {out2!r}")

    return JobQuery(ok=False, error=f"squeue exit {rc2}")


def reconcile_submission(
    record: SubmissionRecord,
    *,
    run: Callable[[str], tuple[int, str]],
    store: SubmissionStore | None = None,
) -> tuple[str, bool]:
    """按提交记录查询作业状态。

    - 查询成功（明确状态）→ 更新记录 state，返回 ``(state, changed=True)``。
    - 查询失败 / 无法判定 → 返回 ``(RECONCILED_UNKNOWN, False)``，不改记录
      （绝不猜测为失败或成功，也绝不触发重提）。
    - 若传入 ``store``，会把明确状态写回。
    """
    if not record.job_id:
        return RECONCILED_UNKNOWN, False

    query = query_job_status(record.job_id, run=run)
    if not query.ok:
        return RECONCILED_UNKNOWN, False

    changed = query.state != record.state
    if changed and store is not None:
        store.update_state(record.submission_id, query.state)
    return query.state, changed
