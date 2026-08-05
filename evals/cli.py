"""Eval CLI — ``python -m evals [list|run|baseline]``。

命令：
- ``list``：列出全部任务（可加 ``--category`` 过滤）
- ``run``：运行任务集合并输出 JSON 报告（``--categories`` / ``--ids``）
- ``baseline``：运行并保存基线到 artifacts/acceptance/m0-eval-baseline/

输出 JSON 可被 CI 比较（M0 §5.3）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

from .drivers import (
    is_driver_task,
    observations_to_result,
    run_task_with_driver,
)
from .harness import run_agent_task
from .registry import (
    DEFAULT_TASKS_DIR,
    TaskRegistry,
    category_counts,
    load_all_tasks,
)
from .report import (
    TaskResult,
    build_report,
    make_result,
    save_report,
)
from .task import FailureCategory
from .verifier import (
    DeterministicVerifier,
    VerificationResult,
    side_effect_digest,
)

BASELINE_DIR = (
    Path(__file__).resolve().parent.parent
    / "artifacts"
    / "acceptance"
    / "m0-eval-baseline"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evals",
        description="ElectroMind Golden Task 评测",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="列出任务")
    p_list.add_argument("--category", default="")
    p_list.add_argument("--json", action="store_true")

    p_run = sub.add_parser("run", help="运行任务")
    p_run.add_argument("--categories", default="", help="逗号分隔类别过滤")
    p_run.add_argument("--ids", default="", help="逗号分隔任务 id")
    p_run.add_argument("--output", default="", help="报告输出路径")
    p_run.add_argument("--runs", type=int, default=1, help="每个任务连续执行次数")
    p_run.add_argument(
        "--work-root", default="", help="隔离 HOME 根目录（默认临时目录）"
    )

    p_base = sub.add_parser("baseline", help="运行并保存基线")
    p_base.add_argument("--categories", default="", help="逗号分隔类别过滤")
    p_base.add_argument("--ids", default="", help="逗号分隔任务 id")
    p_base.add_argument("--runs", type=int, default=1, help="每个任务连续执行次数")
    p_base.add_argument("--work-root", default="", help="隔离 HOME 根目录")
    p_base.add_argument("--output-dir", default=str(BASELINE_DIR))
    return parser


async def run_selected(
    tasks: list,
    *,
    runs: int,
    work_root: Path,
    runner_factory=None,
) -> list:
    """执行任务列表，返回 TaskResult 列表。"""
    verifier = DeterministicVerifier()
    results = []
    for task in tasks:
        observations = []
        if is_driver_task(task):
            obs = await run_task_with_driver(task, work_root)
            d = observations_to_result(task, obs)
            results.append(
                TaskResult(
                    id=d["id"],
                    category=d["category"],
                    passed=d["passed"],
                    failure=d["failure"],
                    details=d["details"],
                    runs=d["runs"],
                    side_effect_digest=d["side_effect_digest"],
                )
            )
            continue
        passed = True
        failure = None
        details = ""
        for run_index in range(runs):
            obs = await run_agent_task(
                task,
                thread_root=work_root / task.id / str(run_index),
                runner_factory=runner_factory,
            )
            observations.append(obs)
            verification = verifier.verify(task, obs)
            if not verification.passed:
                passed = False
                failure = verification.failure
                details = verification.details
                break
        if passed and runs > 1:
            # 确定性：多次运行的外部副作用序列必须完全一致
            digests = {side_effect_digest(o) for o in observations if o.side_effect_log}
            if len(digests) > 1:
                passed = False
                failure = FailureCategory.STATE
                details = f"多次运行副作用摘要不一致: {sorted(digests)}"
        results.append(
            make_result(
                task,
                VerificationResult(passed=passed, failure=failure, details=details),
                runs=runs,
                observations=observations,
            )
        )
    return results


def select_tasks(registry: TaskRegistry, categories: list[str], ids: list[str]) -> list:
    tasks = registry.all()
    if ids:
        selected = [t for t in tasks if t.id in ids]
        missing = [i for i in ids if i not in {t.id for t in selected}]
        if missing:
            raise ValueError(f"未知任务 id: {missing}")
        return selected
    if categories:
        return [t for t in tasks if t.category in categories]
    return tasks


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry = TaskRegistry(load_all_tasks(DEFAULT_TASKS_DIR))

    if args.command == "list":
        tasks = registry.all()
        if args.category:
            tasks = [t for t in tasks if t.category == args.category]
        if args.json:
            print(
                json.dumps(
                    [
                        {
                            "id": t.id,
                            "category": t.category,
                            "title": t.title,
                            "driver": bool(t.driver),
                        }
                        for t in tasks
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            for t in tasks:
                kind = "driver" if t.driver else "agent"
                print(f"{t.id:<14} {t.category:<10} [{kind}] {t.title}")
            print(f"\n共 {len(tasks)} 个任务；按类别: {category_counts(tasks)}")
        return 0

    if args.command in ("run", "baseline"):
        categories = (
            [c.strip() for c in args.categories.split(",") if c.strip()]
            if args.categories
            else []
        )
        ids = [i.strip() for i in args.ids.split(",") if i.strip()]
        try:
            tasks = select_tasks(registry, categories, ids)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        work_root = (
            Path(args.work_root)
            if args.work_root
            else Path(tempfile.mkdtemp(prefix="evals-"))
        )
        results = asyncio.run(run_selected(tasks, runs=args.runs, work_root=work_root))

        commit = _current_commit()
        report = build_report(results, tested_commit=commit)
        report["category_counts"] = category_counts(tasks)
        report["work_root"] = str(work_root)

        if args.command == "baseline":
            baseline_dir = Path(args.output_dir)
            report_path = baseline_dir / "baseline.json"
            save_report(report, report_path)
            print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
            print(f"\n基线已保存: {report_path}")
            return 0 if report["summary"]["passed"] == report["summary"]["total"] else 2

        output = Path(args.output) if args.output else None
        if output:
            save_report(report, output)
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
        if output is None:
            # 无输出文件时也打印失败详情
            for r in results:
                if not r.passed:
                    print(f"  FAIL {r.id}: [{r.failure}] {r.details}")
        return 0 if report["summary"]["passed"] == report["summary"]["total"] else 2

    return 1


def _current_commit() -> str:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or ""
    except Exception:  # noqa: BLE001
        return ""


if __name__ == "__main__":
    sys.exit(main())
