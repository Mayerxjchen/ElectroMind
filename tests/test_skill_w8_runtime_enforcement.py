"""W8 运行时强制行为测试（非文案检查）。

Design: docs/design/skill-agents-rule-migration.md（R-017/R-025 机器强制行）—
直接驱动 research-orchestrator 的 checker 脚本（validate_state / claim_task /
ready_tasks），用构造的 `.research` fixture 证明：

- R-017 昂贵 HPC 作业审批：未记录 approval 的任务无法被 claim（无法执行）。
- R-025 避免重复提交：running 任务无 lease 校验失败；已持有 active lease
  的任务重复 claim 被拦截（单一 owner）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_SCRIPTS = (
    REPO_ROOT / "skills" / "procedures" / "research-orchestrator" / "scripts"
)
FIXTURE = (
    REPO_ROOT
    / "skills"
    / "procedures"
    / "research-orchestrator"
    / "examples"
    / "minimal-project"
)


def _run_skill_script(script: str, research_dir: Path, *args: str):
    env = {**os.environ, "PYTHONPATH": str(SKILL_SCRIPTS)}
    return subprocess.run(
        [
            sys.executable,
            str(SKILL_SCRIPTS / script),
            str(research_dir),
            *args,
        ],
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def research_dir(tmp_path: Path) -> Path:
    """minimal-project fixture 副本 + T004 声明 requires_claim。"""
    dest = tmp_path / "project"
    shutil.copytree(FIXTURE, dest)
    task = dest / ".research" / "tasks" / "T004.yaml"
    text = task.read_text(encoding="utf-8")
    text = text.replace(
        """execution_policy:
  mode: single_owner
  allow_parallel_subagents: false""",
        """execution_policy:
  mode: single_owner
  allow_parallel_subagents: false
  requires_claim: true
  owner_dir: work/runs/ads-relax/
  lease_ttl_minutes: 60
  heartbeat_interval_minutes: 10
  exclusive_paths:
    - work/runs/ads-relax/""",
    )
    task.write_text(text, encoding="utf-8")
    return dest


def _write_lease(research_dir: Path, task_id: str, *, expires_at: str) -> Path:
    lease = {
        "schema_version": 1,
        "lease_id": f"L-{task_id}-test",
        "task_id": task_id,
        "owner_id": "test-runner",
        "role": "engine-runner",
        "status": "active",
        "acquired_at": "2026-06-25T00:00:00+08:00",
        "heartbeat_at": "2026-06-25T00:00:00+08:00",
        "expires_at": expires_at,
        "owner_dir": "work/runs/ads-relax/",
        "exclusive_paths": ["work/runs/ads-relax/"],
    }
    path = research_dir / ".research" / "leases" / f"{task_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lease), encoding="utf-8")
    return path


class TestExpensiveJobApprovalEnforced:
    """R-017：昂贵 HPC 提交审批由 checker 强制（approval 记录缺失 → 不可 claim）。"""

    def test_claim_blocked_without_approval_record(self, research_dir):
        """删除 approval 决策 → claim 被拒，输出 missing approval。"""
        decisions = research_dir / ".research" / "decisions.jsonl"
        rows = [
            line
            for line in decisions.read_text(encoding="utf-8").splitlines()
            if json.loads(line).get("task_id") != "T004"
        ]
        decisions.write_text("\n".join(rows) + "\n", encoding="utf-8")

        proc = _run_skill_script(
            "claim_task.py", research_dir / ".research", "T004", "--owner", "test"
        )
        assert proc.returncode != 0
        assert "approval" in (proc.stdout + proc.stderr).lower()

    def test_approval_gate_is_what_blocks_until_recorded(self, research_dir):
        """写入正确 approval 记录后，claim 的拦截原因不再是 approval。

        fixture 自带的 D003 是占位记录（kind=approval 但无策略字段），因此
        昂贵任务确实处于未审批状态 —— 这本身就是 R-017 的强制证明。
        """
        # 记录真正的审批决策（kind == 策略名）
        decisions = research_dir / ".research" / "decisions.jsonl"
        with decisions.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "decision_id": "D999",
                        "task_id": "T004",
                        "kind": "expensive_hpc_submission",
                        "decision": "approved",
                        "by": "user",
                        "reason": "test approval",
                        "created_at": "2026-06-25T00:00:00+08:00",
                    }
                )
                + "\n"
            )
        proc = _run_skill_script(
            "claim_task.py", research_dir / ".research", "T004", "--owner", "test"
        )
        out = proc.stdout + proc.stderr
        assert proc.returncode != 0  # 仍被依赖门（T003 未 accepted）拦截
        assert "approval" not in out.lower()


class TestNoDuplicateSubmissionEnforced:
    """R-025：避免重复提交 — running 任务必须有 lease；重复 claim 被拦截。"""

    def test_running_task_without_lease_fails(self, research_dir):
        """running + requires_claim 但无 lease → validate_state FAIL。"""
        task = research_dir / ".research" / "tasks" / "T004.yaml"
        text = task.read_text(encoding="utf-8").replace(
            "status: approved", "status: running"
        )
        task.write_text(text, encoding="utf-8")

        proc = _run_skill_script("validate_state.py", research_dir / ".research")
        assert proc.returncode != 0
        assert "requires an active lease" in (proc.stdout + proc.stderr)

    def _make_running_with_lease(self, research_dir: Path) -> None:
        """T004 → running + requires_claim + 有效 active lease（一致性状态）。"""
        task = research_dir / ".research" / "tasks" / "T004.yaml"
        text = task.read_text(encoding="utf-8")
        text = text.replace("status: approved", "status: running")
        text = text.replace(
            """execution_policy:
  mode: single_owner
  allow_parallel_subagents: false""",
            """execution_policy:
  mode: single_owner
  allow_parallel_subagents: false
  requires_claim: true
  owner_dir: work/runs/ads-relax/
  lease_ttl_minutes: 60
  exclusive_paths:
    - work/runs/ads-relax/""",
        )
        task.write_text(text, encoding="utf-8")
        _write_lease(research_dir, "T004", expires_at="2099-01-01T00:00:00+08:00")

    def test_active_lease_requires_running_task_status(self, research_dir):
        """状态一致性强制：active lease 存在但任务非 running → FAIL。

        这阻止「任务未真正运行却持有 lease」的绕过（R-025 单一 owner 语义）。
        """
        self._make_running_with_lease(research_dir)
        task = research_dir / ".research" / "tasks" / "T004.yaml"
        task.write_text(
            task.read_text(encoding="utf-8").replace(
                "status: running", "status: approved"
            ),
            encoding="utf-8",
        )
        proc = _run_skill_script("validate_state.py", research_dir / ".research")
        assert proc.returncode != 0
        assert "active lease task status must be running" in (proc.stdout + proc.stderr)

    def test_lease_path_conflict_blocks_claim(self, research_dir):
        """另一 running 任务持有冲突路径 lease → T004 claim 被拦（双 owner 防御）。"""
        self._make_running_with_lease(research_dir)
        # 第二个 running 任务 T999 持有同一 exclusive path
        t999 = research_dir / ".research" / "tasks" / "T999.yaml"
        t999.write_text(
            (research_dir / ".research" / "tasks" / "T004.yaml")
            .read_text(encoding="utf-8")
            .replace("id: T004", "id: T999")
            .replace("T004", "T999"),
            encoding="utf-8",
        )
        _write_lease(research_dir, "T999", expires_at="2099-01-01T00:00:00+08:00")
        # 状态必须一致：T999 是 running
        t999.write_text(
            t999.read_text(encoding="utf-8").replace(
                "status: approved", "status: running"
            ),
            encoding="utf-8",
        )
        proc = _run_skill_script(
            "claim_task.py", research_dir / ".research", "T004", "--owner", "other"
        )
        out = proc.stdout + proc.stderr
        assert proc.returncode != 0  # 不允许放行（冲突或前置门）
        assert "lease" in out.lower()
