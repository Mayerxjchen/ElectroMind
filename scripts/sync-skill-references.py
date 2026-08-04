"""W1: byte-level deterministic knowledge reference sync (A+ design).

Reconciles the committed runtime copies ``<skill>/references/knowledge/`` from
the canonical authoring source ``skills/knowledge/`` via an explicit TOML
mapping.  Copies are byte-identical to their source (no injected header);
source relationships live in the mapping + generated manifest, not in the
copies.

Usage:
    uv run scripts/sync-skill-references.py            # reconcile the tree
    uv run scripts/sync-skill-references.py --check    # read-only verification
    uv run scripts/sync-skill-references.py --root PATH [--map PATH]

``--check`` verifies, without modifying anything:
    1. every mapped source exists
    2. every mapped target exists
    3. source and target SHA-256 are equal (byte-identical copy)
    4. the mapping declares no duplicate/conflicting target
    5. no undeclared generated copies under any skill references/knowledge/
    6. no stale copies (manifest records whose mapping entry is gone, or
       whose recorded source disagrees with the mapping)

``sync`` (no flags) makes the tree match the mapping exactly: it copies every
mapped source to its targets, prunes anything under ``references/knowledge/``
that the mapping does not declare, and rewrites the manifest.  It validates
the whole mapping first and aborts before writing on any error.

All paths in the mapping are repo-root relative.  Exit codes: 0 = ok,
1 = verification/reconcile failure, 2 = usage error.

Design: docs/superpowers/specs/2026-08-04-skill-aplus-self-contained-design.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tomllib
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MANIFEST_NAME = "sync-manifest.json"
DEFAULT_MAP_REL = Path("skills/knowledge/sync-map.toml")
SKILL_DIRS = ("procedures", "tools")
CHUNK = 1 << 16

# P0-1: 路径约束 — source 只能位于作者事实源目录，target 只能位于各 skill 的
# committed runtime copy 目录。拒绝绝对路径、``..`` 与 symlink 穿越。
SOURCE_PREFIX = ("skills", "knowledge")
TARGET_PREFIX = ("skills", "procedures", "tools")
TARGET_SUFFIX = ("references", "knowledge")


class MapError(ValueError):
    """A mapping/manifest problem that aborts before any write."""


def _validate_rel_path(kind: str, value: str, where: str) -> str:
    """Validate one mapping path; returns the normalized form."""
    raw = value.strip()
    if not raw:
        raise MapError(f"{where}: {kind} must be a non-empty string")
    p = Path(raw)
    if p.is_absolute():
        raise MapError(f"{where}: {kind} must be repo-root relative, got {raw!r}")
    if ".." in p.parts:
        raise MapError(f"{where}: {kind} must not contain '..', got {raw!r}")
    if kind == "source":
        if p.parts[:2] != SOURCE_PREFIX or len(p.parts) != 3:
            raise MapError(
                f"{where}: source must be under skills/knowledge/<file>.md, got {raw!r}"
            )
    else:
        if len(p.parts) != 6:
            raise MapError(
                f"{where}: target must be "
                f"skills/{{procedures,tools}}/<skill>/references/knowledge/<file>, "
                f"got {raw!r}"
            )
        if p.parts[0] != "skills" or p.parts[1] not in SKILL_DIRS:
            raise MapError(
                f"{where}: target must start with "
                f"skills/{{procedures,tools}}/<skill>/, got {raw!r}"
            )
        if p.parts[3:5] != TARGET_SUFFIX:
            raise MapError(
                f"{where}: target must be "
                f"skills/{{procedures,tools}}/<skill>/references/knowledge/<file>, "
                f"got {raw!r}"
            )
    return raw


def _no_symlink_components(root: Path, rel: str, where: str) -> None:
    """Reject any symlink in the ancestry of ``root/rel`` (P0-1)."""
    cursor = root
    for part in Path(rel).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise MapError(f"{where}: symlink not allowed in path: {rel!r}")
        if cursor.exists() and not cursor.is_dir() and part != Path(rel).parts[-1]:
            raise MapError(f"{where}: not a directory: {rel!r}")


def load_map(path: Path) -> list[tuple[str, list[str]]]:
    """Parse the TOML mapping into ``(source, targets)`` entries.

    Raises :class:`MapError` on missing/malformed files, on duplicate or
    conflicting targets (check 4), and on any path that escapes the allowed
    directories (P0-1).
    """
    if not path.is_file():
        raise MapError(f"mapping file not found: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise MapError(f"invalid TOML in {path}: {exc}") from exc
    entries: list[tuple[str, list[str]]] = []
    seen: dict[str, str] = {}
    for i, ref in enumerate(data.get("references", []), start=1):
        where = f"references[{i}]"
        source = ref.get("source")
        targets = ref.get("targets")
        if not isinstance(source, str) or not source.strip():
            raise MapError(f"{where}: missing non-empty 'source'")
        if not isinstance(targets, list) or not targets:
            raise MapError(f"{where}: missing non-empty 'targets' list")
        src = _validate_rel_path("source", source, where)
        normalized: list[str] = []
        for t in targets:
            if not isinstance(t, str):
                raise MapError(f"{where}: target must be a string")
            norm = _validate_rel_path("target", t, where)
            if norm in seen:
                raise MapError(
                    f"conflicting target {norm!r}: declared by both "
                    f"{seen[norm]!r} and {src!r}"
                )
            seen[norm] = src
            normalized.append(norm)
        entries.append((src, normalized))
    return entries


def load_manifest(path: Path) -> dict[str, dict]:
    """Return the manifest entries (target → {source, sha256}); missing → {}."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MapError(f"invalid manifest JSON at {path}: {exc}") from exc
    entries = data.get("entries", {}) if isinstance(data, dict) else {}
    return {k: v for k, v in entries.items() if isinstance(v, dict)}


