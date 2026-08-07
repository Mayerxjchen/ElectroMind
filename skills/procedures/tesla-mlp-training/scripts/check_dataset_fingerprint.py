#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Check a dpdata System directory against a declared dataset fingerprint.

The fingerprint captures the dataset identity: frames, natoms, type_map,
and which labels (energy/force/virial) are present. Two datasets with the
same fingerprint are interchangeable for training; any change in those
fields changes the fingerprint (one dataset = one method fingerprint).

Expected fingerprint is given as a JSON file of the form
{"method": "...", "frames": N, "natoms": N, "type_map": [...],
 "labels": {"energy": bool, "force": bool, "virial": bool}}
or via --expected-frames/--expected-type-map/--expected-natoms/
--expected-labels. NaN/Inf are always checked.

Uses numpy when importable; falls back to a pure-stdlib .npy/.raw reader.
Prints JSON; exit 0 on pass, 1 on fail.

Example:
    python scripts/check_dataset_fingerprint.py --system ./20-workdir/iter-1/05_update \
        --expected-fingerprint ./fingerprint.json
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import struct
import sys
from pathlib import Path

try:  # optional fast path; the stdlib reader covers the rest
    import numpy as _np

    NUMPY = _np
except Exception:
    NUMPY = None

_NPY_DTYPES = {
    "f4": ("f", 4),
    "f8": ("f", 8),
    "i1": ("i", 1),
    "i2": ("i", 2),
    "i4": ("i", 4),
    "i8": ("i", 8),
    "u1": ("u", 1),
    "u2": ("u", 2),
    "u4": ("u", 4),
    "u8": ("u", 8),
    "b1": ("b", 1),
}
_NPY_STRUCT = {
    ("f", 4): "f",
    ("f", 8): "d",
    ("i", 1): "b",
    ("i", 2): "h",
    ("i", 4): "i",
    ("i", 8): "q",
    ("u", 1): "B",
    ("u", 2): "H",
    ("u", 4): "I",
    ("u", 8): "Q",
    ("b", 1): "?",
}


def read_npy_stdlib(path: Path) -> dict:
    with open(path, "rb") as fh:
        magic = fh.read(6)
        if magic != b"\x93NUMPY":
            raise ValueError("not a numpy .npy file")
        version = fh.read(2)
        if not version or version[0] not in (1, 2):
            raise ValueError(f"unsupported .npy version {version!r}")
        if version[0] == 1:
            (header_len,) = struct.unpack("<H", fh.read(2))
        else:
            (header_len,) = struct.unpack("<I", fh.read(4))
        header = fh.read(header_len).decode("ascii")
        payload = fh.read()
    meta = ast.literal_eval(header)
    descr = str(meta["descr"])
    shape = tuple(int(s) for s in meta["shape"])
    while descr and descr[0] in "<>=|":
        descr = descr[1:]
    if descr not in _NPY_DTYPES:
        raise ValueError(f"unsupported dtype {descr!r}")
    kind, itemsize = _NPY_DTYPES[descr]
    code = _NPY_STRUCT[(kind, itemsize)]
    total = 1
    for dim in shape:
        total *= dim
    nonfinite = 0
    chunk = 1 << 20
    for start in range(0, total, chunk):
        count = min(chunk, total - start)
        for value in struct.unpack_from("<%d%s" % (count, code), payload, start * itemsize):
            if not math.isfinite(value):
                nonfinite += 1
    return {"shape": shape, "kind": kind, "nonfinite": nonfinite}


def read_npy_numpy(path: Path) -> dict:
    arr = NUMPY.load(path, mmap_mode="r")
    if arr.dtype.kind in "fiub":
        nonfinite = int(NUMPY.count_nonzero(~NUMPY.isfinite(arr)))
        return {"shape": tuple(arr.shape), "kind": arr.dtype.kind, "nonfinite": nonfinite}
    raise ValueError(f"unsupported dtype {arr.dtype!r}")


def read_raw(path: Path) -> dict:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append([float(x) for x in line.split()])
    if not rows:
        raise ValueError("empty .raw file")
    ncols = len(rows[0])
    for row in rows:
        if len(row) != ncols:
            raise ValueError("ragged .raw file")
    nonfinite = sum(
        1 for row in rows for value in row if not math.isfinite(value)
    )
    return {"shape": (len(rows), ncols), "kind": "f", "nonfinite": nonfinite}


