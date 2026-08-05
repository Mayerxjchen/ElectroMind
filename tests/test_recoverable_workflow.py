"""P0-9: CP2K→DeepMD 12 步可恢复工作流回归测试。"""

from __future__ import annotations

import asyncio
import os

from evals.workflows.cp2k_deepmd import run_recoverable_workflow


def test_recoverable_workflow_12_steps(tmp_path):
    """12 步全过：Plan 审批→Preflight→提交持久化→进程恢复→scheduler
    查询不重提→SSH 对账→解析带单位来源→Parser 失败保持 Completed→修复
    Validated→Reviewer 角色隔离→用户 ACCEPTED→Provenance 报告。"""
    prev = os.environ.get("ELECTROMIND_HOME")
    try:
        evidence = asyncio.run(run_recoverable_workflow(tmp_path))
        assert evidence["all_passed"], [
            (s["step"], s["name"], s["detail"])
            for s in evidence["steps"]
            if not s["ok"]
        ]
        steps = {s["step"]: s for s in evidence["steps"]}
        assert set(steps) == set(range(1, 13))
        # 关键语义断言
        assert steps[5]["queried_status"] == "running"
        assert steps[3]["job_id"].startswith("job-")
        assert steps[7]["unit"] == "Hartree"
        assert steps[8]["ok"]
        assert steps[12]["accepted_by"] == "user-alice"
    finally:
        if prev is None:
            os.environ.pop("ELECTROMIND_HOME", None)
        else:
            os.environ["ELECTROMIND_HOME"] = prev
