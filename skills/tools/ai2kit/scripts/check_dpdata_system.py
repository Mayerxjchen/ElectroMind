#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Validate a dpdata System directory: frames, natoms, type_map, coord/box/energy/force/virial, NaN/Inf, shape consistency.

Reads the deepmd/npy layout (type.raw, type_map.raw, set.NNN/*.{npy,raw}).
Uses numpy when importable and falls back to a pure-stdlib .npy/.raw reader,
so the check always runs. Optional --expected-frames and --expected-type-map
pin the dataset against a declared contract.

Prints JSON; exit 0 on pass, 1 on fail.

Example:
    python scripts/check_dpdata_system.py --system ./init-data \
        --expected-frames 200 --expected-type-map H,O
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


def _accumulate(value, state):
    nonfinite, vmin, vmax = state
    if not math.isfinite(value):
        nonfinite += 1
    if vmin is None or value < vmin:
        vmin = value
    if vmax is None or value > vmax:
        vmax = value
    return (nonfinite, vmin, vmax)


def read_npy_stdlib(path: Path) -> dict:
    """Minimal .npy reader (no numpy): returns shape/kind/nonfinite/min/max."""
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
    vmin = None
    vmax = None
    chunk = 1 << 20
    for start in range(0, total, chunk):
        count = min(chunk, total - start)
        step_fmt = "<%d%s" % (count, code)
        for value in struct.unpack_from(step_fmt, payload, start * itemsize):
            nonfinite, vmin, vmax = _accumulate(
                value, (nonfinite, vmin, vmax)
            )
    return {
        "shape": shape,
        "kind": kind,
        "nonfinite": nonfinite,
        "min": vmin,
        "max": vmax,
    }


def read_npy_numpy(path: Path) -> dict:
    arr = NUMPY.load(path, mmap_mode="r")
    shape = tuple(arr.shape)
    if arr.dtype.kind in "fiub":
        nonfinite = int(NUMPY.count_nonzero(~NUMPY.isfinite(arr)))
        return {
            "shape": shape,
            "kind": arr.dtype.kind,
            "nonfinite": nonfinite,
            "min": float(arr.min()),
            "max": float(arr.max()),
        }
    raise ValueError(f"unsupported dtype {arr.dtype!r}")


def read_raw(path: Path) -> dict:
    """Text .raw layout: one frame per line, flattened values."""
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
    nonfinite = 0
    vmin = None
    vmax = None
    for row in rows:
        for value in row:
            nonfinite, vmin, vmax = _accumulate(value, (nonfinite, vmin, vmax))
    return {
        "shape": (len(rows), ncols),
        "kind": "f",
        "nonfinite": nonfinite,
        "min": vmin,
        "max": vmax,
    }


def load_array(
    path: Path, mode: str, errors: list[str], warnings: list[str]
) -> dict | None:
    """Read an array, folding flat .raw rows into a logical shape.

    .npy files carry their real shape; .raw files store one frame per line
    with flattened values. Modes:
      "n3"   coord/force:  natoms*3 values per frame -> (frames, natoms, 3)
      "33"   box/virial:   9 values per frame        -> (frames, 3, 3)
      "flat" energy:       1 value per frame         -> (frames, 1)
    """
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
    if path.suffix == ".raw" and info["shape"] and len(info["shape"]) == 2:
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
        else:  # flat
            info["shape"] = (nrows, ncols)
    return info


def first_existing(directory: Path, names: list[str]) -> Path | None:
    for name in names:
        path = directory / name
        if path.exists():
            return path
    return None


def _frame_count(info: dict | None) -> int | None:
    if not info or not info["shape"]:
        return None
    return int(info["shape"][0])


def _check_frames_consistent(name: str, frames: int, info: dict, errors: list) -> None:
    if len(info["shape"]) >= 1 and _frame_count(info) != frames:
        errors.append(f"{name} frame count {_frame_count(info)} != coord frames {frames}")


def parse_system(root: Path, errors: list[str], warnings: list[str]) -> dict:
    type_raw = root / "type.raw"
    type_map_raw = root / "type_map.raw"

    if not type_raw.exists():
        errors.append("missing type.raw")
    if not type_map_raw.exists():
        errors.append("missing type_map.raw")

    type_map: list[str] = []
    if type_map_raw.exists():
        type_map = [
            line.strip()
            for line in type_map_raw.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    natoms: int | None = None
    if type_raw.exists():
        try:
            type_idx = [
                int(x) for x in type_raw.read_text(encoding="utf-8").split()
            ]
            natoms = len(type_idx)
            if type_idx and type_map:
                if max(type_idx) >= len(type_map):
                    errors.append("type.raw contains an index out of type_map range")
            elif not type_map:
                warnings.append("type_map.raw absent; element symbols unknown")
        except ValueError as exc:
            errors.append(f"type.raw not a list of integers: {exc}")

    sets = sorted(
        p for p in root.iterdir() if p.is_dir() and p.name.startswith("set.")
    )
    if not sets:
        errors.append("no set.NNN directories found")

    total_frames = 0
    sets_out: dict[str, dict] = {}
    stats: dict[str, dict] = {}
    for s in sets:
        set_name = s.name
        coord_path = first_existing(s, ["coord.npy", "coord.raw"])
        if coord_path is None:
            errors.append(f"{set_name}: missing coord.npy/coord.raw")
            continue
        coord = load_array(coord_path, "n3", errors, warnings)
        if coord is None:
            continue
        frames = _frame_count(coord)
        if frames is None or len(coord["shape"]) != 3 or coord["shape"][2] != 3:
            errors.append(
                f"{set_name}: coord shape {coord['shape']} is not (frames, natoms, 3)"
            )
            continue
        if natoms is not None and coord["shape"][1] != natoms:
            errors.append(
                f"{set_name}: coord natoms {coord['shape'][1]} != type.raw length {natoms}"
            )
        set_info = {"frames": frames}
        stat_key = f"{set_name}/coord"
        stats[stat_key] = {
            "min": coord["min"],
            "max": coord["max"],
            "nonfinite": coord["nonfinite"],
        }
        if coord["nonfinite"]:
            errors.append(f"{set_name}: coord contains NaN/Inf")

        box_path = first_existing(s, ["box.npy", "box.raw"])
        if box_path:
            box = load_array(box_path, "33", errors, warnings)
            if box is not None:
                shape = box["shape"]
                if shape not in [(frames, 3, 3), (3, 3), (frames, 9)]:
                    errors.append(
                        f"{set_name}: box shape {shape} is not (N,3,3)/(3,3)/(N,9)"
                    )
                if box["nonfinite"]:
                    errors.append(f"{set_name}: box contains NaN/Inf")
                stats[f"{set_name}/box"] = {
                    "min": box["min"],
                    "max": box["max"],
                    "nonfinite": box["nonfinite"],
                }
                set_info["box"] = True
        else:
            warnings.append(f"{set_name}: no box; system is implicit")

        energy_path = first_existing(s, ["energy.npy", "energy.raw"])
        if energy_path:
            energy = load_array(energy_path, "flat", errors, warnings)
            if energy is not None:
                if energy["shape"] not in [(frames,), (frames, 1)]:
                    errors.append(
                        f"{set_name}: energy shape {energy['shape']} is not (N,)/(N,1)"
                    )
                if energy["nonfinite"]:
                    errors.append(f"{set_name}: energy contains NaN/Inf")
                stats[f"{set_name}/energy"] = {
                    "min": energy["min"],
                    "max": energy["max"],
                    "nonfinite": energy["nonfinite"],
                }
                set_info["energy"] = True
        else:
            set_info["energy"] = False

        force_path = first_existing(s, ["force.npy", "force.raw"])
        if force_path:
            force = load_array(force_path, "n3", errors, warnings)
            if force is not None:
                if len(force["shape"]) != 3 or force["shape"][2] != 3:
                    errors.append(
                        f"{set_name}: force shape {force['shape']} is not (N,natoms,3)"
                    )
                elif natoms is not None and force["shape"][1] != natoms:
                    errors.append(
                        f"{set_name}: force natoms {force['shape'][1]} != type.raw length {natoms}"
                    )
                if force["nonfinite"]:
                    errors.append(f"{set_name}: force contains NaN/Inf")
                stats[f"{set_name}/force"] = {
                    "min": force["min"],
                    "max": force["max"],
                    "nonfinite": force["nonfinite"],
                }
                set_info["force"] = True
        else:
            set_info["force"] = False

        virial_path = first_existing(s, ["virial.npy", "virial.raw"])
        if virial_path:
            virial = load_array(virial_path, "33", errors, warnings)
            if virial is not None:
                if virial["shape"] not in [(frames, 9), (frames, 3, 3), (3, 3)]:
                    errors.append(
                        f"{set_name}: virial shape {virial['shape']} is not (N,9)/(N,3,3)/(3,3)"
                    )
                if virial["nonfinite"]:
                    errors.append(f"{set_name}: virial contains NaN/Inf")
                stats[f"{set_name}/virial"] = {
                    "min": virial["min"],
                    "max": virial["max"],
                    "nonfinite": virial["nonfinite"],
                }
                set_info["virial"] = True
        else:
            set_info["virial"] = False

        sets_out[set_name] = set_info
        total_frames += frames

    return {
        "frames": total_frames,
        "natoms": natoms,
        "type_map": type_map,
        "sets": sets_out,
        "stats": stats,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system", required=True, help="dpdata System directory")
    parser.add_argument(
        "--expected-frames", type=int, default=None, help="declared total frame count"
    )
    parser.add_argument(
        "--expected-type-map",
        default=None,
        help="declared element order, comma separated, e.g. H,O",
    )
    args = parser.parse_args()

    root = Path(args.system).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    if not root.is_dir():
        print(json.dumps({
            "status": "fail",
            "system": str(root),
            "errors": [f"{root}: not a directory"],
            "warnings": [],
        }, indent=2))
        return 1

    result = parse_system(root, errors, warnings)
    expected = {}
    if args.expected_frames is not None:
        expected["frames"] = args.expected_frames
        if result["frames"] != args.expected_frames:
            errors.append(
                f"frame count {result['frames']} != expected {args.expected_frames}"
            )
    if args.expected_type_map is not None:
        expected["type_map"] = [e.strip() for e in args.expected_type_map.split(",")]
        if result["type_map"] != expected["type_map"]:
            errors.append(
                f"type_map {result['type_map']} != expected {expected['type_map']}"
            )

    verdict = {
        "status": "pass" if not errors else "fail",
        "system": str(root),
        "frames": result["frames"],
        "natoms": result["natoms"],
        "type_map": result["type_map"],
        "sets": result["sets"],
        "stats": result["stats"],
        "expected": expected,
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(verdict, indent=2))
    print(
        f"check_dpdata_system: {verdict['status']} "
        f"({result['frames']} frames, {result['natoms']} atoms)",
        file=sys.stderr,
    )
    return 0 if verdict["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
