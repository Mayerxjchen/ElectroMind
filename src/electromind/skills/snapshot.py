"""Immutable Skill snapshots with content-addressed hashing.

``SkillSnapshot`` captures the frozen content of a single Skill at discovery
time — instructions, resources with per-file hashes, and a composite SHA-256.

``SkillSetSnapshot`` captures the entire catalog at a point in time with a
generation counter and content-addressed digest.  Two ``SkillSetSnapshot``
instances with the same digest are guaranteed to represent identical content,
regardless of filesystem mtimes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .discovery import SkillCatalogSnapshot, SkillDiagnostic


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SkillResource:
    """A single file resource within a Skill directory.

    Attributes:
        relative_path: Path relative to the Skill root (e.g. ``references/slurm.md``).
        sha256: Hex-encoded SHA-256 of the file content.
        size: File size in bytes.
    """

    relative_path: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class SkillSnapshot:
    """An immutable point-in-time capture of a single Skill.

    Once built, ``instructions`` and ``resources`` will never change — even if
    the source files are modified on disk.  ``use_skill`` reads from this snapshot
    rather than re-reading the source ``SKILL.md``.

    Attributes:
        name: Skill name (from frontmatter or directory name).
        description: Human-readable one-liner.
        kind: ``"procedure"``, ``"tool"``, or ``"standard"``.
        source_id: Stable source identifier (e.g. ``"project-skills"``).
        source_root: Absolute path to the source root on the host filesystem.
        relative_root: Path from source_root to the skill directory.
        instructions: Full body of ``SKILL.md`` (after frontmatter).
        resources: Frozen tuple of resource files with individual hashes.
        sha256: Composite hash of instructions + all resource metadata.
    """

    name: str
    description: str
    kind: str
    source_id: str
    source_root: Path
    relative_root: str
    instructions: str
    resources: tuple[SkillResource, ...]
    sha256: str
    skill_md_sha256: str = ""  # SHA-256 of the full SKILL.md file on disk


@dataclass(frozen=True, slots=True)
class SkillSetSnapshot:
    """An immutable capture of the entire Skill catalog at a point in time.

    Attributes:
        generation: Monotonically increasing integer (1-based).
        digest: Content-addressed SHA-256 of the complete set.
        skills: Frozen tuple of ``SkillSnapshot`` in name order.
        diagnostics: Non-fatal issues from discovery / loading.
    """

    generation: int
    digest: str
    skills: tuple[SkillSnapshot, ...]
    diagnostics: tuple["SkillDiagnostic", ...]


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def hash_content(*parts: str) -> str:
    """Return SHA-256 hex digest of concatenated UTF-8 parts."""
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
    return h.hexdigest()


# Backward-compatible alias for existing callers.
_hash_content = hash_content


def _hash_file(path: Path) -> tuple[str, int]:
    """Return ``(sha256_hex, size_bytes)`` for a file."""
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def build_skill_snapshot(
    skill,  # electromind.skills.skill.Skill
    kind: str,
    source_root: Path,
) -> SkillSnapshot:
    """Build a ``SkillSnapshot`` from a loaded ``Skill``.

    Resources are re-hashed from disk to produce per-file ``SkillResource``
    entries.  The composite ``sha256`` covers instructions + all resource
    paths + all resource content hashes.
    """
    resources: list[SkillResource] = []
    skill_dir = skill.skill_root or skill.root

    for rel_path in skill.resources:
        full = skill_dir / rel_path
        try:
            file_hash, file_size = _hash_file(full)
        except OSError:
            # File became unreadable between discovery and snapshot — skip.
            continue
        resources.append(
            SkillResource(
                relative_path=rel_path,
                sha256=file_hash,
                size=file_size,
            )
        )

    # Compute composite skill hash
    hash_parts = [skill.instructions]
    for res in sorted(resources, key=lambda r: r.relative_path):
        hash_parts.append(f"{res.relative_path}|{res.sha256}")
    skill_sha256 = _hash_content(*hash_parts)

    # Hash the full SKILL.md file for mount verification
    skill_md_path = skill_dir / "SKILL.md"
    try:
        skill_md_hash, _ = _hash_file(skill_md_path)
    except OSError:
        skill_md_hash = ""

    # Compute relative_root
    try:
        relative_root = (
            skill_dir.resolve().relative_to(source_root.resolve()).as_posix()
        )
    except ValueError:
        relative_root = skill_dir.name

    return SkillSnapshot(
        name=skill.name,
        description=skill.description,
        kind=kind,
        source_id=skill.source_id,
        source_root=source_root,
        relative_root=relative_root,
        instructions=skill.instructions,
        resources=tuple(resources),
        sha256=skill_sha256,
        skill_md_sha256=skill_md_hash,
    )


def build_skill_set_snapshot(
    catalog: "SkillCatalogSnapshot",
    generation: int,
) -> SkillSetSnapshot:
    """Build a ``SkillSetSnapshot`` from a ``SkillCatalogSnapshot``.

    Each ``Skill`` in the catalog is converted to a ``SkillSnapshot``.  The set
    digest covers every skill's name/source_id/sha256,
    and all diagnostics — so the digest changes iff any observable content
    changes.
    """

    # Determine source root per skill
    source_map: dict[str, Path] = {}
    for src in catalog.sources:
        source_map[src.id] = src.root

    # Determine kind per skill from source
    kind_map: dict[str, str] = {}
    for src in catalog.sources:
        kind_map[src.id] = src.kind

    snapshots: list[SkillSnapshot] = []
    for skill in catalog.registry.list():
        src_root = source_map.get(skill.source_id, skill.root)
        kind = kind_map.get(skill.source_id, "standard")
        snapshots.append(build_skill_snapshot(skill, kind=kind, source_root=src_root))

    snapshots.sort(key=lambda s: s.name)

    # Build set digest (A+ W8: no AGENTS.md content/hashes — skills are
    # self-contained; the digest covers skill identity, content, diagnostics).
    digest_parts: list[str] = []

    # Skill identity + hash (name-sorted for determinism)
    for ss in snapshots:
        digest_parts.append(f"{ss.name}|{ss.source_id}|{ss.sha256}")

    # Diagnostics
    for diag in sorted(catalog.diagnostics, key=lambda d: (d.path, d.code)):
        digest_parts.append(f"{diag.code}|{diag.path}|{diag.severity}|{diag.message}")

    digest = _hash_content(*digest_parts)

    return SkillSetSnapshot(
        generation=generation,
        digest=digest,
        skills=tuple(snapshots),
        diagnostics=catalog.diagnostics,
    )


def digest_prefix(digest: str, length: int = 8) -> str:
    """Return the first *length* hex chars of a digest for use in paths."""
    return digest[:length]
