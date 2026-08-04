"""SKILL-2: multi-scope candidate discovery (ancestor walk, admin, trust).

Adds the RFC target discovery capabilities *alongside* the legacy pipeline
without changing it:

- **Ancestor walk**: from ``cwd`` up to the repo root, each level checks only
  the fixed skill directories (``.electromind/skills``, ``.agents/skills``,
  ``.claude/skills``) plus the repo's structured ``skills/`` bundle — no
  recursive scans, no HOME sweeps, no sibling projects.
- **Admin scope**: ``/etc/electromind/skills`` (injectable for tests).
- **User scope**: ``~/.electromind/skills``, ``~/.agents/skills``,
  ``~/.claude/skills``.
- **Project scope**: per-level fixed dirs; nearest project outranks higher
  projects (RFC section 三).
- **Add-dir roots**: explicit configured roots, scope ``"add_dir"``.
- **Per-source fingerprint**: change detection per source.
- **Workspace Trust**: reads the *existing* trust store via an injected
  evaluator — no new trust database is created.

The legacy ``discover_skill_sources`` / ``load_skill_catalog`` keep their exact
behavior; this module is the new discovery path that SKILL-3's catalog builder
consumes.

RFC: docs/superpowers/specs/2026-08-03-skill-runtime-phase2-rfc.md
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path
from typing import Callable, Sequence

from .candidate import SkillCandidate, SkillSource, make_skill_id
from .discovery import SkillSource as LegacySkillSource

# Fixed skill directories checked at every ancestor level.
STANDARD_SKILL_DIRS = (".electromind", ".agents", ".claude")
# Dialect per fixed directory convention (RFC section 二 / 三).
DIALECT_BY_DIR = {
    ".electromind": "electromind",
    ".agents": "agents",
    ".claude": "claude",
}
# Default admin scope root.
ADMIN_SKILLS_DIR = Path("/etc/electromind/skills")

# Scope ranking for default resolution (RFC section 三: Admin > User >
# nearest Project > higher Projects > Built-in).  Lower = higher priority.
_SCOPE_RANK = {
    "admin": 0,
    "user": 1,
    "add_dir": 2,
    "project": 3,
    "builtin": 4,
    "plugin": 5,
}
# Dialect order within the same scope (RFC section 三).
_DIALECT_RANK = {"electromind": 0, "agents": 1, "claude": 2, "builtin": 3}


def source_rank(source: SkillSource) -> tuple[int, int, int]:
    """Return a sort key for *source* per RFC source priority.

    ``(scope_rank, distance, dialect_rank)`` — lower sorts first.  Distance
    dominates dialect within ``project`` scope so the nearest project
    (RFC section 三 #5) always beats higher projects (#6), while dialect
    order (electromind > agents > claude) applies within the same level.
    """
    scope_rank = _SCOPE_RANK.get(source.scope, 99)
    dialect_rank = _DIALECT_RANK.get(source.dialect, 99)
    distance = source.distance_from_cwd if source.distance_from_cwd is not None else 0
    return (scope_rank, distance, dialect_rank)


def find_repo_root(cwd: Path) -> Path | None:
    """Walk up from *cwd* looking for a ``.git`` marker (repo root).

    Returns ``None`` when no marker is found (no ancestor walk is performed).
    """
    for p in (cwd, *cwd.parents):
        if (p / ".git").exists():
            return p
    return None


def _ancestor_levels(cwd: Path, project_root: Path | None) -> list[Path]:
    """Return the ancestor levels to inspect, nearest (cwd) first.

    The chain ends at *project_root* when it is an ancestor of *cwd*, at the
    repo root (``.git`` marker) otherwise, or at *cwd* alone when no marker
    exists.  An explicit *project_root* outside the chain is appended as the
    topmost level so its skills stay discoverable.
    """
    top = project_root or find_repo_root(cwd) or cwd
    levels: list[Path] = []
    cur = cwd
    while True:
        levels.append(cur)
        if cur == top:
            break
        if cur.parent == cur:
            if levels[-1] != top:
                levels.append(top)
            break
        cur = cur.parent
    return levels


def _source_id(scope: str, dialect: str, root: Path) -> str:
    """Stable source id: ``{scope}-{dialect}-{hash12(root)}``."""
    h = hashlib.sha256(root.as_posix().encode("utf-8")).hexdigest()[:12]
    return f"{scope}-{dialect}-{h}"


def _project_source(
    scope: str,
    dialect: str,
    root: Path,
    *,
    distance: int | None,
    trust_domain: str,
    project_root: Path | None,
) -> SkillSource:
    return SkillSource(
        source_id=_source_id(scope, dialect, root),
        scope=scope,  # type: ignore[arg-type]
        dialect=dialect,  # type: ignore[arg-type]
        root=root,
        project_root=project_root,
        distance_from_cwd=distance,
        trust_domain=trust_domain,
        read_only=False,
    )


def discover_candidate_sources(
    project_path: str | Path | None,
    *,
    cwd: str | Path | None = None,
    configured_roots: Sequence[str | Path] = (),
    user_home: Path | None = None,
    admin_root: str | Path | None = None,
    builtin_roots: Sequence[str | Path] | None = None,
) -> tuple[SkillSource, ...]:
    """Discover Skill sources across all scopes (RFC section 十).

    Args:
        project_path: Repo root for project-scoped discovery.
        cwd: Working directory the ancestor walk starts from (default: ``os.getcwd()``).
        configured_roots: Explicit add-dir roots (scope ``"add_dir"``).
        user_home: User home for user-scoped discovery (default: ``Path.home()``).
        admin_root: Admin skills root (default: ``/etc/electromind/skills``).
        builtin_roots: Builtin skill roots (procedures/ + tools/ bundle).
            Defaults to ``builtin.builtin_roots()`` — the wheel/venv installed
            bundle or the repo ``skills/`` fallback (SKILL-8).

    Returns:
        Sources ordered by RFC source priority (admin > user > nearest project
        > higher projects; dialect order electromind > agents > claude within
        a scope).  Trust is *not* evaluated here — callers pass candidates
        through ``load_candidates`` with an evaluator.
    """
    workdir = Path(cwd or os.getcwd()).expanduser().resolve()
    home = Path(user_home or Path.home()).expanduser().resolve()
    proj = (
        Path(project_path).expanduser().resolve() if project_path is not None else None
    )

    sources: list[SkillSource] = []

    # Builtin scope — wheel/venv installed bundle or repo skills/ fallback.
    if builtin_roots is None:
        from .builtin import builtin_roots as _default_builtin_roots

        builtin_roots = _default_builtin_roots()
    for root in builtin_roots:
        r = Path(root).expanduser().resolve()
        if r.is_dir():
            sources.append(
                SkillSource(
                    source_id=_source_id("builtin", "builtin", r),
                    scope="builtin",
                    dialect="builtin",
                    root=r,
                    trust_domain="builtin",
                    read_only=True,
                )
            )

    # Admin scope — single fixed root.
    admin = Path(admin_root or ADMIN_SKILLS_DIR).expanduser().resolve()
    if admin.is_dir():
        sources.append(
            SkillSource(
                source_id=_source_id("admin", "electromind", admin),
                scope="admin",
                dialect="electromind",
                root=admin,
                trust_domain="admin",
                read_only=True,
            )
        )

    # User scope — three fixed directories.
    for dir_name in STANDARD_SKILL_DIRS:
        root = home / dir_name / "skills"
        if root.is_dir():
            sources.append(
                SkillSource(
                    source_id=_source_id("user", DIALECT_BY_DIR[dir_name], root),
                    scope="user",
                    dialect=DIALECT_BY_DIR[dir_name],  # type: ignore[arg-type]
                    root=root,
                    trust_domain="user",
                    read_only=False,
                )
            )

    # Project scope — ancestor walk over fixed dirs per level.
    for distance, level in enumerate(_ancestor_levels(workdir, proj)):
        trust_domain = str(level)
        # The repo's structured bundle: <level>/skills with AGENTS.md.
        structured = level / "skills"
        if (structured / "AGENTS.md").exists():
            sources.append(
                _project_source(
                    "project",
                    "electromind",
                    structured,
                    distance=distance,
                    trust_domain=trust_domain,
                    project_root=level,
                )
            )
        for dir_name in STANDARD_SKILL_DIRS:
            root = level / dir_name / "skills"
            if root.is_dir():
                sources.append(
                    _project_source(
                        "project",
                        DIALECT_BY_DIR[dir_name],
                        root,
                        distance=distance,
                        trust_domain=trust_domain,
                        project_root=level,
                    )
                )

    # Add-dir roots — explicit user-provided directories.
    for idx, root in enumerate(configured_roots):
        r = Path(root).expanduser().resolve()
        if r.is_dir():
            sources.append(
                SkillSource(
                    source_id=_source_id("add_dir", "electromind", r),
                    scope="add_dir",
                    dialect="electromind",
                    root=r,
                    trust_domain=f"add_dir:{idx}",
                    read_only=False,
                )
            )

    return tuple(sorted(sources, key=source_rank))


def _to_legacy_source(source: SkillSource) -> LegacySkillSource:
    """Map an RFC ``SkillSource`` onto the legacy ``discovery.SkillSource``.

    Legacy scope mapping: project/add_dir → ``"project"``/``"configured"``,
    user → ``"user"``.  Structured (AGENTS.md) roots become ``"structured"``,
    everything else ``"standard"``.
    """
    legacy_scope = {
        "project": "project",
        "add_dir": "configured",
        "user": "user",
        "admin": "configured",
        "builtin": "configured",
    }.get(source.scope, "configured")
    kind = "structured" if (source.root / "AGENTS.md").exists() else "standard"
    return LegacySkillSource(
        id=source.source_id,
        kind=kind,  # type: ignore[arg-type]
        scope=legacy_scope,  # type: ignore[arg-type]
        root=source.root,
        priority=0,
    )


def fingerprint_source(source: SkillSource) -> str:
    """Return a content fingerprint for a single *source*.

    Hashes every skill directory under the source (SKILL.md + resources) so
    change detection covers ALL candidates — including same-name duplicates
    the legacy loader would have dropped.
    """
    from .snapshot import hash_content

    parts = [source.source_id, source.root.as_posix()]
    for skill_dir in _source_skill_dirs(source):
        parts.append(skill_dir.as_posix())
        md = skill_dir / "SKILL.md"
        if md.is_file():
            parts.append(hash_content(md.read_bytes().decode("utf-8", "replace")))
        for rel in sorted(_resource_rel_paths(skill_dir)):
            full = skill_dir / rel
            try:
                parts.append(
                    hash_content(rel, full.read_bytes().decode("utf-8", "replace"))
                )
            except OSError:
                parts.append(rel)
    return hash_content(*parts)


def _source_skill_dirs(source: SkillSource) -> list[Path]:
    """The skill directories under *source* (structured or standard layout).

    - Structured (AGENTS.md present): ``procedures/*`` and ``tools/*``.
    - Standard: direct children that contain ``SKILL.md``.
    """
    dirs: list[Path] = []
    if (source.root / "AGENTS.md").is_file():
        for sub in ("procedures", "tools"):
            subdir = source.root / sub
            if not subdir.is_dir():
                continue
            for entry in sorted(subdir.iterdir()):
                if entry.is_dir() and (entry / "SKILL.md").is_file():
                    dirs.append(entry)
    else:
        for entry in sorted(source.root.iterdir()):
            if entry.is_dir() and (entry / "SKILL.md").is_file():
                dirs.append(entry)
    return dirs


def _resource_rel_paths(skill_dir: Path) -> list[str]:
    """Relative resource paths under *skill_dir* (excluding SKILL.md)."""
    from .skill import collect_resources

    return [rel for rel in collect_resources(skill_dir) if rel != "SKILL.md"]


def load_candidates(
    sources: tuple[SkillSource, ...],
    *,
    is_project_trusted: Callable[[Path | None], bool] | None = None,
) -> tuple[SkillCandidate, ...]:
    """Load every source into ``SkillCandidate`` tuples — **per directory**.

    Unlike the legacy ``load_skill_catalog`` (first-wins, drops same-name
    duplicates within a source), this loader:

    - keeps **every** skill directory as a candidate, including same-source
      same-name duplicates;
    - preserves the **full frontmatter** in the descriptor;
    - produces **unique qualified ids** (add-dir roots and same-source
      collisions get a stable locator hash segment).

    Trust is evaluated per candidate using the *injected* evaluator (RFC
    section 五): project sources are ``trusted`` only when the workspace
    trust store marks the project trusted, otherwise ``untrusted``; all other
    scopes (admin/user/add_dir/builtin) default to ``trusted``.  No trust
    database is created or modified here.
    """

    evaluator = is_project_trusted or (lambda _project_root: True)
    candidates: list[SkillCandidate] = []
    used_ids: set[str] = set()

    for source in sources:
        for skill_dir in _source_skill_dirs(source):
            candidate = _load_one_candidate(
                source,
                skill_dir,
                evaluator=evaluator,
            )
            if candidate is None:
                continue
            # Ensure a globally-unique qualified id.
            skill_id = candidate.skill_id
            if skill_id in used_ids:
                locator = _locator_hash(skill_dir)
                parts = skill_id.split(":")
                skill_id = ":".join(parts[:-1] + [locator, parts[-1]])
            used_ids.add(skill_id)
            candidates.append(replace(candidate, skill_id=skill_id))
    return tuple(candidates)


def _load_one_candidate(
    source: SkillSource,
    skill_dir: Path,
    *,
    evaluator: Callable[[Path | None], bool],
) -> SkillCandidate | None:
    """Load one skill directory into a candidate, or ``None`` when invalid."""
    from .candidate import SkillDescriptor, make_skill_id
    from .discovery import SkillDiagnostic
    from .skill import (
        collect_resources,
        has_symlinks,
        parse_skill_md,
        validate_skill_name,
    )
    from .snapshot import hash_content

    diagnostics: list[SkillDiagnostic] = []

    # Symlink / escape safety checks (mirror the legacy loader).
    try:
        resolved = skill_dir.resolve()
        resolved.relative_to(source.root.resolve())
    except ValueError:
        return None  # resolves outside the source root — drop
    if has_symlinks(resolved):
        return None  # symlinks rejected — drop

    md_path = skill_dir / "SKILL.md"
    try:
        frontmatter, body = parse_skill_md(md_path.read_text(encoding="utf-8"))
    except OSError as exc:
        diagnostics.append(
            SkillDiagnostic(
                code="skill_load_error",
                message=f"cannot read SKILL.md: {exc}",
                path=str(skill_dir),
                severity="error",
            )
        )
        return None

    name = str(frontmatter.get("name") or "").strip() or skill_dir.name
    description = str(frontmatter.get("description") or "").strip()
    if not description:
        diagnostics.append(
            SkillDiagnostic(
                code="skill_missing_description",
                message=f"frontmatter must include `description` in {skill_dir.name}",
                path=str(md_path),
                severity="error",
            )
        )
    name_err = validate_skill_name(name)
    if name_err:
        diagnostics.append(
            SkillDiagnostic(
                code="skill_name_invalid",
                message=name_err,
                path=str(skill_dir),
                severity="error",
            )
        )

    resources = tuple(rel for rel in collect_resources(skill_dir) if rel != "SKILL.md")
    content_digest = hash_content(body, description, *sorted(resources))
    resource_digest = hash_content(*sorted(resources)) if resources else hash_content()

    # Frontmatter policy fields → runtime model (RFC section 二/四).
    compatibility = _parse_compatibility(frontmatter)
    disable_model_invocation = _parse_bool_flag(frontmatter, "disable-model-invocation")

    # Builtin kind from the subdirectory under the builtin root.
    kind: str | None = None
    if source.scope == "builtin":
        try:
            first = skill_dir.resolve().relative_to(source.root.resolve()).parts[0]
            kind = "procedure" if first == "procedures" else first
        except ValueError:
            kind = "tool"

    descriptor = SkillDescriptor(
        name=name,
        description=description,
        entry_path=md_path,
        root_path=skill_dir,
        frontmatter=dict(frontmatter),
        content_digest=content_digest,
        resource_digest=resource_digest,
        compatibility=compatibility,
        disable_model_invocation=disable_model_invocation,
    )
    skill_id = make_skill_id(
        scope=source.scope,
        name=name,
        dialect=source.dialect,
        project_dir=(source.project_root.name if source.scope == "project" else None),
        kind=kind,
    )
    trusted = evaluator(source.project_root) if source.scope == "project" else True
    return SkillCandidate(
        skill_id=skill_id,
        descriptor=descriptor,
        source=source,
        enabled_state="on",
        trust_state="trusted" if trusted else "untrusted",
        diagnostics=tuple(diagnostics),
    )


def _parse_compatibility(frontmatter: dict) -> tuple[str, ...]:
    """Parse frontmatter ``compatibility`` into a tuple of capability labels.

    Accepts a single string (``compatibility: ssh``) or a list
    (``compatibility: [ssh, local]``).  Invalid values degrade to ``()``
    (no declared restriction).
    """
    value = frontmatter.get("compatibility")
    if isinstance(value, str):
        labels = [value.strip()]
    elif isinstance(value, (list, tuple)):
        labels = [str(v).strip() for v in value]
    else:
        return ()
    return tuple(label for label in labels if label)


def _parse_bool_flag(frontmatter: dict, key: str) -> bool:
    """Parse a boolean frontmatter flag (``true``/``false``/``yes``/``no``)."""
    value = frontmatter.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1", "on")
    return False


def _locator_hash(path: Path) -> str:
    """Stable short locator for qualified-id disambiguation."""
    return hashlib.sha256(path.as_posix().encode("utf-8")).hexdigest()[:8]


def model_visible_candidates(
    candidates: tuple[SkillCandidate, ...],
) -> tuple[SkillCandidate, ...]:
    """Filter candidates to those the model may discover (RFC section 四/五).

    Model-visible = ``trust_state == "trusted"``, ``enabled_state in
    ("on", "name_only")``, and NOT ``disable-model-invocation``.  Untrusted/
    blocked/opt-out candidates are still discoverable via the ``/skills``
    picker (diagnostics surface), they simply never enter the model catalog.
    """
    return tuple(
        c
        for c in candidates
        if c.trust_state == "trusted"
        and c.enabled_state in ("on", "name_only")
        and not c.descriptor.disable_model_invocation
    )


def qualified_skill_id(candidate: SkillCandidate) -> str:
    """Return the candidate's qualified skill id (never empty).

    Candidates built by this module carry a ``skill_id`` from
    ``build_candidate``; this helper documents the invariant used by the
    resolver (SKILL-3).
    """
    if candidate.skill_id:
        return candidate.skill_id
    return make_skill_id(
        scope=candidate.source.scope,
        name=candidate.descriptor.name,
        dialect=candidate.source.dialect,
        project_dir=(
            candidate.source.project_root.name
            if candidate.source.scope == "project"
            else None
        ),
    )
