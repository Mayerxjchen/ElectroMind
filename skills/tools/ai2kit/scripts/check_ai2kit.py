#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Check an ai2-kit installation: binary, import, version, required subcommands, and optional features.

Prints a single JSON verdict with "status" one of "passed" (everything works),
"degraded" (installed but something is missing), or "missing" (ai2-kit not
installed at all). A missing installation exits 0 — that is a valid, reportable
state — while a degraded one exits 1 so it does not slip past silently.

Features reported: "ase" and "dpdata" (importable in the probed interpreter)
and "model_devi" (the model-deviation subcommand available).

Example:
    python scripts/check_ai2kit.py --python /path/to/venv/bin/python
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

DEFAULT_SUBCOMMANDS = ["tool", "tool dpdata", "tool ase", "tool model_devi"]


def run(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    """Run a command; returns (returncode, stdout, stderr) without raising."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError:
        return 127, "", "executable not found"
    except subprocess.TimeoutExpired:
        return 124, "", "timed out"


def probe_version(binary: str) -> str:
    """Best-effort version string from the CLI or module metadata."""
    for flag in ("--version", "version"):
        code, out, err = run([binary, flag])
        if code == 0:
            text = (out + err).strip()
            match = re.search(r"\d+\.\d+(?:\.\d+)?", text)
            return match.group(0) if match else "unknown"
    return ""


def probe_module_version(python: str) -> str:
    code, out, err = run(
        [
            python,
            "-c",
            "from importlib.metadata import version; print(version('ai2-kit'))",
        ]
    )
    if code == 0:
        text = (out + err).strip()
        return text if re.fullmatch(r"\d+(?:\.\d+)*", text) else "unknown"
    return ""


def probe_subcommand(binary: str, name: str) -> bool:
    code, _, _ = run([binary] + name.split() + ["--help"])
    return code == 0


def probe_import(python: str, module: str) -> bool:
    code, _, _ = run([python, "-c", f"import {module}"])
    return code == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="interpreter used for import/version probes "
        "(default: the interpreter running this script)",
    )
    parser.add_argument(
        "--bin",
        default=None,
        help="explicit path to the ai2-kit executable "
        "(default: resolved from PATH)",
    )
    parser.add_argument(
        "--subcommand",
        action="append",
        dest="subcommands",
        metavar="NAME",
        help="required subcommand, e.g. 'tool dpdata' "
        f"(repeatable; default: {' '.join(DEFAULT_SUBCOMMANDS)})",
    )
    parser.add_argument(
        "--no-import",
        action="store_true",
        help="skip Python import probes (useful when only the CLI is present)",
    )
    args = parser.parse_args()

    binary = args.bin or shutil.which("ai2-kit")
    if args.bin and not (binary and os.path.isfile(binary)):
        binary = None
    subcommands = args.subcommands or list(DEFAULT_SUBCOMMANDS)

    errors: list[str] = []
    warnings: list[str] = []

    version = ""
    if binary:
        version = probe_version(binary)
        if not version:
            warnings.append("ai2-kit binary found but version could not be determined")
    elif not args.no_import:
        version = probe_module_version(args.python)

    module_ok = probe_import(args.python, "ai2_kit") if not args.no_import else False
    if binary and not module_ok:
        warnings.append(
            "ai2-kit CLI found but the ai2_kit module is not importable with "
            f"{args.python}; pass --python pointing at the right environment"
        )

    found = {}
    if binary:
        for name in subcommands:
            found[name] = probe_subcommand(binary, name)
    missing_subcommands = [
        name for name, ok in found.items() if not ok
    ]
    if missing_subcommands:
        warnings.append(
            "required subcommands not found: " + ", ".join(missing_subcommands)
        )

    features = {
        "ase": probe_import(args.python, "ase") if not args.no_import else False,
        "dpdata": probe_import(args.python, "dpdata") if not args.no_import else False,
        "model_devi": any("model_devi" in name for name, ok in found.items() if ok),
    }
    if not args.no_import:
        features["model_devi"] = features["model_devi"] or probe_import(
            args.python, "ai2_kit.tool.model_devi"
        )
    missing_features = [k for k, v in features.items() if not v]
    if missing_features:
        warnings.append("optional features missing: " + ", ".join(missing_features))

    if not binary and not module_ok:
        status = "missing"
        if missing_features:
            warnings.append("dependency probes failed because ai2-kit is absent")
    elif not binary:
        status = "degraded"
        warnings.append("ai2-kit module importable but CLI executable not found on PATH")
    elif missing_subcommands or missing_features or not version:
        status = "degraded"
    else:
        status = "passed"

    verdict = {
        "status": status,
        "version": version or None,
        "binary": binary,
        "interpreter": args.python,
        "features": features,
        "subcommands": found,
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(verdict, indent=2))
    print(
        f"check_ai2kit: {status}"
        + (f" (version {version})" if version else ""),
        file=sys.stderr,
    )
    return 0 if status != "degraded" else 1


if __name__ == "__main__":
    sys.exit(main())
