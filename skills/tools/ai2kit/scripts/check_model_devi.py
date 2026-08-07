#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Validate a model_devi.out file: readability, column layout, frame count, finite values, step mapping, summary statistics.

The expected layout is 1 + 9*n_models columns: step, then per model
max/avg/min of virial, force, energy deviations. Optional --lo/--hi grade
candidate counts on the chosen deviation column (default max_devi_f).

Prints JSON; exit 0 on pass, 1 on fail.

Example:
    python scripts/check_model_devi.py --md-file ./explore/model_devi.out \\
        --expected-frames 200 --lo 0.1 --hi 0.2
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

QUANTITY_OFFSETS = {"v": 0, "f": 3, "e": 6}
STAT_OFFSETS = {"max": 0, "avg": 1, "min": 2}


def _is_float(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def generated_names(ncols: int) -> list[str]:
    if ncols < 2:
        return ["step"]
    n_models = (ncols - 1) // 9
    names = ["step"]
    for group in range(max(n_models, 1)):
        for quantity in ("v", "f", "e"):
            for stat in ("max", "avg", "min"):
                names.append(f"{stat}_devi_{quantity}_{group}")
    return names[:ncols]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--md-file", required=True, help="path to model_devi.out"
    )
    parser.add_argument(
        "--expected-frames",
        type=int,
        default=None,
        help="declared number of data rows (trajectory frames)",
    )
    parser.add_argument(
        "--lo", type=float, default=None, help="lower grading threshold"
    )
    parser.add_argument(
        "--hi", type=float, default=None, help="upper grading threshold"
    )
    parser.add_argument(
        "--col",
        default="max_devi_f",
        help="deviation column used for grading (default: max_devi_f)",
    )
    args = parser.parse_args()

    path = Path(args.md_file).resolve()
    errors: list[str] = []
    warnings: list[str] = []

    if not path.is_file():
        print(json.dumps({
            "status": "fail",
            "file": str(path),
            "errors": [f"{path}: file not found"],
            "warnings": [],
        }, indent=2))
        return 1

    lines = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    lines.append(line)
    except OSError as exc:
        print(json.dumps({
            "status": "fail",
            "file": str(path),
            "errors": [f"{path}: cannot read: {exc}"],
            "warnings": [],
        }, indent=2))
        return 1

    if not lines:
        errors.append("file is empty")

    header: list[str] | None = None
    data_tokens: list[list[str]] = []
    for line in lines:
        tokens = line.split()
        if header is None and not all(_is_float(t) for t in tokens):
            header = tokens
        else:
            data_tokens.append(tokens)

    rows: list[list[float]] = []
    ncols: int | None = None
    for tokens in data_tokens:
        if ncols is None:
            ncols = len(tokens)
        elif len(tokens) != ncols:
            errors.append(
                f"ragged row: expected {ncols} columns, got {len(tokens)}"
            )
            continue
        try:
            rows.append([float(t) for t in tokens])
        except ValueError:
            errors.append(f"non-numeric row: {' '.join(tokens)}")

    if ncols is None:
        ncols = 0
    if ncols and (ncols - 1) % 9 != 0:
        warnings.append(
            f"column count {ncols} is not 1 + 9*n_models; "
            "the producer layout may have drifted"
        )
    if header is not None and len(header) != ncols:
        warnings.append(
            f"header has {len(header)} columns but data has {ncols}"
        )

    frames = len(rows)
    nonfinite = 0
    for row in rows:
        for value in row:
            if not math.isfinite(value):
                nonfinite += 1
    if nonfinite:
        errors.append(f"{nonfinite} non-finite value(s) in deviation data")

    columns = (
        header
        if header is not None and len(header) == ncols
        else generated_names(ncols)
    )

    step = {}
    if rows:
        steps = [int(r[0]) for r in rows if r[0] == int(r[0])]
        if len(steps) != frames:
            errors.append("step column contains non-integer values")
        else:
            non_decreasing = all(a <= b for a, b in zip(steps, steps[1:]))
            unique = len(set(steps))
            step = {
                "first": steps[0],
                "last": steps[-1],
                "non_decreasing": non_decreasing,
                "unique_steps": unique,
            }
            if not non_decreasing:
                errors.append(
                    "step column is not non-decreasing; trajectory mapping is broken"
                )
            if unique != frames:
                warnings.append(
                    f"step column has {unique} unique values for {frames} rows; "
                    "frame-to-trajectory mapping is not 1:1"
                )
    else:
        errors.append("no numeric data rows")

    # Column stats and per-quantity summary. Quantities sit at fixed offsets
    # within each per-model group when no header is present.
    summary: dict[str, dict] = {}
    if rows and ncols >= 2:
        n_models = (ncols - 1) // 9 if (ncols - 1) % 9 == 0 else 1
        for quantity in ("v", "f", "e"):
            max_cols = []
            avg_cols = []
            for group in range(n_models):
                base = 1 + 9 * group
                max_cols.append(base + QUANTITY_OFFSETS[quantity] + STAT_OFFSETS["max"])
                avg_cols.append(base + QUANTITY_OFFSETS[quantity] + STAT_OFFSETS["avg"])
            vals_max = [row[c] for row in rows for c in max_cols if c < ncols]
            vals_avg = [row[c] for row in rows for c in avg_cols if c < ncols]
            if vals_max:
                summary[f"max_devi_{quantity}"] = {
                    "max": max(vals_max),
                    "mean": sum(vals_max) / len(vals_max),
                    "min": min(vals_max),
                }
            if vals_avg:
                summary[f"avg_devi_{quantity}"] = {
                    "mean": sum(vals_avg) / len(vals_avg),
                }
        for idx, name in enumerate(columns[1:], start=1):
            summary.setdefault(name, {}).update(
                {
                    "max": max(row[idx] for row in rows),
                    "mean": sum(row[idx] for row in rows) / frames,
                    "min": min(row[idx] for row in rows),
                }
            )

    # Optional grading on a chosen deviation column.
    candidates = None
    if args.lo is not None and args.hi is not None:
        if args.lo >= args.hi:
            errors.append("--lo must be smaller than --hi")
        else:
            col_idx = None
            if columns and args.col in columns:
                col_idx = columns.index(args.col)
            elif args.col == "max_devi_f" and ncols >= 2 and (
                ncols - 1
            ) % 9 == 0:
                col_idx = 4  # first model's max_devi_f
            if col_idx is None:
                warnings.append(
                    f"column {args.col!r} not found; skipping grading"
                )
            else:
                values = [row[col_idx] for row in rows]
                good = sum(1 for v in values if v < args.lo)
                decent = sum(
                    1 for v in values if args.lo <= v <= args.hi
                )
                poor = sum(1 for v in values if v > args.hi)
                candidates = {
                    "column": args.col,
                    "lo": args.lo,
                    "hi": args.hi,
                    "good": good,
                    "decent": decent,
                    "poor": poor,
                }

    if args.expected_frames is not None and frames != args.expected_frames:
        errors.append(
            f"frame count {frames} != expected {args.expected_frames}"
        )

    verdict = {
        "status": "pass" if not errors else "fail",
        "file": str(path),
        "frames": frames,
        "columns": columns,
        "step": step,
        "summary": summary,
        "candidates": candidates,
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(verdict, indent=2))
    print(
        f"check_model_devi: {verdict['status']} "
        f"({frames} frames, {ncols} columns)",
        file=sys.stderr,
    )
    return 0 if verdict["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
