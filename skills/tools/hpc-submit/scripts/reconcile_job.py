#!/usr/bin/env python3
"""reconcile_job.py — P3.5: 按提交记录查询远端作业状态（不猜测、不重提）。

用法:
    reconcile_job.py --submission SUB_ID --rsess-session SESSION

行为:
- 经 rsess 查 squeue/sacct（P3.6）。
- 查询失败 → 输出 UNKNOWN，退出码 3；绝不猜测成功/失败，绝不重提。
- 查询到明确状态 → 写回记录 state，打印状态，退出码 0。
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys

from electromind.hpc import RECONCILED_UNKNOWN, SubmissionStore, reconcile_submission


def rsess_run(session: str) -> callable:
    """绑定到 rsess session 的 run(cmd) -> (exit_code, stdout)。"""

    def run(cmd: str) -> tuple[int, str]:
        proc = subprocess.run(
            ["rsess", "run", session, *shlex.split(cmd)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return proc.returncode, proc.stdout

    return run


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="按提交记录查询远端作业状态")
    p.add_argument("--submission", required=True)
    p.add_argument("--rsess-session", required=True)
    args = p.parse_args(argv)

    store = SubmissionStore()
    record = store.find(args.submission)
    if record is None:
        print(f"submission 不存在: {args.submission}", file=sys.stderr)
        return 1

    run = rsess_run(args.rsess_session)
    try:
        state, _changed = reconcile_submission(record, run=run, store=store)
    except Exception as exc:  # noqa: BLE001 — rsess/ssh 层异常 → UNKNOWN
        print(RECONCILED_UNKNOWN, file=sys.stdout)
        print(f"查询失败（未猜测）: {exc}", file=sys.stderr)
        return 3

    print(state)
    if state == RECONCILED_UNKNOWN:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
