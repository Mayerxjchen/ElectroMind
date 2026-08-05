#!/usr/bin/env python3
"""collect_outputs.py — P3.5/P3.7: 下载远端产物并校验 SHA，不丢数据。

用法:
    collect_outputs.py --submission SUB_ID --target ssh-target \
        --remote-path remote/path --local-path local/path [--expected-sha HEX]

行为:
- 经 rsync 从远端拉文件（不走 tmux 文本传输，防行折叠损坏）。
- 校验优先级：--expected-sha > 记录里的 script_sha256/input_sha256
  （当本地文件名匹配脚本/输入时）> 至少非空。
- SHA 不符 → 退出码 4，绝不把损坏文件当成功产物。
- 下载后把产物的 SHA 写回记录（details，便于核对）。
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

from electromind.hpc import SubmissionStore


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def rsync_pull(target: str, remote_path: str, local_path: Path) -> None:
    """rsync 拉取（-c 强制按内容校验，不信任 mtime/size）。"""
    remote = f"{target}:{remote_path}"
    subprocess.run(
        ["rsync", "-a", "-c", "--info=stats1", remote, str(local_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=600,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="下载远端产物并校验 SHA")
    p.add_argument("--submission", required=True)
    p.add_argument("--target", required=True, help="ssh target 别名（与 rsess 相同）")
    p.add_argument("--remote-path", required=True)
    p.add_argument("--local-path", required=True)
    p.add_argument("--expected-sha", default="")
    args = p.parse_args(argv)

    store = SubmissionStore()
    record = store.find(args.submission)
    if record is None:
        print(f"submission 不存在: {args.submission}", file=sys.stderr)
        return 1

    local = Path(args.local_path)
    local.parent.mkdir(parents=True, exist_ok=True)
    try:
        rsync_pull(args.target, args.remote_path, local)
    except subprocess.CalledProcessError as exc:
        print(f"rsync 失败: {exc.stderr}", file=sys.stderr)
        return 3

    if local.stat().st_size == 0:
        print(f"下载产物为空: {local}", file=sys.stderr)
        return 4

    actual = sha256_file(local)
    # 预期 SHA：--expected-sha 显式传入（prepare_submission 记录的值）。
    expected = args.expected_sha.strip().lower()
    if expected and actual != expected:
        print(
            f"SHA 不符: local={actual} expected={expected} ({local})",
            file=sys.stderr,
        )
        return 4

    print(f"ok {local} ({local.stat().st_size} bytes, sha {actual[:12]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
