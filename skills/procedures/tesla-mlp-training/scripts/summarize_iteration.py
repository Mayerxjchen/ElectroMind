#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Summarize one iteration: lcurve, model deviation statistics, label counts.

Locates files by convention when --iteration is given:
  lcurve        <iteration>/01_train/lcurve.out
  model_devi    <iteration>/02_explore/**/model_devi.out (one entry per file)
  label dataset <iteration>/05_update (dpdata directory)

or accept explicit paths with --lcurve/--model-devi/--label-dataset.
Pure stdlib; prints JSON. Exit 0 even when a convention file is absent
(recorded as null); exit 1 when an explicitly given path cannot be read.

Example:
    python scripts/summarize_iteration.py --workdir ./water64/20-workdir --iteration iter-1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def summarize_lcurve(path: Path, errors: list[str]) -> dict | None:
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                tokens = line.split()
                try:
                    values = [float(t) for t in tokens]
                except ValueError:
                    continue
                if len(values) >= 4:
                    rows.append(values)
    except OSError as exc:
        errors.append(f"lcurve unreadable: {path}: {exc}")
        return None
    if not rows:
        errors.append(f"lcurve has no parseable rows: {path}")
        return None
    final = rows[-1]
    val_losses = [r[3] for r in rows]
    return {
        "file": str(path),
        "rows": len(rows),
        "final_step": final[0],
        "final_train_loss": final[2],
        "final_val_loss": final[3],
        "min_val_loss": min(val_losses),
        "min_val_loss_step": rows[val_losses.index(min(val_losses))][0],
    }


def summarize_model_devi(path: Path, errors: list[str]) -> dict | None:
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                tokens = line.split()
                try:
                    values = [float(t) for t in tokens]
                except ValueError:
                    continue
                rows.append(values)
    except OSError as exc:
        errors.append(f"model_devi unreadable: {path}: {exc}")
        return None
    if not rows:
        errors.append(f"model_devi has no data rows: {path}")
        return None
    ncols = len(rows[0])
    if ncols >= 5:  # positional: step, v*, f(max,avg,...), ...
        max_devi_f = [r[4] for r in rows]
        avg_devi_f = [r[5] for r in rows]
        summary = {
            "frames": len(rows),
            "columns": ncols,
            "max_devi_f": {
                "max": max(max_devi_f),
                "mean": sum(max_devi_f) / len(max_devi_f),
            },
            "avg_devi_f": {
                "mean": sum(avg_devi_f) / len(avg_devi_f),
            },
        }
    else:
        summary = {"frames": len(rows), "columns": ncols}
    return {"file": str(path), **summary}


def summarize_labels(dataset: Path, errors: list[str]) -> dict | None:
    if not dataset.is_dir():
        return None
    type_raw = dataset / "type.raw"
    natoms = None
    if type_raw.is_file():
        try:
            natoms = len([int(x) for x in type_raw.read_text(encoding="utf-8").split()])
        except ValueError:
            pass
    frames = 0
    labels = {"energy": False, "force": False, "virial": False}
    for s in sorted(
        p for p in dataset.iterdir() if p.is_dir() and p.name.startswith("set.")
    ):
        coord = s / "coord.npy"
        coord_raw = s / "coord.raw"
        if coord.is_file() or coord_raw.is_file():
            try:
                if coord.is_file():
                    import struct

                    with open(coord, "rb") as fh:
                        fh.read(6)
                        fh.read(2)
                        (header_len,) = struct.unpack("<H", fh.read(2))
                        header = fh.read(header_len).decode("ascii")
                    import ast

                    frames += int(ast.literal_eval(header)["shape"][0])
                else:
                    frames += sum(
                        1 for _ in coord_raw.open(encoding="utf-8") if _.strip()
                    )
            except Exception:
                pass
        for label, names in (
            ("energy", ("energy.npy", "energy.raw")),
            ("force", ("force.npy", "force.raw")),
            ("virial", ("virial.npy", "virial.raw")),
        ):
            if any((s / name).is_file() for name in names):
                labels[label] = True
    return {
        "dataset": str(dataset),
        "frames": frames,
        "natoms": natoms,
        "labels": labels,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", default="20-workdir")
    parser.add_argument("--iteration", default=None)
    parser.add_argument("--lcurve", default=None, help="explicit lcurve.out path")
    parser.add_argument(
        "--model-devi", action="append", default=[], help="explicit model_devi.out path"
    )
    parser.add_argument("--label-dataset", default=None, help="explicit dpdata directory")
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []

    iteration_dir = None
    if args.iteration:
        candidate = Path(args.iteration)
        if not candidate.is_dir():
            candidate = Path(args.workdir) / args.iteration
        if candidate.is_dir():
            iteration_dir = candidate.resolve()
        else:
            errors.append(f"iteration {args.iteration!r} not found")

    lcurve = None
    if args.lcurve:
        lcurve = summarize_lcurve(Path(args.lcurve), errors)
    elif iteration_dir is not None:
        path = iteration_dir / "01_train" / "lcurve.out"
        if path.is_file():
            lcurve = summarize_lcurve(path, errors)

    model_devi = []
    if args.model_devi:
        for spec in args.model_devi:
            entry = summarize_model_devi(Path(spec), errors)
            if entry:
                model_devi.append(entry)
    elif iteration_dir is not None:
        explore = iteration_dir / "02_explore"
        if explore.is_dir():
            for path in sorted(explore.rglob("model_devi.out")):
                entry = summarize_model_devi(path, errors)
                if entry:
                    model_devi.append(entry)

    labels = None
    if args.label_dataset:
        labels = summarize_labels(Path(args.label_dataset), errors)
    elif iteration_dir is not None:
        labels = summarize_labels(iteration_dir / "05_update", errors)

    verdict = {
        "iteration": str(iteration_dir) if iteration_dir else None,
        "lcurve": lcurve,
        "model_devi": model_devi or None,
        "labels": labels,
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(verdict, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