def write_manifest(path: Path, entries: dict[str, dict]) -> None:
    """Write the manifest deterministically (sorted keys, no timestamps)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "generated_by": "scripts/sync-skill-references.py",
        "entries": dict(sorted(entries.items())),
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# hashing + tree walking
# ---------------------------------------------------------------------------


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_copy(src: Path, dest: Path) -> None:
    """Byte-copy *src* to *dest* atomically (same-dir temp + os.replace).

    P0-1: readers never observe a partially-written copy, and a failed
    copy leaves no partial file behind.
    """
    import os
    import tempfile

    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=".sync-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out:
            with src.open("rb") as inp:
                shutil.copyfileobj(inp, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def skill_knowledge_dirs(root: Path) -> list[Path]:
    """All ``<skill>/references/knowledge/`` dirs under skills/{procedures,tools}."""
    dirs: list[Path] = []
    for kind in SKILL_DIRS:
        base = root / "skills" / kind
        if not base.is_dir():
            continue
        for skill_dir in sorted(base.iterdir()):
            kdir = skill_dir / "references" / "knowledge"
            if kdir.is_dir():
                dirs.append(kdir)
    return dirs


# ---------------------------------------------------------------------------
# --check (read-only)
# ---------------------------------------------------------------------------


def run_check(root: Path, map_path: Path, manifest_path: Path) -> list[str]:
    """Run all six verifications; return the list of errors ([] = pass)."""
    try:
        entries = load_map(map_path)
    except MapError as exc:
        return [str(exc)]
    manifest = load_manifest(manifest_path)
    mapped_targets = {t for _, targets in entries for t in targets}

    errors: list[str] = []
    for source, targets in entries:
        try:
            _no_symlink_components(root, source, f"source {source!r}")
            for target in targets:
                _no_symlink_components(root, target, f"target {target!r}")
        except MapError as exc:
            return [str(exc)]
        src = root / source
        if not src.is_file():
            errors.append(f"missing source: {source}")
            continue
        src_sha = sha256_of(src)
        for target in targets:
            tgt = root / target
            if not tgt.is_file():
                errors.append(f"missing target: {target}")
                continue
            if sha256_of(tgt) != src_sha:
                errors.append(f"SHA-256 mismatch: {target} differs from {source}")

    for kdir in skill_knowledge_dirs(root):
        for f in sorted(kdir.iterdir()):
            if not f.is_file():
                continue
            rel = str(f.relative_to(root))
            if rel in mapped_targets:
                if rel not in manifest:
                    errors.append(f"target not recorded in manifest: {rel}")
            elif rel not in manifest:
                errors.append(f"undeclared copy: {rel}")

    source_by_target = {t: s for s, targets in entries for t in targets}
    for target, record in sorted(manifest.items()):
        if target not in mapped_targets:
            errors.append(f"stale copy: {target} (no longer in the mapping)")
        elif record.get("source") != source_by_target[target]:
            errors.append(
                f"stale manifest: {target} recorded from "
                f"{record.get('source')!r}, mapping now says "
                f"{source_by_target[target]!r}"
            )
    return errors


# ---------------------------------------------------------------------------
# sync (reconcile)
# ---------------------------------------------------------------------------


def run_sync(root: Path, map_path: Path, manifest_path: Path) -> tuple[int, int, int]:
    """Make the tree match the mapping; return (copied, pruned, recorded).

    Validates the mapping and every source before any write, so a failing
    sync leaves the tree untouched.
    """
    entries = load_map(map_path)  # raises MapError on conflicts
    for source, targets in entries:
        if not (root / source).is_file():
            raise MapError(f"missing source: {source}")
        _no_symlink_components(root, source, f"source {source!r}")
        for target in targets:
            _no_symlink_components(root, target, f"target {target!r}")
    mapped_targets = {t for _, targets in entries for t in targets}

    copied = 0
    for source, targets in entries:
        src = root / source
        src_sha = sha256_of(src)
        for target in targets:
            tgt = root / target
            if not tgt.is_file() or sha256_of(tgt) != src_sha:
                _atomic_copy(src, tgt)
                copied += 1

    pruned = 0
    for kdir in skill_knowledge_dirs(root):
        for f in sorted(kdir.rglob("*")):
            if f.is_file() and str(f.relative_to(root)) not in mapped_targets:
                f.unlink()
                pruned += 1
        for d in sorted(
            (p for p in kdir.rglob("*") if p.is_dir()),
            key=lambda p: len(p.parts),
            reverse=True,
        ):
            try:
                d.rmdir()
            except OSError:
                pass

    recorded = 0
    new_manifest: dict[str, dict] = {}
    for source, targets in entries:
        src_sha = sha256_of(root / source)
        for target in targets:
            new_manifest[target] = {"source": source, "sha256": src_sha}
            recorded += 1
    write_manifest(manifest_path, new_manifest)
    return copied, pruned, recorded


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sync-skill-references",
        description=(
            "Reconcile skill references/knowledge/ copies from "
            "skills/knowledge/ (A+ self-contained skills)."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify only; never modifies the work tree",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="repo root (default: parent of scripts/)",
    )
    parser.add_argument(
        "--map",
        type=Path,
        default=None,
        help="mapping TOML (default: <root>/skills/knowledge/sync-map.toml)",
    )
    args = parser.parse_args(argv)

    root = (args.root or SCRIPT_DIR.parent).resolve()
    map_path = args.map or (root / DEFAULT_MAP_REL)
    if not map_path.is_absolute():
        map_path = (root / map_path).resolve()
    manifest_path = map_path.parent / MANIFEST_NAME

    if args.check:
        errors = run_check(root, map_path, manifest_path)
        if errors:
            for e in errors:
                print(f"check: {e}", file=sys.stderr)
            return 1
        print("sync-skill-references: check passed")
        return 0

    try:
        copied, pruned, recorded = run_sync(root, map_path, manifest_path)
    except MapError as exc:
        print(f"sync-skill-references: {exc}", file=sys.stderr)
        return 1
    print(
        f"sync-skill-references: copied {copied}, pruned {pruned}, "
        f"recorded {recorded} in {manifest_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
