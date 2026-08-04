"""Skill source discovery and catalog snapshots.

Deterministic discovery across project, configured, and user roots.

A+ W5/W8: discovery has exactly one model — the plain flat skill root
``<root>/<skill-name>/SKILL.md`` (``.agents/skills``, ``.electromind/skills``,
user home, and the builtin ``procedures``/``tools`` roots).  There is no
structured-root variant and no AGENTS.md marker.

Public entry points:
- ``discover_skill_sources()`` → ordered tuple of ``SkillSource``
- ``load_skill_catalog()`` → immutable ``SkillCatalogSnapshot``
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .skill import (
    Skill,
    SkillRegistry,
    has_symlinks,
    validate_skill_name,
)
from .snapshot import hash_content  # shared fingerprint hasher

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DiscoveredSkill:
    """A skill candidate found during discovery, before full content loading.

    Discovery only locates skills, determines sources, and resolves priorities.
    Snapshot building reads the full content later.

    Attributes:
        name: Skill name (from frontmatter or directory name).
        description: From frontmatter.
        kind: ``"procedure"``, ``"tool"``, or ``"standard"``.
        source_id: Stable source identifier.
        source_priority: Lower = higher priority for duplicate resolution.
        source_root: Absolute path to the source root.
        skill_root: Absolute path to the skill directory.
        skill_md: Absolute path to ``SKILL.md``.
    """

    name: str
    description: str
    kind: str
    source_id: str
    source_priority: int
    source_root: Path
    skill_root: Path
    skill_md: Path


@dataclass(frozen=True, slots=True)
class SkillSource:
    """A discovered root that may contain Skills.

    Attributes:
        id: Stable identifier derived from scope, kind, and normalised path.
        kind: ``"standard"`` — A+ W5: every source is a flat per-skill root.
        scope: ``"project"``, ``"configured"``, or ``"user"``.
        root: Absolute filesystem path to the source root.
        priority: Lower number = higher priority in duplicate resolution.
    """

    id: str
    kind: Literal["structured", "standard"]
    scope: Literal["project", "configured", "user"]
    root: Path
    priority: int


@dataclass(frozen=True, slots=True)
class SkillDiagnostic:
    """A non-fatal issue discovered during scanning."""

    code: str
    message: str
    path: str
    severity: Literal["warning", "error"] = "warning"


@dataclass(frozen=True, slots=True)
class SkillMount:
    """Describes where a Skill was installed in a sandbox."""

    source_root: str
    skill_root: str


@dataclass(frozen=True, slots=True)
class SkillCatalogSnapshot:
    """An immutable point-in-time snapshot of the Skill catalog.

    Attributes:
        registry: The populated ``SkillRegistry``.
        sources: Ordered discovery sources.
        diagnostics: Non-fatal issues found during discovery/loading.
        fingerprint: SHA-256 hash of the catalog content for change detection.
    """

    registry: SkillRegistry
    sources: tuple[SkillSource, ...]
    diagnostics: tuple[SkillDiagnostic, ...]
    fingerprint: str


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

STANDARD_MARKER = "SKILL.md"


def _make_source_id(scope: str, kind: str, root: Path) -> str:
    """Derive a stable, human-readable source id.

    Uses a short content hash of the normalised path to avoid leaking
    host directory structure into mount paths and diagnostics.
    """
    h = hashlib.sha256(root.as_posix().encode("utf-8")).hexdigest()[:12]
    return f"{scope}-{kind}-{h}"


# _hash_content is imported from .snapshot as hash_content; keep alias for
# internal consistency.
_hash_content = hash_content


def _hash_file_hex(path: Path) -> str:
    """Return SHA-256 hex digest of a file's content."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def discover_skill_sources(
    project_path: str | Path | None,
    *,
    configured_roots: tuple[str | Path, ...] = (),
    user_home: Path | None = None,
) -> tuple[SkillSource, ...]:
    """Return an ordered, deterministic list of Skill sources.

    A+ W5: every source is a plain flat skill root; the structured
    ``<project>/skills`` bundle is no longer discovered.

    Priority order (first = highest):
    1. ``<project>/.agents/skills``
    2. ``<project>/.electromind/skills``
    3. configured / legacy roots (``configured_roots``)
    4. ``~/.electromind/skills``
    5. ``~/.agents/skills``
    """
    sources: list[SkillSource] = []
    home = user_home or Path.home()

    # 1–3: project sources (A+ W5: only the flat fixed skill dirs — the
    # structured ``<project>/skills`` bundle is no longer a discovery path)
    if project_path:
        proj = Path(project_path).expanduser().resolve()

        for priority, candidate in enumerate(
            (proj / ".agents" / "skills", proj / ".electromind" / "skills"), start=2
        ):
            if candidate.is_dir():
                sources.append(
                    SkillSource(
                        id=_make_source_id("project", "standard", candidate),
                        kind="standard",
                        scope="project",
                        root=candidate,
                        priority=priority,
                    )
                )

    # 4: configured / legacy roots
    for idx, root in enumerate(configured_roots):
        r = Path(root).expanduser().resolve()
        if r.is_dir():
            sources.append(
                SkillSource(
                    id=_make_source_id("configured", "standard", r),
                    kind="standard",
                    scope="configured",
                    root=r,
                    priority=10 + idx,
                )
            )

    # 5: user home ~/.electromind/skills
    user_em = home / ".electromind" / "skills"
    if user_em.is_dir():
        sources.append(
            SkillSource(
                id=_make_source_id("user", "standard", user_em),
                kind="standard",
                scope="user",
                root=user_em,
                priority=20,
            )
        )

    # 6: user home ~/.agents/skills
    user_agents = home / ".agents" / "skills"
    if user_agents.is_dir():
        sources.append(
            SkillSource(
                id=_make_source_id("user", "standard", user_agents),
                kind="standard",
                scope="user",
                root=user_agents,
                priority=21,
            )
        )

    return tuple(sources)


