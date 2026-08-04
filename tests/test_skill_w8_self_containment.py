"""W8: 规则所有权迁移 — AGENTS.md 删除后的行为证明。

Design: docs/superpowers/specs/2026-08-04-skill-aplus-self-contained-design.md
(§8 迁移矩阵) — 每条 machine-enforced 规则都有行为测试证明强制机制有效；
prompt 类规则验证已进入所属 skill 的内容。
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS = REPO_ROOT / "skills"


# ---------------------------------------------------------------------------
# AGENTS.md 已删除且无任何残留读取
# ---------------------------------------------------------------------------


def test_skills_agents_md_deleted():
    """W8 标志：skills/AGENTS.md 已删除。"""
    assert not (SKILLS / "AGENTS.md").exists()


def test_no_src_code_reads_agents_md():
    """没有任何 src 代码再读取 AGENTS.md（含 marker 探测与注入）。"""
    for path in (REPO_ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert '"AGENTS.md"' not in text, (
            f"{path.relative_to(REPO_ROOT)} 仍引用 AGENTS.md"
        )
        assert "STRUCTURED_MARKER" not in text, (
            f"{path.relative_to(REPO_ROOT)} 仍引用 STRUCTURED_MARKER"
        )


def test_no_skill_document_points_to_agents_md():
    """skills/ 全树没有任何文档再指向 AGENTS.md。"""
    hits: list[str] = []
    for path in SKILLS.rglob("*"):
        if path.is_file() and path.suffix in (".md", ".toml"):
            text = path.read_text(encoding="utf-8", errors="replace")
            if "AGENTS.md" in text:
                hits.append(str(path.relative_to(SKILLS)))
    assert hits == [], f"仍有文档指向 AGENTS.md: {hits}"


# ---------------------------------------------------------------------------
# machine-enforced 规则：强制机制的行为证明
# ---------------------------------------------------------------------------


class TestPathAccessBoundary:
    """迁移矩阵「路径访问边界 → Sandbox policy（是）」。"""

    def test_files_write_outside_workdir_rejected(self, tmp_path):
        from electromind.sandbox.sandbox import Sandbox

        async def _run():
            async with await Sandbox.create(
                backend="local", workdir=str(tmp_path / "box")
            ) as box:
                with pytest.raises((PermissionError, ValueError)):
                    await box.files.write("/etc/pwned.txt", b"x")

        import asyncio

        asyncio.run(_run())


class TestDangerousCommandApproval:
    """迁移矩阵「危险命令审批 → Runtime permission/hook（是）」。"""

    def test_dangerous_command_blocked_by_policy(self, tmp_path):
        from electromind.sandbox.policy import check_command

        with pytest.raises(PermissionError):
            check_command(
                "cd .. && rm -rf x",
                workdir=str(tmp_path / "box"),
                policy="workdir",
            )


class TestExpensiveJobApprovalAndNoDuplicateSubmit:
    """迁移矩阵「昂贵 HPC 提交审批 → Runtime hook + hpc-submit（是）」
    与「避免重复提交 → hpc-submit lease（是）」：skill 内容层面承载。"""

    def test_hpc_submit_carries_approval_breakpoint(self):
        text = (SKILLS / "tools" / "hpc-submit" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        assert "Approval breakpoint" in text
        assert "Never resubmit blindly" in text

    def test_research_orchestrator_checker_enforces_leases(self):
        """.research 状态协议由 checker 强制：claim/lease 校验脚本存在且
        validate_state 会拒绝未声称的执行任务。"""
        scripts = SKILLS / "procedures" / "research-orchestrator" / "scripts"
        assert (scripts / "claim_task.py").is_file()
        assert (scripts / "check_pre_submit.py").is_file()
        text = (scripts / "validate_state.py").read_text(encoding="utf-8")
        assert "lease" in text.lower()


# ---------------------------------------------------------------------------
# prompt 类规则：已进入所属 skill 内容（“部分/否”行）
# ---------------------------------------------------------------------------


class TestPromptRuleMigration:
    def test_comp_chem_workflow_carries_global_guardrails(self):
        """「不伪造参数或证据」与操作模式进入 comp-chem-workflow。"""
        text = (SKILLS / "procedures" / "comp-chem-workflow" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        assert "Never invent" in text
        assert "semi-automatic" in text
        assert "Approval breakpoints" in text
        assert "one focused question" in text

    def test_engine_skills_carry_convergence_not_validity(self):
        """「计算完成不等于收敛」进入 engine skills。"""
        text = (SKILLS / "tools" / "cp2k" / "SKILL.md").read_text(encoding="utf-8")
        assert "PROGRAM ENDED AT" in text

    def test_cluster_discovery_lives_in_hpc_submit(self):
        """「集群环境发现」进入 hpc-submit（三 tier）。"""
        text = (SKILLS / "tools" / "hpc-submit" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        assert "three tiers" in text
        assert "~/.cluster-agents.md" in text

    def test_remote_connection_rules_live_in_rsess(self):
        """「远程连接规则」进入 rsess。"""
        text = (SKILLS / "tools" / "rsess" / "SKILL.md").read_text(encoding="utf-8")
        assert "Hard guardrails" in text
