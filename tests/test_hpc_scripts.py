"""P3.5: 三个 HPC 入口脚本（prepare/reconcile/collect）端到端。

用一个临时 home 隔离记录文件；rsess/rsync 用 stub 替换（不真连远端）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "skills" / "tools" / "hpc-submit" / "scripts"


def _run_script(script: str, *args: str, home: Path):
    env = dict(os.environ)
    # 让 electromind.hpc 落到临时 home
    env["ELECTROMIND_HOME"] = str(home)
    env["PYTHONPATH"] = str(Path(__file__).parent.parent / "src")
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(home),
    )


@pytest.fixture()
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir(parents=True, exist_ok=True)
    return h


def test_prepare_submission_creates_record(home):
    script = home / "run.sh"
    script.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    r = _run_script(
        "prepare_submission.py",
        "--thread",
        "t1",
        "--run",
        "r1",
        "--script",
        str(script),
        "--bind-job-id",
        "sb-100",
        home=home,
    )
    assert r.returncode == 0, r.stderr
    sub_id = r.stdout.strip()
    assert sub_id.startswith("sub-")

    # 再次提交同 thread+run → 拒绝（防重复）
    r2 = _run_script(
        "prepare_submission.py",
        "--thread",
        "t1",
        "--run",
        "r1",
        "--script",
        str(script),
        home=home,
    )
    assert r2.returncode == 2
    assert "禁止重复 sbatch" in r2.stderr


def _run_script_env(script: str, *args: str, home: Path, env_extra: dict):
    env = dict(os.environ)
    env["ELECTROMIND_HOME"] = str(home)
    env["PYTHONPATH"] = str(Path(__file__).parent.parent / "src")
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(home),
    )


def test_prepare_submission_verify_remote_ok_and_mismatch(home, tmp_path):
    """--verify-remote：远端 SHA 一致 → 提交；不一致 → 拒绝（退出码 2）。"""
    script = home / "run.sh"
    script.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")

    # stub rsess：sha256sum 远端路径 → 计算本地同名文件哈希
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "rsess"
    stub.write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do last="$a"; done\n'
        'sha256sum "$ELECTROMIND_HOME/$(basename "$last")"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    env_extra = {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}

    r = _run_script_env(
        "prepare_submission.py",
        "--thread",
        "t",
        "--run",
        "r",
        "--script",
        str(script),
        "--rsess-session",
        "sess-x",
        "--remote-workdir",
        "/remote/work",
        "--verify-remote",
        home=home,
        env_extra=env_extra,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().startswith("sub-")

    # stub rsess 返回错误哈希 → 必须拒绝（禁止在内容不一致时提交）
    bad = bin_dir / "rsess"
    bad.write_text(
        "#!/bin/sh\n"
        "printf '0000000000000000000000000000000000000000000000000000000000000000  x\\n'\n",
        encoding="utf-8",
    )
    bad.chmod(0o755)
    r2 = _run_script_env(
        "prepare_submission.py",
        "--thread",
        "t",
        "--run",
        "r2",
        "--script",
        str(script),
        "--rsess-session",
        "sess-x",
        "--remote-workdir",
        "/remote/work",
        "--verify-remote",
        home=home,
        env_extra=env_extra,
    )
    assert r2.returncode == 2
    assert "远端 SHA 不一致" in r2.stderr

    # 缺 session/workdir 直接拒绝，不静默跳过校验
    r3 = _run_script_env(
        "prepare_submission.py",
        "--thread",
        "t",
        "--run",
        "r3",
        "--script",
        str(script),
        "--verify-remote",
        home=home,
        env_extra=env_extra,
    )
    assert r3.returncode == 2
    assert "--verify-remote 需要" in r3.stderr


def test_prepare_submission_missing_script(home):
    r = _run_script(
        "prepare_submission.py",
        "--thread",
        "t",
        "--run",
        "r",
        "--script",
        str(home / "nope.sh"),
        home=home,
    )
    assert r.returncode == 2
    assert "无法读取" in r.stderr


def test_reconcile_job_unknown_when_rsess_fails(home, monkeypatch):
    """rsess 不可达 → 输出 UNKNOWN，不猜测（stub rsess 失败）。"""
    script = home / "run.sh"
    script.write_text("x", encoding="utf-8")
    r = _run_script(
        "prepare_submission.py",
        "--thread",
        "t",
        "--run",
        "r",
        "--script",
        str(script),
        "--bind-job-id",
        "sb-200",
        home=home,
    )
    sub_id = r.stdout.strip()
    # stub rsess：不可执行 → 失败路径
    r2 = _run_script(
        "reconcile_job.py",
        "--submission",
        sub_id,
        "--rsess-session",
        "no-such-rsess",
        home=home,
    )
    # rsess 命令本身缺失或超时 → UNKNOWN（退出码 3），绝不猜成功
    assert r2.returncode == 3
    assert r2.stdout.strip() == "unknown"
