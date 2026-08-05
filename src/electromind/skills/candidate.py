"""SKILL-1: multi-candidate Skill model — Source / Descriptor / Candidate.

Introduces the RFC target data model *alongside* the legacy single-value
``SkillRegistry``, without changing existing discovery behavior:

- ``SkillSource``      → where a Skill was found (scope / dialect / trust domain).
- ``SkillDescriptor``  → what a specific Skill version is (name, body digest,
                         resource digest, compatibility).
- ``SkillCandidate``   → one specific discovered version, with its identity,
                         enabled state, and trust state.
- ``QualifiedSkillID`` → the stable string that uniquely addresses a candidate
                         (e.g. ``project:repo-root:agents:cp2k``).

This module is additive: legacy ``discovery.SkillSource`` and ``skill.SkillRegistry``
stay untouched.  The compatibility adapters at the bottom translate the legacy
pipeline's results into the new model losslessly and build a legacy
``SkillRegistry`` back from candidates, so SKILL-2/3 can rewire discovery without
a flag-day switch.

RFC: docs/superpowers/specs/2026-08-03-skill-runtime-phase2-rfc.md
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Mapping

from .discovery import SkillDiagnostic
from .snapshot import hash_content

if TYPE_CHECKING:
    from .discovery import SkillCatalogSnapshot
    from .discovery import SkillSource as LegacySkillSource
    from .skill import Skill, SkillRegistry

Scope = Literal["builtin", "admin", "user", "project", "add_dir", "plugin"]
Dialect = Literal["electromind", "agents", "claude", "builtin"]
EnabledState = Literal["on", "name_only", "manual_only", "off"]
TrustState = Literal["trusted", "untrusted", "blocked"]


# ---------------------------------------------------------------------------
# Qualified Skill ID
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QualifiedSkillID:
    """A stable, parseable identifier that uniquely addresses a Skill candidate.

    Serialized form: ``{scope}:{middle...}:{name}`` where ``middle`` locates the
    source:

    - builtin: ``builtin:procedure:cp2k`` (middle = sub-kind)
    - user / admin / add_dir: ``user:agents:cp2k`` (middle = dialect)
    - project: ``project:repo-root:agents:cp2k`` (middle = project-dir + dialect)

    Attributes:
        scope: Source scope.
        name: Skill name.
        middle: Locator segments between scope and name (project-dir, dialect,
            or builtin sub-kind).
    """

    scope: str
    name: str
    middle: tuple[str, ...] = ()

    def __str__(self) -> str:
        parts = [self.scope]
        parts.extend(self.middle)
        parts.append(self.name)
        return ":".join(parts)

    @classmethod
    def parse(cls, text: str) -> "QualifiedSkillID":
        """Parse a qualified skill id string.

        Raises ``ValueError`` for malformed ids (fewer than two segments).
        """
        parts = text.split(":")
        if len(parts) < 2:
            raise ValueError(f"malformed qualified skill id: {text!r}")
        if not parts[0] or not parts[-1]:
            raise ValueError(f"malformed qualified skill id: {text!r}")
        return cls(scope=parts[0], name=parts[-1], middle=tuple(parts[1:-1]))


def make_skill_id(
    *,
    scope: str,
    name: str,
    dialect: str | None = None,
    project_dir: str | None = None,
    kind: str | None = None,
) -> str:
    """Build a qualified skill id string from structured components.

    ``project_dir`` is included for ``project`` scope; ``kind`` (procedure/tool)
    is used for ``builtin`` scope; otherwise ``dialect`` fills the middle.
    """
    if scope == "project":
        if project_dir is None:
            raise ValueError("project-scope skill id requires project_dir")
        if dialect is None:
            raise ValueError("project-scope skill id requires dialect")
        middle = (project_dir, dialect)
    elif scope == "builtin":
        middle = (kind,) if kind else ()
    else:
        middle = (dialect,) if dialect else ()
    return str(QualifiedSkillID(scope=scope, name=name, middle=middle))


# ---------------------------------------------------------------------------
# RFC target models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SkillSource:
    """Where a Skill was found (RFC target model).

    This is distinct from the legacy ``discovery.SkillSource`` (which carries a
    single integer ``priority``).  Here priority/trust/state are kept separate:

    - ``scope``            → builtin / admin / user / project / add_dir / plugin
    - ``dialect``          → which directory convention the root uses
    - ``project_root``     → repo root for project-scoped sources
    - ``distance_from_cwd``→ ancestor distance (0 = cwd itself)
    - ``trust_domain``     → the trust decision domain (read from Workspace Trust)
    - ``read_only``        → whether this source is treated as immutable
    """

    source_id: str
    scope: Scope
    dialect: Dialect
    root: Path
    project_root: Path | None = None
    distance_from_cwd: int | None = None
    trust_domain: str = ""
    read_only: bool = False
    # Root-internal discovery may adopt DIRECT-CHILD directory symlinks whose
    # real target is inside one of these trusted paths (e.g. the project root
    # or explicitly configured external skill roots).  Empty by default.
    adopted_targets: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class SkillDescriptor:
    """What one specific Skill version is.

    Attributes:
        name: Skill name (from frontmatter or directory name).
        description: Human-readable one-liner from frontmatter.
        entry_path: Path to ``SKILL.md``.
        root_path: Path to the skill directory.
        frontmatter: Raw frontmatter mapping (as parsed from ``SKILL.md``).
        content_digest: SHA-256 of the instruction body + description.
        resource_digest: SHA-256 over the sorted resource path list.
        compatibility: Dialects this Skill declares compatibility with
            (from frontmatter ``compatibility``).  An empty tuple means no
            declared restriction.
        disable_model_invocation: Whether the model may invoke this Skill
            implicitly (frontmatter ``disable-model-invocation``).  The user
            can still invoke it explicitly.
    """

    name: str
    description: str
    entry_path: Path
    root_path: Path
    frontmatter: Mapping[str, object]
    content_digest: str
    resource_digest: str
    compatibility: tuple[str, ...] = ()
    disable_model_invocation: bool = False


@dataclass(frozen=True, slots=True)
class SkillCandidate:
    """One discovered Skill version, fully addressable.

    Attributes:
        skill_id: Qualified skill id (e.g. ``project:repo-root:agents:cp2k``).
        descriptor: The specific version's content.
        source: The EFFECTIVE source (highest priority after physical-file
            dedup across overlapping roots).
        discovery_sources: Every source that produced this same physical
            skill (dedup provenance).  Empty when only one root found it.
        enabled_state: on / name_only / manual_only / off.
        trust_state: trusted / untrusted / blocked.
        diagnostics: Non-fatal issues specific to this candidate.
    """

    skill_id: str
    descriptor: SkillDescriptor
    source: SkillSource
    discovery_sources: tuple[SkillSource, ...] = ()
    enabled_state: EnabledState = "on"
    trust_state: TrustState = "trusted"
    diagnostics: tuple[SkillDiagnostic, ...] = ()


# ---------------------------------------------------------------------------
# Builders (from legacy pipeline)
# ---------------------------------------------------------------------------


def _resource_digest(resources: tuple[str, ...]) -> str:
    """SHA-256 over the sorted resource path list."""
    return hash_content(*sorted(resources)) if resources else hash_content()


def build_descriptor(skill: "Skill") -> SkillDescriptor:
    """Build a ``SkillDescriptor`` from a legacy ``Skill`` (compat parsing).

    ``content_digest`` is the legacy ``skill.sha256`` (covers instructions +
    description + resource paths), so digests stay stable across the adapter.
    """
    skill_dir = skill.skill_root or skill.root
    return SkillDescriptor(
        name=skill.name,
        description=skill.description,
        entry_path=skill_dir / "SKILL.md",
        root_path=skill_dir,
        frontmatter={"name": skill.name, "description": skill.description},
        content_digest=skill.sha256,
        resource_digest=_resource_digest(skill.resources),
    )


_LEGACY_SCOPE_TO_SCOPE: dict[str, Scope] = {
    "project": "project",
    "configured": "add_dir",
    "user": "user",
}


def _legacy_source_to_source(source: "LegacySkillSource") -> SkillSource:
    """Map a legacy ``discovery.SkillSource`` onto the RFC ``SkillSource``."""
    scope = _LEGACY_SCOPE_TO_SCOPE.get(source.scope, "user")
    # The legacy source doesn't carry dialect; infer it from the root basename.
    root_name = source.root.name
    if scope == "builtin":
        dialect: Dialect = "builtin"
    elif root_name == "skills" and source.kind == "structured":
        dialect = "electromind"
    elif root_name == "claude":
        dialect = "claude"
    else:
        dialect = "electromind" if root_name == "electromind" else "agents"
    # Project root: for a structured root (<project>/skills) the parent is the
    # project; for a standard root (<project>/.agents/skills) the project is
    # two levels up.
    project_root: Path | None = None
    if scope == "project":
        if source.kind == "structured":
            project_root = source.root.parent
        else:
            project_root = source.root.parent.parent
    return SkillSource(
        source_id=source.id,
        scope=scope,
        dialect=dialect,
        root=source.root,
        project_root=project_root,
        distance_from_cwd=None,
        trust_domain=source.scope,
        read_only=source.scope == "configured",
    )


def build_candidate(skill: "Skill", source: "LegacySkillSource") -> SkillCandidate:
    """Build a ``SkillCandidate`` from a legacy ``Skill`` + ``SkillSource``.

    This is the compat parsing path: it expresses a legacy discovery result
    losslessly as a candidate without reading any additional files.
    """
    new_source = _legacy_source_to_source(source)
    skill_id = make_skill_id(
        scope=new_source.scope,
        name=skill.name,
        dialect=new_source.dialect,
        project_dir=(
            new_source.project_root.name if new_source.scope == "project" else None
        ),
        kind=(source.root.name if new_source.scope == "builtin" else None),
    )
    return SkillCandidate(
        skill_id=skill_id,
        descriptor=build_descriptor(skill),
        source=new_source,
        enabled_state="on",
        trust_state="trusted",
    )


def candidates_from_catalog(
    catalog: "SkillCatalogSnapshot",
) -> tuple[SkillCandidate, ...]:
    """Convert a legacy ``SkillCatalogSnapshot`` into ``SkillCandidate`` tuples.

    Only the *visible* (registered) skills are converted — the shadowed
    duplicates that ``load_skill_catalog`` dropped are not recoverable here.
    Retaining every same-name candidate is SKILL-2/3 work; this adapter is the
    lossless representation of what the legacy catalog currently exposes.
    """
    source_by_id = {s.id: s for s in catalog.sources}
    candidates: list[SkillCandidate] = []
    for skill in catalog.registry.list():
        src = source_by_id.get(skill.source_id)
        if src is None:
            continue
        candidates.append(build_candidate(skill, src))
    return tuple(candidates)


def registry_from_candidates(
    candidates: tuple[SkillCandidate, ...],
) -> "SkillRegistry":
    """Build a legacy ``SkillRegistry`` from candidates (compat adapter).

    Preserves the legacy first-wins semantics: candidates are ordered by the
    OLD priority (project < add_dir/configured < user < admin < builtin) so a
    project Skill still beats a configured-root duplicate — matching
    ``load_skill_catalog``.  This lets legacy callers keep using the old
    registry during the phase-2 migration; the new-chain resolver applies the
    RFC source priority separately.
    """
    from .skill import Skill, SkillRegistry

    # Legacy first-wins order (lower = wins): project roots beat configured
    # roots beat user roots; builtin is last (no legacy equivalent).
    _LEGACY_RANK = {
        "project": 0,
        "add_dir": 1,
        "user": 2,
        "admin": 3,
        "builtin": 4,
    }

    ordered = sorted(
        candidates,
        key=lambda c: (
            _LEGACY_RANK.get(c.source.scope, 99),
            c.descriptor.name,
        ),
    )
    registry = SkillRegistry()
    for candidate in ordered:
        if registry.get(candidate.descriptor.name) is not None:
            continue
        skill = Skill(
            name=candidate.descriptor.name,
            description=candidate.descriptor.description,
            instructions="",  # body is not stored on the candidate
            root=candidate.descriptor.root_path,
            resources=(),
            source_id=candidate.source.source_id,
            skill_root=candidate.descriptor.root_path,
            sha256=candidate.descriptor.content_digest,
        )
        registry.register(skill)
    return registry


# ---------------------------------------------------------------------------
# Agent Skills standard validator
# ---------------------------------------------------------------------------

_REQUIRED_FRONTMATTER = ("name", "description")


def validate_agents_frontmatter(
    frontmatter: Mapping[str, object],
    *,
    dir_name: str | None = None,
) -> tuple[list[str], list[str]]:
    """Validate a SKILL.md frontmatter against the Agent Skills standard.

    Returns ``(errors, warnings)``.  Errors violate the standard (missing name /
    description, invalid name, name != directory name — A+ W3 hard error).
    """
    from .skill import validate_skill_name

    errors: list[str] = []
    warnings: list[str] = []

    for required in _REQUIRED_FRONTMATTER:
        if not str(frontmatter.get(required) or "").strip():
            errors.append(f"frontmatter must include `{required}`")

    name = str(frontmatter.get("name") or "").strip()
    if name:
        name_err = validate_skill_name(name)
        if name_err:
            errors.append(name_err)
        elif dir_name is not None and name != dir_name:
            errors.append(
                f"frontmatter name {name!r} does not match directory {dir_name!r}"
            )

    return errors, warnings


def validate_agents_skill_dir(skill_dir: str | Path) -> tuple[list[str], list[str]]:
    """Validate a skill directory against the Agent Skills standard.

    Reads ``SKILL.md`` and runs ``validate_agents_frontmatter``.  Returns
    ``(errors, warnings)``.  A missing or unparseable ``SKILL.md`` is an error.
    """
    from .skill import parse_skill_md

    root = Path(skill_dir).expanduser().resolve()
    skill_md = root / "SKILL.md"
    if not skill_md.exists():
        return [f"missing SKILL.md: {root}"], []
    try:
        frontmatter, _body = parse_skill_md(skill_md.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - surface any parse failure
        return [f"cannot parse SKILL.md: {exc}"], []
    return validate_agents_frontmatter(frontmatter, dir_name=root.name)