def _load_standard_source(
    source: SkillSource,
) -> tuple[list[Skill], list[SkillDiagnostic]]:
    """Load Skills from a flat directory of per-skill subdirectories.

    Each skill subdirectory is loaded individually — a single broken
    SKILL.md does not discard the entire source.
    """
    from .skill import load_skill as _load_one

    diagnostics: list[SkillDiagnostic] = []
    loaded: list[Skill] = []

    if not source.root.is_dir():
        diagnostics.append(
            SkillDiagnostic(
                code="skill_source_not_found",
                message=f"source root does not exist: {source.root}",
                path=str(source.root),
                severity="error",
            )
        )
        return loaded, diagnostics

    for entry in sorted(source.root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.exists():
            continue

        try:
            skill = _load_one(entry)
        except Exception as exc:
            diagnostics.append(
                SkillDiagnostic(
                    code="skill_load_error",
                    message=f"failed to load skill {entry.name}: {exc}",
                    path=str(entry),
                    severity="error",
                )
            )
            continue

        try:
            resolved = skill.root.resolve()
            if not _path_is_within_root(resolved, source.root):
                diagnostics.append(
                    SkillDiagnostic(
                        code="skill_resolves_outside_root",
                        message=f"skill resolves outside its source root: {skill.root}",
                        path=str(skill.root),
                        severity="error",
                    )
                )
                continue

            # Reject symlinks anywhere in the skill tree
            syms = has_symlinks(resolved)
            if syms:
                for sym_path in syms:
                    diagnostics.append(
                        SkillDiagnostic(
                            code="skill_symlink_rejected",
                            message=(
                                f"skill {skill.name!r} contains a symlink: "
                                f"{sym_path.relative_to(resolved)}"
                            ),
                            path=str(sym_path),
                            severity="error",
                        )
                    )
                continue

            # Validate name
            name_err = validate_skill_name(skill.name)
            if name_err:
                diagnostics.append(
                    SkillDiagnostic(
                        code="skill_name_invalid",
                        message=name_err,
                        path=str(resolved),
                        severity="error",
                    )
                )
                continue
        except Exception as exc:
            diagnostics.append(
                SkillDiagnostic(
                    code="skill_resolve_error",
                    message=f"cannot resolve skill path: {exc}",
                    path=str(skill.root),
                    severity="error",
                )
            )
            continue

        loaded.append(
            Skill(
                name=skill.name,
                description=skill.description,
                instructions=skill.instructions,
                root=skill.root,
                resources=skill.resources,
                source_id=source.id,
                skill_root=skill.root,
            )
        )

    return loaded, diagnostics


def _path_is_within_root(path: Path, root: Path) -> bool:
    """Return True if *path* is equal to *root* or a descendant of it."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _build_fingerprint(
    skills: list[Skill],
    sources: tuple[SkillSource, ...],
) -> str:
    """Build a deterministic SHA-256 fingerprint from catalog contents."""
    parts: list[str] = []

    # Hash source metadata in order
    for src in sources:
        parts.append(
            f"{src.id}|{src.kind}|{src.scope}|{src.root.as_posix()}|{src.priority}"
        )

    # Hash each skill in name-sorted order, including resource content
    for skill in sorted(skills, key=lambda s: s.name):
        parts.append(f"{skill.name}|{skill.description}|{skill.source_id}")
        parts.append(skill.instructions)
        parts.append(skill.sha256 if skill.sha256 else "")
        # Include resource content hashes so file changes are detected
        skill_dir = skill.skill_root or skill.root
        for res_path in sorted(skill.resources):
            full = skill_dir / res_path
            try:
                res_hash = _hash_file_hex(full)
                parts.append(f"{res_path}|{res_hash}")
            except OSError:
                parts.append(res_path)

    return _hash_content(*parts)


def load_skill_catalog(
    sources: tuple[SkillSource, ...],
) -> SkillCatalogSnapshot:
    """Load a ``SkillCatalogSnapshot`` from an ordered tuple of sources.

    Duplicate Skill names are resolved by source priority: the first-registered
    Skill wins (lowest priority number), and later duplicates produce a
    ``"duplicate_skill_name"`` diagnostic.
    """
    all_skills: list[Skill] = []
    all_diagnostics: list[SkillDiagnostic] = []

    # A+ W5/W8: every source is a plain flat skill root — one loader.
    for source in sources:
        skills, diags = _load_standard_source(source)
        all_skills.extend(skills)
        all_diagnostics.extend(diags)

    # Register by priority — first wins
    registry = SkillRegistry()
    for skill in sorted(all_skills, key=lambda s: _source_priority_for(s, sources)):
        if registry.get(skill.name) is not None:
            all_diagnostics.append(
                SkillDiagnostic(
                    code="duplicate_skill_name",
                    message=(
                        f"skill '{skill.name}' from {skill.source_id} "
                        f"is shadowed by a higher-priority source"
                    ),
                    path=str(skill.root),
                    severity="warning",
                )
            )
            continue
        registry.register(skill)

    fingerprint = _build_fingerprint(list(registry.list()), sources)

    return SkillCatalogSnapshot(
        registry=registry,
        sources=sources,
        diagnostics=tuple(all_diagnostics),
        fingerprint=fingerprint,
    )


def _source_priority_for(skill: Skill, sources: tuple[SkillSource, ...]) -> int:
    """Return the priority of the source that produced *skill*."""
    for src in sources:
        if src.id == skill.source_id:
            return src.priority
    return 999