def load_array(path: Path, mode: str, errors: list[str]) -> dict | None:
    """Read an array; .raw rows are folded per mode (n3/33/flat)."""
    if path.suffix == ".npy":
        reader = read_npy_numpy if NUMPY is not None else read_npy_stdlib
    elif path.suffix == ".raw":
        reader = read_raw
    else:
        errors.append(f"{path}: unsupported data file")
        return None
    try:
        info = reader(path)
    except Exception as exc:
        errors.append(f"{path}: cannot read: {exc}")
        return None
    if path.suffix == ".raw" and len(info["shape"]) == 2:
        nrows, ncols = info["shape"]
        if mode == "n3":
            if ncols % 3 != 0:
                errors.append(f"{path}: {ncols} columns is not a multiple of 3")
                return None
            info["shape"] = (nrows, ncols // 3, 3)
        elif mode == "33":
            if ncols != 9:
                errors.append(f"{path}: expected 9 columns per frame, got {ncols}")
                return None
            info["shape"] = (nrows, 3, 3)
        else:
            info["shape"] = (nrows, ncols)
    return info


def first_existing(directory: Path, names: list[str]) -> Path | None:
    for name in names:
        path = directory / name
        if path.exists():
            return path
    return None


def compute_fingerprint(root: Path, errors: list[str]) -> dict:
    type_raw = root / "type.raw"
    type_map_raw = root / "type_map.raw"
    natoms: int | None = None
    if type_raw.exists():
        try:
            natoms = len([int(x) for x in type_raw.read_text(encoding="utf-8").split()])
        except ValueError as exc:
            errors.append(f"type.raw not a list of integers: {exc}")
    else:
        errors.append("missing type.raw")
    type_map: list[str] = []
    if type_map_raw.exists():
        type_map = [
            line.strip()
            for line in type_map_raw.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    else:
        errors.append("missing type_map.raw")

    sets = sorted(
        p for p in root.iterdir() if p.is_dir() and p.name.startswith("set.")
    )
    if not sets:
        errors.append("no set.NNN directories found")
    total_frames = 0
    labels = {"energy": False, "force": False, "virial": False}
    for s in sets:
        coord_path = first_existing(s, ["coord.npy", "coord.raw"])
        if coord_path is None:
            errors.append(f"{s.name}: missing coord")
            continue
        coord = load_array(coord_path, "n3", errors)
        if coord is None:
            continue
        if len(coord["shape"]) != 3 or coord["shape"][2] != 3:
            errors.append(f"{s.name}: coord shape {coord['shape']} is not (frames, natoms, 3)")
            continue
        frames = int(coord["shape"][0])
        if natoms is not None and coord["shape"][1] != natoms:
            errors.append(
                f"{s.name}: coord natoms {coord['shape'][1]} != type.raw length {natoms}"
            )
        if coord["nonfinite"]:
            errors.append(f"{s.name}: coord contains NaN/Inf")
        total_frames += frames
        for label, names in (
            ("energy", ["energy.npy", "energy.raw"]),
            ("force", ["force.npy", "force.raw"]),
            ("virial", ["virial.npy", "virial.raw"]),
        ):
            path = first_existing(s, names)
            if path:
                info = load_array(path, "flat" if label == "energy" else "33", errors)
                if info is None:
                    continue
                if info["nonfinite"]:
                    errors.append(f"{s.name}: {label} contains NaN/Inf")
                labels[label] = True

    return {
        "frames": total_frames,
        "natoms": natoms,
        "type_map": type_map,
        "labels": labels,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system", required=True, help="dpdata System directory")
    parser.add_argument(
        "--expected-fingerprint",
        default=None,
        help="JSON file with the declared fingerprint (see docstring)",
    )
    parser.add_argument("--expected-frames", type=int, default=None)
    parser.add_argument("--expected-natoms", type=int, default=None)
    parser.add_argument("--expected-type-map", default=None, help="comma separated, e.g. H,O")
    parser.add_argument(
        "--expected-labels",
        default=None,
        help="comma separated, e.g. energy,force",
    )
    args = parser.parse_args()

    root = Path(args.system).resolve()
    errors: list[str] = []
    if not root.is_dir():
        print(json.dumps({
            "status": "fail",
            "system": str(root),
            "errors": [f"{root}: not a directory"],
            "warnings": [],
        }, indent=2))
        return 1

    computed = compute_fingerprint(root, errors)
    expected: dict = {}
    if args.expected_fingerprint:
        fp_path = Path(args.expected_fingerprint)
        if not fp_path.is_file():
            errors.append(f"expected fingerprint file missing: {fp_path}")
        else:
            try:
                expected = json.loads(fp_path.read_text(encoding="utf-8"))
            except Exception as exc:
                errors.append(f"expected fingerprint unreadable: {exc}")
    else:
        if args.expected_frames is not None:
            expected["frames"] = args.expected_frames
        if args.expected_natoms is not None:
            expected["natoms"] = args.expected_natoms
        if args.expected_type_map is not None:
            expected["type_map"] = [
                e.strip() for e in args.expected_type_map.split(",")
            ]
        if args.expected_labels is not None:
            expected["labels"] = {
                label.strip(): True
                for label in args.expected_labels.split(",")
                if label.strip()
            }

    matches: dict = {}
    for key in ("frames", "natoms", "type_map"):
        if key in expected:
            matches[key] = computed.get(key) == expected[key]
            if not matches[key]:
                errors.append(
                    f"{key} {computed.get(key)} != expected {expected[key]}"
                )
    if "labels" in expected:
        matches["labels"] = True
        for label, required in expected["labels"].items():
            present = bool(computed.get("labels", {}).get(label))
            if required and not present:
                matches["labels"] = False
                errors.append(f"label {label!r} required but missing")
    if not expected:
        errors.append("no expected fingerprint provided "
                      "(--expected-fingerprint or --expected-* flags)")

    verdict = {
        "status": "pass" if not errors else "fail",
        "system": str(root),
        "computed": computed,
        "expected": expected,
        "matches": matches,
        "errors": errors,
        "warnings": [],
    }
    print(json.dumps(verdict, indent=2))
    print(
        f"check_dataset_fingerprint: {verdict['status']} "
        f"({computed['frames']} frames, {computed['natoms']} atoms)",
        file=sys.stderr,
    )
    return 0 if verdict["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
