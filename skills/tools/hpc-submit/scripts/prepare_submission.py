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
5. 传 ``--verify-remote`` 时（配合 --rsess-session/--remote-workdir），
   经 ``rsess run sha256sum`` 核对远端文件 SHA 与本地记录一致；不一致
   → 退出码 2，拒绝提交（文件传输必须是 rsync/scp，且落盘须与记录相符）。

输出: submission_id（stdout）。后续用 reconcile_job.py 查询。
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
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
    p.add_argument(
        "--idempotency-key",
        default="",
        help="幂等键（缺省为 thread:run）；重试必须复用同一键，禁止重复 sbatch",
    )
    p.add_argument(
        "--verify-remote",
        action="store_true",
        help="经 rsess 核对远端文件 SHA 与本地一致（需 --rsess-session/--remote-workdir）",
    )
    args = p.parse_args(argv)

    try:
        script_sha = sha256_file(args.script)
        input_sha = sha256_file(args.input) if args.input else ""
    except OSError as exc:
        print(f"无法读取输入文件: {exc}", file=sys.stderr)
        return 2

    if args.verify_remote:
        if not args.rsess_session or not args.remote_workdir:
            print(
                "--verify-remote 需要 --rsess-session 与 --remote-workdir",
                file=sys.stderr,
            )
            return 2
        # 远端文件与本地同名（SKILL 规定 rsync/scp 保持文件名，禁止改名传输）
        checks = [(Path(args.script).name, script_sha)]
        if args.input:
            checks.append((Path(args.input).name, input_sha))
        for name, local_sha in checks:
            remote_path = f"{args.remote_workdir.rstrip('/')}/{name}"
            proc = subprocess.run(
                ["rsess", "run", args.rsess_session, "sha256sum", remote_path],
                capture_output=True,
                text=True,
                timeout=120,
            )
            remote_sha = proc.stdout.split(maxsplit=1)[0] if proc.stdout else ""
            if proc.returncode != 0 or remote_sha != local_sha:
                print(
                    f"远端 SHA 不一致（{remote_path}）：本地 {local_sha[:12]}，"
                    f"远端 {remote_sha[:12] or '无'}"
                    + (
                        f"；rsess 失败: {proc.stderr.strip()[:120]}"
                        if proc.returncode
                        else ""
                    ),
                    file=sys.stderr,
                )
                return 2

    store = SubmissionStore()
    try:
        # 幂等复用：同一 (thread, run) 已登记过（sbatch 超时/断线后的重试、
        # 或同一提交的 bind 阶段）→ 复用原记录，绝不产生第二条记录。
        # 已有 job_id → 拒绝（禁止重复 sbatch）。
        from electromind.hpc import default_idempotency_key

        idem = args.idempotency_key or default_idempotency_key(args.thread, args.run)
        existing = next(
            (r for r in store.all() if r.idempotency_key == idem), None
        )
        if existing is not None:
            if existing.job_id:
                raise HpcSubmissionError(
                    f"thread {args.thread} run {args.run} 已有提交的作业"
                    f"（job {existing.job_id}），禁止重复 sbatch"
                )
            record = existing
        else:
            record = store.record_attempt(
                thread_id=args.thread,
                run_id=args.run,
                rsess_session=args.rsess_session,
                remote_workdir=args.remote_workdir,
                script_sha256=script_sha,
                input_sha256=input_sha,
                stdout_path=args.stdout,
                idempotency_key=args.idempotency_key,
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
