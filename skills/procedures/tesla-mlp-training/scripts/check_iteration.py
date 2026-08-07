#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Check one TESLA iteration for completeness, separating COMPLETED from VALIDATED.

For every stage, "completed" means the <stage>.done marker exists (execution
finished) and "validated" means the <stage>.validated marker exists (the
stage's scientific checks passed). These two fields are always reported
separately; a done marker is never treated as validity.

Also reads and echoes the iteration manifest (iteration-manifest.json) when
present.

Prints JSON; exit 0 on pass, 1 on degraded (all completed, some unvalidated)
or fail.

Example:
    python scripts/check_iteration.py --workdir ./water64/20-workdir --iteration iter-1
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_STAGES = [
    "01_train",
    "02_explore",
    "03_screen",
    "04_label",
    "05_update",
]
DEFAULT_ARTIFACTS = {
    "01_train": "graph*.pb",
    "02_explore": "model_devi.out",
    "03_screen": "*.xyz",
    "04_label": "*.out",
    "05_update": "type.raw",
}


def _numeric_suffix(name: str) -> int:
    match = re.search(r"(\d+)$", name)
    return int(match.group(1)) if match else -1


def find_iteration_dir(workdir: Path, name: str | None, errors: list[str]) -> Path | None:
    if name:
        candidate = workdir / name
        if candidate.is_dir():
            return candidate
        candidate = Path(name)
        if candidate.is_dir():
            return candidate
        errors.append(f"iteration {name!r} not found")
        return None
    iterations = sorted(
        p for p in workdir.iterdir()
        if p.is_dir() and p.name.startswith("iter-")
    )
    if not iterations:
        errors.append(f"no iter-* directories under {workdir}")
        return None
    return max(iterations, key=lambda p: _numeric_suffix(p.name))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", default="20-workdir")
    parser.add_argument(
        "--iteration",
        default=None,
        help="iteration dir name or path (default: highest iter-* under workdir)",
    )
    parser.add_argument(
        "--stages",
        default=",".join(DEFAULT_STAGES),
        help="comma-separated stage names",
    )
    parser.add_argument(
        "--artifact",
        action="append",
        default=[],
        metavar="STAGE=GLOB",
        help="required artifact glob for a stage (repeatable)",
    )
    parser.add_argument("--done-suffix", default=".done")
    parser.add_argument("--validated-suffix", default=".validated")
    parser.add_argument("--manifest", default="iteration-manifest.json")
    parser.add_argument(
        "--optional-stage",
        action="append",
        default=[],
        help="stage allowed to have no artifacts (repeatable)",
    )
    args = parser.parse_args()

    workdir = Path(args.workdir).resolve()
    errors: list[str] = []
    warnings: list[str] = []

    if not workdir.is_dir():
        print(json.dumps({
            "status": "fail",
            "errors": [f"{workdir}: not a directory"],
            "warnings": [],
        }, indent=2))
        return 1

    iteration = find_iteration_dir(workdir, args.iteration, errors)
    if iteration is None:
        print(json.dumps({"status": "fail", "errors": errors, "warnings": warnings}, indent=2))
        return 1

    artifacts = dict(DEFAULT_ARTIFACTS)
    for spec in args.artifact:
        if "=" not in spec:
            errors.append(f"--artifact expects STAGE=GLOB, got {spec!r}")
            continue
        stage, glob = spec.split("=", 1)
        artifacts[stage] = glob

    stages = [s.strip() for s in args.stages.split(",") if s.strip()]
    stage_report = []
    for stage in stages:
        stage_dir = iteration / stage
        completed = (iteration / (stage + args.done_suffix)).is_file()
        validated = (iteration / (stage + args.validated_suffix)).is_file()
        matches = []
        if stage_dir.is_dir():
            pattern = artifacts.get(stage)
            if pattern:
                matches = sorted(
                    str(p.relative_to(iteration)) for p in stage_dir.rglob(pattern)
                )
            if not matches and stage not in args.optional_stage:
                errors.append(
                    f"{stage}: no artifacts matching {pattern!r} in {stage_dir}"
                )
        else:
            errors.append(f"{stage}: stage directory missing: {stage_dir}")
        stage_report.append({
            "stage": stage,
            "completed": completed,
            "validated": validated,
            "artifacts": matches,
        })
        if completed and not validated:
            warnings.append(
                f"{stage}: completed but NOT validated (missing "
                f"{stage + args.validated_suffix})"
            )

    manifest = None
    manifest_path = iteration / args.manifest
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"manifest unreadable: {manifest_path}: {exc}")
    elif args.manifest != "none":
        warnings.append(f"no iteration manifest at {manifest_path}")

    all_completed = all(s["completed"] for s in stage_report)
    all_validated = all(s["validated"] for s in stage_report)

    if errors:
        status = "fail"
    elif all_completed and all_validated:
        status = "pass"
    elif all_completed:
        status = "degraded"  # everything ran, but validity is missing
    else:
        status = "fail"

    verdict = {
        "status": status,
        "iteration": str(iteration),
        "stages": stage_report,
        "all_completed": all_completed,
        "all_validated": all_validated,
        "manifest": manifest,
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(verdict, indent=2))
    print(
        f"check_iteration: {status} "
        f"(completed={all_completed}, validated={all_validated})",
        file=sys.stderr,
    )
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
