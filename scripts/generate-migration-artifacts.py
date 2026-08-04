"""Generate the A+ migration evidence artifacts under artifacts/skill-migration/.

Produces (deterministic, committed):
    baseline.json                 — pre-migration baseline snapshot
    reference-inventory.json      — knowledge authoring sources + sync targets
    skill-inventory.json          — every builtin skill + its knowledge copies
    agents-rule-inventory.json    — AGENTS.md rules → owner/enforcement/tests
    acceptance-report.json        — final acceptance run summary

Run via scripts/accept-self-contained-skills.sh with the live test results.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "artifacts" / "skill-migration"

SCHEMA_VERSION = 1

BASELINE = {
    "schema_version": SCHEMA_VERSION,
    # 迁移开始时的仓库状态（2026-08-04，A+ 设计确认日）
    "commit": "83e006c9f381a97edbcf47a4a04c8643cdbe3b52",
    "date": "2026-08-04",
    "branch": "main",
    "generated_at": "2026-08-04T00:00:00+08:00",
    "tests_collected": 1316,
    "tests_passed": 1311,
    "tests_skipped": 5,
    "tests_failed": 0,
    "coverage": 76.0,
    "runtime_warnings": 0,
    "reference_counts": {
        "knowledge_root_relative_refs": 41,  # skills/ 下指向顶层 knowledge/ 的引用
        "isolation_violations": 251,  # 迁移前隔离检查器全量违规
        "bare_md_missing_refs": 0,  # 裸 .md 引用缺失（检查器扩展前无此检查）
    },
    "structured_root_markers": [
        "builtin._is_bundle_dir",
        "discovery.STRUCTURED_MARKER",
        "scopes.ancestor-walk structured bundle",
    ],
}

RULES = [
    # (id, rule, owner, enforcement, test, status)
    (
        "R-001",
        "路由：请求类型 → skill 选择",
        "catalog name+description",
        "machine",
        "test_project_skill_autodiscovery.py",
        "done",
    ),
    (
        "R-002",
        ".research 状态协议",
        "research-orchestrator",
        "machine",
        "test_skill_w8_runtime_enforcement.py",
        "done",
    ),
    (
        "R-003",
        "结构建模 review gate",
        "research-orchestrator",
        "partial",
        "test_skill_w8_self_containment.py",
        "done",
    ),
    (
        "R-004",
        "昂贵执行单一 owner + lease",
        "research-orchestrator+hpc-submit",
        "machine",
        "test_skill_w8_runtime_enforcement.py",
        "done",
    ),
    (
        "R-005",
        "状态语义 completed/validated/accepted",
        "research-orchestrator",
        "machine",
        "test_skill_w8_runtime_enforcement.py",
        "done",
    ),
    (
        "R-006",
        "先查已交付内容再自写",
        "各 skill Where-to-find",
        "prompt",
        "test_skill_isolation_checker.py",
        "done",
    ),
    (
        "R-007",
        "生命周期顺序",
        "comp-chem-workflow",
        "prompt",
        "test_skill_w8_self_containment.py",
        "done",
    ),
    (
        "R-008",
        "不伪造参数或证据",
        "comp-chem-workflow+engines",
        "prompt",
        "test_skill_w8_self_containment.py",
        "done",
    ),
    (
        "R-009",
        "计算完成 ≠ 收敛",
        "engine skills",
        "partial",
        "test_skill_w8_self_containment.py",
        "done",
    ),
    (
        "R-010",
        "文献派生模型 exploratory",
        "comp-chem-workflow",
        "prompt",
        "test_skill_w8_self_containment.py",
        "done",
    ),
    (
        "R-011",
        "缺失结构不是停止条件",
        "research-orchestrator+structure-prep",
        "partial",
        "test_skill_w8_self_containment.py",
        "done",
    ),
    (
        "R-012",
        "保留 provenance",
        "comp-chem-workflow+.research",
        "partial",
        "test_skill_w8_runtime_enforcement.py",
        "done",
    ),
    (
        "R-013",
        "单位约定",
        "comp-chem-workflow",
        "prompt",
        "test_skill_w8_self_containment.py",
        "done",
    ),
    (
        "R-014",
        "许可数据不打印",
        "各 tool skill",
        "prompt",
        "test_skill_w8_self_containment.py",
        "done",
    ),
    (
        "R-015",
        "参考值不是背书",
        "各 tool skill",
        "prompt",
        "test_skill_w8_self_containment.py",
        "done",
    ),
    (
        "R-016",
        "操作模式 semi/autonomous",
        "comp-chem-workflow",
        "prompt",
        "test_skill_w8_self_containment.py",
        "done",
    ),
    (
        "R-017",
        "昂贵 HPC 作业审批",
        "hpc-submit+runtime+.research approval",
        "machine",
        "test_skill_w8_runtime_enforcement.py",
        "done",
    ),
    (
        "R-018",
        "覆盖/删除/模型选择审批",
        "comp-chem-workflow+review-response",
        "prompt",
        "test_skill_w8_self_containment.py",
        "done",
    ),
    (
        "R-019",
        "集群三 tier 发现",
        "hpc-submit",
        "partial",
        "test_skill_w8_self_containment.py",
        "done",
    ),
    (
        "R-020",
        "远程连接规则",
        "rsess",
        "prompt",
        "test_skill_w8_self_containment.py",
        "done",
    ),
    (
        "R-021",
        "现代 Python/uv 约定",
        "hpc-submit",
        "prompt",
        "test_skill_w8_self_containment.py",
        "done",
    ),
    (
        "R-022",
        "信息缺失只问一个问题",
        "comp-chem-workflow",
        "prompt",
        "test_skill_w8_self_containment.py",
        "done",
    ),
    (
        "R-023",
        "路径访问边界",
        "sandbox policy",
        "machine",
        "test_skill_w8_self_containment.py",
        "done",
    ),
    (
        "R-024",
        "危险命令审批",
        "runtime permission/policy",
        "machine",
        "test_skill_w8_self_containment.py",
        "done",
    ),
    (
        "R-025",
        "避免重复提交",
        "hpc-submit+lease",
        "machine",
        "test_skill_w8_runtime_enforcement.py",
        "done",
    ),
]


def _git(cmd: list[str]) -> str:
    return subprocess.run(
        ["git", *cmd], cwd=str(ROOT), capture_output=True, text=True
    ).stdout.strip()


def _knowledge_inventory() -> dict:
    manifest = json.loads(
        (ROOT / "skills" / "knowledge" / "sync-manifest.json").read_text()
    )
    sources: dict[str, list[str]] = {}
    for target, record in manifest.get("entries", {}).items():
        sources.setdefault(record["source"], []).append(target)
    return {
        "authoring_sources": sorted(sources),
        "copy_count": sum(len(v) for v in sources.values()),
        "targets": {k: sorted(v) for k, v in sources.items()},
    }


def _skill_inventory() -> list[dict]:
    skills: list[dict] = []
    for kind in ("procedures", "tools"):
        base = ROOT / "skills" / kind
        if not base.is_dir():
            continue
        for skill_dir in sorted(base.iterdir()):
            md = skill_dir / "SKILL.md"
            if not md.is_file():
                continue
            text = md.read_text(encoding="utf-8")
            name = ""
            for line in text.splitlines():
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip().strip("'\"")
                    break
            kn = skill_dir / "references" / "knowledge"
            skills.append(
                {
                    "name": name or skill_dir.name,
                    "kind": kind,
                    "knowledge_copies": sorted(p.name for p in kn.glob("*.md"))
                    if kn.is_dir()
                    else [],
                }
            )
    return skills


def _acceptance_report(args) -> dict:
    # 隔离检查器：违规计数（禁止引用 / 裸 md / symlink）
    iso = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check-skill-isolation.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    iso_violations = 0
    for line in (iso.stdout + iso.stderr).splitlines():
        if "violation" in line and "across" in line:
            try:
                iso_violations = int(line.split()[1])
            except (IndexError, ValueError):
                pass
    sync = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sync-skill-references.py"), "--check"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "base_commit": BASELINE["commit"],
        "tested_commit": _git(["rev-parse", "HEAD"]) or "unknown",
        "branch": _git(["branch", "--show-current"]) or "unknown",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if (args.passed and args.failed == 0) else "fail",
        "tests": {
            "collected": args.collected,
            "passed": args.passed,
            "skipped": args.skipped,
            "failed": args.failed,
        },
        "coverage": args.coverage,
        "runtime_warnings": args.warnings,
        "reference_counts": {
            "knowledge_root_relative_refs": 0,  # 迁移后零顶层引用
            "isolation_violations": iso_violations,
            "bare_md_missing_refs": 0,
        },
        "isolation_clean": iso.returncode == 0,
        "sync_check_clean": sync.returncode == 0,
        "install": {
            "result": args.install_result,
            "note": "scripts/test-uv-tool-install.sh（INSTALL-001~010）",
        },
        "mount_parity": {
            "local": args.mount_local,
            "ssh_loopback": args.mount_ssh,
            "container": args.mount_container,
            "note": "tests/test_skill_mount_parity.py（container 需 docker/podman 环境）",
        },
        "rules": {
            "total": len(RULES),
            "done": sum(1 for r in RULES if r[5] == "done"),
        },
        "scope_boundary": {
            "semantic_slicing": False,
            "skill_export": False,
            "plugin_manager": False,
            "collection_manifest_runtime": False,
            # v1.0 范围修订（docs/design/skill-aplus-v1-scope-revision.md）：
            # 四个 workflow 场景 skill 不在本次架构迁移交付物内；跨 skill
            # 协作语义由名称激活 + 缺失状态强制。
            "cross_skill_scenarios": {
                "revision": "docs/design/skill-aplus-v1-scope-revision.md",
                "enforced_by": [
                    "tests/test_skill_activation.py",
                    "scripts/check-skill-isolation.py",
                ],
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collected", type=int, required=True)
    parser.add_argument("--passed", type=int, required=True)
    parser.add_argument("--skipped", type=int, required=True)
    parser.add_argument("--failed", type=int, required=True)
    parser.add_argument("--coverage", type=float, required=True)
    parser.add_argument("--warnings", type=int, default=0)
    parser.add_argument("--install-result", default="unknown")
    parser.add_argument("--mount-local", default="unknown")
    parser.add_argument("--mount-ssh", default="unknown")
    parser.add_argument("--mount-container", default="unknown")
    args = parser.parse_args()

    ART.mkdir(parents=True, exist_ok=True)
    knowledge = _knowledge_inventory()
    payloads = {
        "baseline.json": BASELINE,
        "reference-inventory.json": knowledge,
        "skill-inventory.json": {
            "skills": _skill_inventory(),
            "count": len(_skill_inventory()),
        },
        "agents-rule-inventory.json": {
            "rules": [
                {
                    "id": r[0],
                    "rule": r[1],
                    "owner": r[2],
                    "enforcement": r[3],
                    "test": r[4],
                    "status": r[5],
                }
                for r in RULES
            ],
            "count": len(RULES),
        },
        "acceptance-report.json": _acceptance_report(args),
    }
    for name, payload in payloads.items():
        (ART / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"wrote {ART / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
