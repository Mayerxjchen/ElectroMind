#!/usr/bin/env python3
"""prepare_submission.py — P3.5: 提交前登记记录，挡重复 sbatch。

用法:
    prepare_submission.py --thread THREAD --run RUN \
        --rsess-session SESSION --remote-workdir DIR \
        --script path.sh --input path.inp [--stdout path.out] \
        [--bind-job-id JOBID]

行为:
1. 计算 script / input 的 SHA-256（P3.7：上传前记录，下载后核对）。
2. 写入一条 SubmissionRecord（job_id 为空，state 留空）。
3. 若同 thread+run 已有 job_id → 抛错退出码 2（禁止重复提交）。
4. 传 ``--bind-job-id`` 时把 sbatch 返回的 job_id 补进记录
   （sbatch 成功即用；重复 bind 同 job_id 幂等，不同 job_id 拒绝）。

输出: submission_id（stdout）。后续用 reconcile_job.py 查询。
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from electromind.hpc import HpcSubmissionError, SubmissionStore


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="登记 HPC 提交记录（防重复 sbatch）")
    p.add_argument("--thread", required=True)
    p.add_argument("--run", required=True)
    p.add_argument("--rsess-session", default="")
    p.add_argument("--remote-workdir", default="")
    p.add_argument("--script", required=True)
    p.add_argument("--input", default="")
    p.add_argument("--stdout", default="")
    p.add_argument("--bind-job-id", default="")
    args = p.parse_args(argv)

    try:
        script_sha = sha256_file(args.script)
        input_sha = sha256_file(args.input) if args.input else ""
    except OSError as exc:
        print(f"无法读取输入文件: {exc}", file=sys.stderr)
        return 2

    store = SubmissionStore()
    try:
        record = store.record_attempt(
            thread_id=args.thread,
            run_id=args.run,
            rsess_session=args.rsess_session,
            remote_workdir=args.remote_workdir,
            script_sha256=script_sha,
            input_sha256=input_sha,
            stdout_path=args.stdout,
        )
        if args.bind_job_id:
            record = store.bind_job_id(record.submission_id, args.bind_job_id)
    except HpcSubmissionError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(record.submission_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
