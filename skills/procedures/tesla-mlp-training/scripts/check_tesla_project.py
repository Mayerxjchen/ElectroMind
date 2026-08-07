#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Check a TESLA project skeleton: 00-config, 01-workflow, workdir, run.sh.

Verifies that the four canonical project entries exist and are readable.
The workdir name follows this repository's convention (20-workdir); a
different *workdir* sibling is reported as a warning, not an error, because
upstream examples may name it differently.

Prints JSON; exit 0 on pass, 1 on fail.

Example:
    python scripts/check_tesla_project.py --project-root ./water64
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _probe(root: Path, name: str) -> dict:
    path = root / name
    return {
        "exists": path.exists(),
        "readable": path.exists() and os.access(path, os.R_OK),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".", help="TESLA project root")
    parser.add_argument("--config-dir", default="00-config")
    parser.add_argument("--workflow-dir", default="01-workflow")
    parser.add_argument("--workdir", default="20-workdir")
    parser.add_argument("--run-script", default="run.sh")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    errors: list[str] = []
    warnings: list[str] = []

    if not root.is_dir():
        errors.append(f"{root}: not a directory")

    paths = {
        "config_dir": _probe(root, args.config_dir),
        "workflow_dir": _probe(root, args.workflow_dir),
        "workdir": _probe(root, args.workdir),
        "run_script": _probe(root, args.run_script),
    }

    for key, probe in paths.items():
        if not probe["exists"]:
            errors.append(f"{key} missing: {root / getattr(args, key)}")
        elif not probe["readable"]:
            errors.append(f"{key} not readable: {root / getattr(args, key)}")

    # Drift hint: upstream examples may use a differently named workdir.
    workdir_hint = sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and "workdir" in p.name and p.name != args.workdir
    )
    if not paths["workdir"]["exists"] and workdir_hint:
        warnings.append(
            f"workdir {args.workdir!r} not found; found {', '.join(workdir_hint)}; "
            "read run.sh for the actual workdir name"
        )

    verdict = {
        "status": "pass" if not errors else "fail",
        "project": str(root),
        "paths": paths,
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(verdict, indent=2))
    print(f"check_tesla_project: {verdict['status']}", file=sys.stderr)
    return 0 if verdict["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
