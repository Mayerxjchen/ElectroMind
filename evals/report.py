"""Eval 报告 — 机器可读 JSON 输出，可在 CI 中比较。

报告 schema（M0 §5.3/§5.4）：

```json
{
  "schema_version": 1,
  "tested_commit": "<sha>",
  "generated_at": "<iso>",
  "results": [
    {"id": "...", "category": "...", "passed": true,
     "failure": null | "planning|model|tool|environment|state|validation|safety",
     "details": "...", "runs": 1, "side_effect_digest": "..."}
  ],
  "summary": {"total": 60, "passed": 0, "success_rate": 0.0,
              "by_category": {...}, "by_failure": {...}}
}
```
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .task import TaskSpec
from .verifier import EvalObservation, VerificationResult, side_effect_digest


@dataclass(slots=True)
class TaskResult:
    id: str
    category: str
    passed: bool
    failure: str | None = None
    details: str = ""
    runs: int = 1
    side_effect_digest: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def make_result(
    task: TaskSpec,
    verification: VerificationResult,
    *,
    runs: int,
    observations: list[EvalObservation],
) -> TaskResult:
    """从验证结果构建任务结果；多 run 时记录副作用摘要。"""
    digest = ""
    if observations and observations[-1].side_effect_log:
        digest = side_effect_digest(observations[-1])
    return TaskResult(
        id=task.id,
        category=task.category,
        passed=verification.passed,
        failure=str(verification.failure) if verification.failure else None,
        details=verification.details,
        runs=runs,
        side_effect_digest=digest,
    )


def summarize(results: list[TaskResult]) -> dict[str, Any]:
    """汇总：总数、通过数、成功率、按类别/失败分类统计。"""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    by_category: dict[str, dict[str, int]] = {}
    by_failure: dict[str, int] = {}
    for r in results:
        cat = by_category.setdefault(r.category, {"total": 0, "passed": 0})
        cat["total"] += 1
        if r.passed:
            cat["passed"] += 1
        if r.failure is not None:
            by_failure[r.failure] = by_failure.get(r.failure, 0) + 1
    return {
        "total": total,
        "passed": passed,
        "success_rate": round(passed / total, 4) if total else 0.0,
        "by_category": by_category,
        "by_failure": by_failure,
    }


def build_report(
    results: list[TaskResult],
    *,
    tested_commit: str = "",
    baseline: dict | None = None,
) -> dict[str, Any]:
    """构建完整报告（含基线对比）。"""
    report: dict[str, Any] = {
        "schema_version": 1,
        "tested_commit": tested_commit,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": [r.to_dict() for r in results],
        "summary": summarize(results),
    }
    if baseline is not None:
        report["baseline"] = baseline.get("summary")
    return report


def save_report(report: dict, path: Path) -> Path:
    """原子写报告 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def load_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def compare_to_baseline(report: dict, baseline: dict) -> dict:
    """与基线对比：核心安全/恢复类别成功率不得下降。"""
    cur = report["summary"]
    base = baseline.get("summary", {})
    comparison: dict[str, Any] = {"safe": True, "regressions": []}
    for category, critical in (("safety", True), ("recovery", True)):
        base_cat = base.get("by_category", {}).get(category, {})
        cur_cat = cur.get("by_category", {}).get(category, {})
        base_rate = _rate(base_cat)
        cur_rate = _rate(cur_cat)
        if critical and cur_rate < base_rate:
            comparison["safe"] = False
            comparison["regressions"].append(
                {
                    "category": category,
                    "baseline_rate": base_rate,
                    "current_rate": cur_rate,
                }
            )
    comparison["overall_delta"] = round(
        cur.get("success_rate", 0.0) - base.get("success_rate", 0.0), 4
    )
    return comparison


def _rate(cat: dict) -> float:
    total = cat.get("total", 0)
    return round(cat.get("passed", 0) / total, 4) if total else 0.0
