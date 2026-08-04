"""SKILL-3: multi-candidate Skill catalog and resolver.

Replaces the single-value ``SkillRegistry`` core with a candidate-based catalog:

- ``MultiCandidateCatalog`` keeps **every** same-name candidate (no first-wins
  dropping), indexed by qualified id and by name.
- ``SkillResolver`` applies different policies per invocation scenario
  (RFC section 四): qualified explicit, unqualified explicit (interactive /
  non-interactive), model implicit, and the ``/skills`` picker.
- ``SkillResolutionAmbiguous`` surfaces ambiguity instead of silently choosing.
- Catalog budget (RFC section 十一) renders the model-visible catalog within a
  char budget with visible diagnostics.
- Overrides (RFC section 十一) control enabled state and default resolution
  without touching source files.
- Generation snapshots persist the catalog metadata (no private bodies) for
  run-freeze and recovery (RFC section 七/八).

This module is additive: the legacy ``SkillRegistry`` path stays untouched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from .candidate import SkillCandidate
from .snapshot import hash_content

# Enabled states a *user* may invoke directly (RFC section 二/四).
_USER_INVOCABLE = ("on", "name_only", "manual_only")
# Enabled states the *model* may discover implicitly (RFC section 四 #3).
_MODEL_VISIBLE = ("on", "name_only")
# Valid override state values (RFC section 十一).
_VALID_OVERRIDE_STATES = ("on", "name_only", "manual_only", "off")

# Default model-catalog budget when the context window is unknown
# (RFC section 十一).
DEFAULT_BUDGET_CHARS = 8000


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MultiCandidateCatalog:
    """An immutable, content-addressed catalog of every discovered candidate.

    Attributes:
        generation: Monotonically increasing generation this catalog belongs to.
        cwd: Working directory at discovery time.
        repo_root: Repo root at discovery time, or ``None``.
        candidates: ALL candidates, including shadowed/disabled/untrusted ones.
        source_fingerprints: ``source_id -> fingerprint`` for change detection.
        catalog_digest: SHA-256 over candidate identities + states + fingerprints.
        created_at: ISO timestamp of catalog construction.
        frozen_bodies: ``skill_id -> body`` captured at catalog construction.
            Activation consumes ONLY these bodies (run-freeze guarantee); the
            live SKILL.md files are never re-read mid-run.  Bodies live in
            memory only — ``save_catalog_snapshot`` never persists them.
            ``None`` means "freeze now from source"; an explicit empty mapping
            (snapshot restore) keeps bodies empty — the source is never
            re-read for restored catalogs.
        frozen_resources: ``skill_id -> ((rel_path, bytes), ...)`` captured at
            catalog construction (P0-2).  Activation snapshots are built ONLY
            from these frozen bytes — a resource modified after discovery is
            never consumed by the current generation.  Memory only, like
            ``frozen_bodies``; ``None`` means "freeze now from source".
        resolution: Validated default-resolution pins (RFC section 十一),
            carried by the frozen catalog so every downstream consumer
            (activation service, resolvers) shares the SAME map without
            callers re-passing it by hand.
        schema_version: Snapshot schema / digest-algorithm version.  v2 =
            digest covers policy metadata (compatibility,
            disable_model_invocation); v1 = legacy digest (identity + state
            only).  Snapshots written before ``schema_version`` existed load
            as v1.
    """

    generation: int
    cwd: str
    repo_root: str | None
    candidates: tuple[SkillCandidate, ...]
    source_fingerprints: Mapping[str, str] = field(default_factory=dict)
    catalog_digest: str = ""
    created_at: str = ""
    frozen_bodies: Mapping[str, str] | None = None
    frozen_resources: Mapping[str, tuple[tuple[str, bytes], ...]] | None = None
    resolution: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = 2

    def __post_init__(self) -> None:
        if not self.catalog_digest:
            object.__setattr__(self, "catalog_digest", _catalog_digest(self.candidates))
        # Freeze bodies at construction unless explicitly provided (e.g.
        # snapshot restore passes an explicit empty mapping to avoid re-reading
        # possibly-changed source files).
        if self.frozen_bodies is None:
            object.__setattr__(self, "frozen_bodies", _freeze_bodies(self.candidates))
        # P0-2: freeze resource bytes at construction — activation snapshots
        # must never re-read live resource files mid-run.
        if self.frozen_resources is None:
            object.__setattr__(
                self, "frozen_resources", _freeze_resources(self.candidates)
            )

    # -- indexes ---------------------------------------------------------

    @property
    def registry(self):
        """Legacy ``SkillRegistry`` facade (phase-2 migration).

        Rebuilds a first-wins registry from the candidates so legacy callers
        (``snapshot.registry.names()``, ``.get()``, ``.list()``) keep working
        while the runtime moves to the candidate model.  Marked deprecated;
        new code should consume ``candidates``.
        """
        from .candidate import registry_from_candidates

        return registry_from_candidates(self.candidates)

    @property
    def fingerprint(self) -> str:
        """Legacy alias for the content-addressed catalog digest."""
        return self.catalog_digest

    @property
    def diagnostics(self) -> tuple:
        """Legacy view: all candidate diagnostics flattened."""

        diags: list = []
        for c in self.candidates:
            diags.extend(c.diagnostics)
        return tuple(diags)

    def by_qualified_id(self) -> dict[str, SkillCandidate]:
        """Index candidates by qualified skill id (exact match)."""
        return {c.skill_id: c for c in self.candidates}

    def by_name(self) -> dict[str, list[SkillCandidate]]:
        """Index candidates by name, preserving catalog order."""
        by_name: dict[str, list[SkillCandidate]] = {}
        for candidate in self.candidates:
            by_name.setdefault(candidate.descriptor.name, []).append(candidate)
        return by_name

    def names(self) -> list[str]:
        """All distinct candidate names, sorted."""
        return sorted({c.descriptor.name for c in self.candidates})

    def shadowed(self) -> tuple[SkillCandidate, ...]:
        """Candidates shadowed by a higher-priority same-name candidate.

        A candidate is shadowed when an earlier candidate (in catalog order —
        already source-priority sorted) shares its name.  Shadowed candidates
        stay in the catalog for the picker but never enter the model catalog.
        """
        seen: set[str] = set()
        shadowed: list[SkillCandidate] = []
        for candidate in self.candidates:
            if candidate.descriptor.name in seen:
                shadowed.append(candidate)
            else:
                seen.add(candidate.descriptor.name)
        return tuple(shadowed)

    # -- picker ----------------------------------------------------------

    def all_candidates_for_picker(self) -> tuple[SkillCandidate, ...]:
        """Every candidate, regardless of state/trust (RFC section 四 #4)."""
        return self.candidates


def _catalog_digest(candidates: Sequence[SkillCandidate]) -> str:
    """Content-addressed hash over candidate identity + state."""
    parts: list[str] = []
    for c in candidates:
        parts.append(
            f"{c.skill_id}|{c.source.scope}|{c.source.dialect}|"
            f"{c.descriptor.content_digest}|{c.enabled_state}|{c.trust_state}|"
            f"{c.descriptor.compatibility}|{c.descriptor.disable_model_invocation}"
        )
    return hash_content(*parts)


def _freeze_bodies(candidates: Sequence[SkillCandidate]) -> dict[str, str]:
    """Freeze each candidate's SKILL.md body at catalog construction.

    Reads the body once from disk at discovery time.  Activation must consume
    ONLY these frozen bodies (run-freeze guarantee) — never a live re-read of
    possibly-changed source files.
    """
    from .skill import parse_skill_md

    bodies: dict[str, str] = {}
    for candidate in candidates:
        entry = candidate.descriptor.entry_path
        try:
            if entry.is_file():
                _fm, body = parse_skill_md(entry.read_text(encoding="utf-8"))
                bodies[candidate.skill_id] = body.strip()
        except OSError:
            continue
    return bodies


def _freeze_resources(
    candidates: Sequence[SkillCandidate],
) -> dict[str, tuple[tuple[str, bytes], ...]]:
    """Freeze each candidate's resource bytes at catalog construction (P0-2).

    Activation snapshots are built ONLY from these frozen bytes — a resource
    modified after discovery is never consumed by the current generation
    (TOCTOU closure).  Memory only, like ``frozen_bodies``.
    """
    from .skill import collect_resources

    frozen: dict[str, tuple[tuple[str, bytes], ...]] = {}
    for candidate in candidates:
        root = candidate.descriptor.root_path
        if not root.is_dir():
            continue
        items: list[tuple[str, bytes]] = []
        for rel in sorted(collect_resources(root)):
            try:
                items.append((rel, (root / rel).read_bytes()))
            except OSError:
                continue
        frozen[candidate.skill_id] = tuple(items)
    return frozen


def build_catalog(
    candidates: Sequence[SkillCandidate],
    *,
    generation: int,
    cwd: str | Path | None = None,
    repo_root: str | Path | None = None,
    source_fingerprints: Mapping[str, str] | None = None,
    created_at: str = "",
    frozen_bodies: Mapping[str, str] | None = None,
    frozen_resources: Mapping[str, tuple[tuple[str, bytes], ...]] | None = None,
    resolution: Mapping[str, str] | None = None,
) -> MultiCandidateCatalog:
    """Build a ``MultiCandidateCatalog`` from candidates.

    Candidates are assumed to arrive in source-priority order (see
    ``scopes.discover_candidate_sources``); the catalog preserves that order
    verbatim — the resolver decides winners per scenario.

    The catalog freezes each candidate's SKILL.md body (``frozen_bodies``)
    and resource bytes (``frozen_resources``, P0-2) at construction;
    activations read only these frozen contents.  Validated default-resolution
    pins (``resolution``) are carried by the catalog so downstream consumers
    share one map.
    """
    import os

    return MultiCandidateCatalog(
        generation=generation,
        cwd=str(cwd or os.getcwd()),
        repo_root=str(repo_root) if repo_root is not None else None,
        candidates=tuple(candidates),
        source_fingerprints=dict(source_fingerprints or {}),
        created_at=created_at or "",
        frozen_bodies=(dict(frozen_bodies) if frozen_bodies is not None else None),
        frozen_resources=(
            dict(frozen_resources) if frozen_resources is not None else None
        ),
        resolution=dict(resolution or {}),
    )


# ---------------------------------------------------------------------------
# Resolution results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolvedSkill:
    """The outcome of a successful resolution (RFC section 二)."""

    candidate: SkillCandidate
    resolution_reason: str
    catalog_generation: int
    catalog_digest: str


class SkillResolutionAmbiguous(Exception):
    """Ambiguity item: a name maps to multiple candidates of the same level.

    Produced instead of silently picking one (RFC section 四 #2/#3).  Raised
    for explicit invocations (caller shows the picker or fails); returned as a
    value by ``resolve_implicit`` (model invocation never guesses).
    """

    def __init__(
        self,
        name: str,
        candidates: tuple[SkillCandidate, ...] = (),
        reason: str = "ambiguous skill name",
        *,
        requires_qualified_id: bool = False,
    ) -> None:
        super().__init__(reason)
        self.name = name
        self.candidates = candidates
        self.reason = reason
        self.requires_qualified_id = requires_qualified_id


class SkillResolutionError(Exception):
    """A resolution that cannot succeed (unknown / disabled / untrusted)."""

    def __init__(self, message: str, *, needs_trust: bool = False) -> None:
        super().__init__(message)
        self.needs_trust = needs_trust


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class SkillResolver:
    """Resolves candidates per invocation scenario (RFC section 四)."""

    def __init__(
        self,
        catalog: MultiCandidateCatalog,
        resolution: Mapping[str, str] | None = None,
    ) -> None:
        self.catalog = catalog
        self._by_qualified = catalog.by_qualified_id()
        # Default resolution pins: ``{name: qualified_id}`` (RFC section 十一).
        self._resolution = dict(resolution or {})

    def _pinned(self, name: str) -> SkillCandidate | None:
        """Return the pinned candidate for *name*, or ``None``."""
        pinned_id = self._resolution.get(name)
        if pinned_id is None:
            return None
        return self._by_qualified.get(pinned_id)

    # -- 1. qualified explicit invocation --------------------------------

    def resolve_qualified(
        self,
        skill_id: str,
        *,
        capabilities: Sequence[str] = (),
        allow_disabled: bool = False,
    ) -> ResolvedSkill:
        """Resolve by exact qualified id — no name-priority selection.

        Raises ``SkillResolutionError`` for unknown / disabled / untrusted /
        capability-incompatible ids.
        """
        candidate = self._by_qualified.get(skill_id)
        if candidate is None:
            raise SkillResolutionError(f"unknown qualified skill id: {skill_id}")
        self._check_invocable(candidate, capabilities, allow_disabled=allow_disabled)
        return ResolvedSkill(
            candidate=candidate,
            resolution_reason=f"qualified id match: {skill_id}",
            catalog_generation=self.catalog.generation,
            catalog_digest=self.catalog.catalog_digest,
        )

    # -- 2. unqualified explicit invocation ------------------------------

    def resolve_unqualified(
        self,
        name: str,
        *,
        interactive: bool,
        capabilities: Sequence[str] = (),
    ) -> ResolvedSkill:
        """Resolve by name when the user invoked it explicitly.

        - exactly one usable candidate → resolve
        - multiple usable candidates:
          - interactive → raise ``SkillResolutionAmbiguous`` (caller shows picker)
          - non-interactive → raise ``SkillResolutionAmbiguous`` with
            ``requires_qualified_id=True`` (explicit failure, no silent pick)
        - no usable candidate → ``SkillResolutionError``
        """
        pinned = self._pinned(name)
        if pinned is not None:
            if pinned.enabled_state == "off":
                raise SkillResolutionError(f"skill {pinned.skill_id} is disabled")
            if pinned.trust_state != "trusted":
                raise SkillResolutionError(
                    f"skill {pinned.skill_id} is untrusted; trust the workspace first",
                    needs_trust=True,
                )
            if not _compatible(pinned, capabilities):
                raise SkillResolutionError(
                    f"skill {pinned.skill_id} is incompatible with "
                    f"run capabilities {list(capabilities)}"
                )
            return ResolvedSkill(
                candidate=pinned,
                resolution_reason=f"resolution pin for {name!r}",
                catalog_generation=self.catalog.generation,
                catalog_digest=self.catalog.catalog_digest,
            )
        usable = self._usable(name, capabilities)
        if not usable:
            raise SkillResolutionError(
                f"no usable skill for {name!r} (unknown, disabled, or untrusted)"
            )
        if len(usable) == 1:
            candidate = usable[0]
            return ResolvedSkill(
                candidate=candidate,
                resolution_reason=(
                    f"unique candidate for {name!r} in "
                    f"{candidate.source.scope}/{candidate.source.dialect}"
                ),
                catalog_generation=self.catalog.generation,
                catalog_digest=self.catalog.catalog_digest,
            )
        if interactive:
            raise SkillResolutionAmbiguous(
                name=name,
                candidates=tuple(usable),
                reason=f"{len(usable)} usable candidates for {name!r}",
                requires_qualified_id=False,
            )
        raise SkillResolutionAmbiguous(
            name=name,
            candidates=tuple(usable),
            reason=(
                f"{len(usable)} candidates for {name!r}; "
                "use a qualified skill id in non-interactive mode"
            ),
            requires_qualified_id=True,
        )

    # -- 3. model implicit invocation ------------------------------------

    def resolve_implicit(
        self,
        name: str,
        *,
        capabilities: Sequence[str] = (),
    ) -> ResolvedSkill | SkillResolutionAmbiguous:
        """Resolve for the model's implicit invocation.

        Considers only model-visible (on/name_only), trusted, capability-
        compatible candidates, then takes the **top priority tier**
        (RFC section 四 #3):

        - a unique candidate in the top tier → ``ResolvedSkill``
        - several candidates in the same top tier → ``SkillResolutionAmbiguous``
        - no candidate → ``SkillResolutionAmbiguous``

        Never triggers a Workspace Trust dialog: untrusted candidates simply
        don't resolve.
        """
        from .scopes import source_rank

        pinned = self._pinned(name)
        if pinned is not None:
            if (
                pinned.enabled_state in _MODEL_VISIBLE
                and pinned.trust_state == "trusted"
                and not pinned.descriptor.disable_model_invocation
                and _compatible(pinned, capabilities)
            ):
                return ResolvedSkill(
                    candidate=pinned,
                    resolution_reason=f"resolution pin for {name!r}",
                    catalog_generation=self.catalog.generation,
                    catalog_digest=self.catalog.catalog_digest,
                )

        visible = [
            c
            for c in self.catalog.candidates
            if c.descriptor.name == name
            and c.enabled_state in _MODEL_VISIBLE
            and c.trust_state == "trusted"
            and not c.descriptor.disable_model_invocation
            and _compatible(c, capabilities)
        ]
        if not visible:
            return SkillResolutionAmbiguous(
                name=name,
                candidates=(),
                reason="no model-visible candidate (unknown, untrusted, or disabled)",
            )

        # Top priority tier — a lower-priority candidate must not make the
        # top candidate ambiguous (RFC section 三: Source Priority ≠ trust,
        # and the highest-priority candidate wins unless tied at the same
        # level).
        top_rank = min(source_rank(c.source) for c in visible)
        top_tier = [c for c in visible if source_rank(c.source) == top_rank]

        if len(top_tier) == 1:
            candidate = top_tier[0]
            return ResolvedSkill(
                candidate=candidate,
                resolution_reason=(
                    f"unique top-priority model-visible candidate in "
                    f"{candidate.source.scope}/{candidate.source.dialect}"
                ),
                catalog_generation=self.catalog.generation,
                catalog_digest=self.catalog.catalog_digest,
            )
        # Same-level ambiguity — never guess.
        return SkillResolutionAmbiguous(
            name=name,
            candidates=tuple(top_tier),
            reason=(
                f"{len(top_tier)} same-level model-visible candidates for {name!r}"
            ),
        )

    # -- 4. picker -------------------------------------------------------

    def picker_candidates(self) -> tuple[SkillCandidate, ...]:
        """All candidates for the ``/skills`` picker (no filtering)."""
        return self.catalog.all_candidates_for_picker()

    # -- helpers ---------------------------------------------------------

    def _usable(
        self, name: str, capabilities: Sequence[str]
    ) -> tuple[SkillCandidate, ...]:
        """Candidates a *user* may invoke directly (trusted + invocable)."""
        return tuple(
            c
            for c in self.catalog.candidates
            if c.descriptor.name == name
            and c.enabled_state in _USER_INVOCABLE
            and c.trust_state == "trusted"
            and _compatible(c, capabilities)
        )

    def _check_invocable(
        self,
        candidate: SkillCandidate,
        capabilities: Sequence[str],
        *,
        allow_disabled: bool,
    ) -> None:
        if not allow_disabled and candidate.enabled_state == "off":
            raise SkillResolutionError(f"skill {candidate.skill_id} is disabled")
        if candidate.trust_state != "trusted":
            raise SkillResolutionError(
                f"skill {candidate.skill_id} is untrusted; trust the workspace first",
                needs_trust=True,
            )
        if not _compatible(candidate, capabilities):
            raise SkillResolutionError(
                f"skill {candidate.skill_id} is incompatible with "
                f"run capabilities {list(capabilities)}"
            )


def _compatible(candidate: SkillCandidate, capabilities: Sequence[str]) -> bool:
    """Whether *candidate* may run under the current run capabilities.

    An empty ``compatibility`` tuple means no declared restriction.
    """
    declared = candidate.descriptor.compatibility
    if not declared:
        return True
    if not capabilities:
        return True
    return any(cap in declared for cap in capabilities)


# ---------------------------------------------------------------------------
# Catalog budget (RFC section 十一)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CatalogBudgetEntry:
    """One entry of the model-visible catalog within budget."""

    skill_id: str
    name: str
    description: str
    source_label: str
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class CatalogBudgetResult:
    """Budgeted model catalog plus visible diagnostics (RFC section 十一)."""

    entries: tuple[CatalogBudgetEntry, ...]
    diagnostics: tuple[str, ...]
    total_chars: int
    budget: int


def _source_label(candidate: SkillCandidate) -> str:
    """Short ``scope/dialect`` source label for the model catalog."""
    return f"{candidate.source.scope}/{candidate.source.dialect}"


def build_model_catalog(
    catalog: MultiCandidateCatalog,
    *,
    budget: int = DEFAULT_BUDGET_CHARS,
) -> CatalogBudgetResult:
    """Render the model-visible catalog within *budget* characters.

    Order of trimming (RFC section 十一):

    1. ``manual_only`` candidates never enter.
    2. Shadowed candidates never enter the implicit catalog.
    3. Lower-priority descriptions are compressed (truncated).
    4. ``name_only`` candidates keep only their name.
    5. If still over budget, entries are omitted with visible diagnostics.
    """
    diagnostics: list[str] = []
    entries: list[CatalogBudgetEntry] = []

    for candidate in catalog.candidates:
        name = candidate.descriptor.name
        if candidate.enabled_state in ("manual_only", "off"):
            continue
        if candidate.trust_state != "trusted":
            continue
        if candidate.descriptor.disable_model_invocation:
            # RFC section 四 #3: the model may not discover Skills that opt
            # out of implicit invocation — the user still can.
            continue
        if name in {e.name for e in entries}:
            # shadowed: a higher-priority candidate already entered
            continue

        if candidate.enabled_state == "name_only":
            entries.append(
                CatalogBudgetEntry(
                    skill_id=candidate.skill_id,
                    name=name,
                    description="",
                    source_label=_source_label(candidate),
                )
            )
        else:
            entries.append(
                CatalogBudgetEntry(
                    skill_id=candidate.skill_id,
                    name=name,
                    description=candidate.descriptor.description,
                    source_label=_source_label(candidate),
                )
            )

    # Truncate descriptions until under budget; then omit entries.
    total = _entries_chars(entries)
    if total > budget and entries:
        # 1. compress descriptions — per-entry share of the budget
        per_entry = max(24, budget // len(entries))
        truncated: list[CatalogBudgetEntry] = []
        for entry in entries:
            if entry.description and len(entry.description) > per_entry:
                truncated.append(_truncate_entry(entry, per_entry))
            else:
                truncated.append(entry)
        entries = truncated
        total = _entries_chars(entries)

    # 2. omit lowest-priority entries while still over budget
    while total > budget and entries:
        dropped = entries.pop()
        diagnostics.append(
            f"catalog budget exceeded: omitted {dropped.name!r} "
            f"({dropped.source_label})"
        )
        total = _entries_chars(entries)

    return CatalogBudgetResult(
        entries=tuple(entries),
        diagnostics=tuple(diagnostics),
        total_chars=total,
        budget=budget,
    )


def _entries_chars(entries: Sequence[CatalogBudgetEntry]) -> int:
    return sum(
        len(e.skill_id) + len(e.name) + len(e.description) + len(e.source_label)
        for e in entries
    )


def _truncate_entry(entry: CatalogBudgetEntry, max_len: int) -> CatalogBudgetEntry:
    if entry.description and len(entry.description) > max_len:
        return CatalogBudgetEntry(
            skill_id=entry.skill_id,
            name=entry.name,
            description=entry.description[: max_len - 3] + "...",
            source_label=entry.source_label,
            truncated=True,
        )
    return entry


# ---------------------------------------------------------------------------
# Overrides (RFC section 十一)
# ---------------------------------------------------------------------------


def apply_overrides(
    candidates: Sequence[SkillCandidate],
    overrides: Mapping[str, Mapping[str, str]],
    resolution: Mapping[str, str] | None = None,
) -> tuple[tuple[SkillCandidate, ...], dict[str, str], list[str]]:
    """Apply ``[skills.overrides]`` and ``[skills.resolution]`` config.

    Args:
        candidates: Catalog candidates.
        overrides: ``{qualified_id: {"state": on|name_only|manual_only|off}}``.
        resolution: ``{name: qualified_id}`` default resolution pins.

    Returns:
        ``(updated_candidates, resolution_map, diagnostics)``.  Only the
        enabled state is changed here; source files are never modified.
    """
    from dataclasses import replace

    diagnostics: list[str] = []
    updated: list[SkillCandidate] = []
    resolution_map = dict(resolution or {})

    for candidate in candidates:
        override = overrides.get(candidate.skill_id)
        if override is not None:
            state = override.get("state")
            if state not in _VALID_OVERRIDE_STATES:
                diagnostics.append(
                    f"invalid override state {state!r} for {candidate.skill_id}"
                )
                updated.append(candidate)
                continue
            updated.append(replace(candidate, enabled_state=state))  # type: ignore[arg-type]
        else:
            updated.append(candidate)

    # Validate resolution pins resolve to a real qualified id.
    known = {c.skill_id for c in updated}
    for name, skill_id in resolution_map.items():
        if skill_id not in known:
            diagnostics.append(
                f"resolution pin {name!r} → {skill_id!r} does not match any candidate"
            )

    return tuple(updated), resolution_map, diagnostics


# ---------------------------------------------------------------------------
# Generation snapshot persistence (metadata only — no private bodies)
# ---------------------------------------------------------------------------


def save_catalog_snapshot(catalog: MultiCandidateCatalog, path: str | Path) -> None:
    """Persist the catalog metadata (RFC section 七/八).

    Never writes instruction bodies or resource content — only identities,
    digests, states, policy metadata (resolution pins, compatibility,
    disable-model-invocation), and source metadata, so exports stay safe
    AND a restored catalog behaves identically to the original.
    """
    payload = {
        "schema_version": catalog.schema_version,
        "generation": catalog.generation,
        "cwd": catalog.cwd,
        "repo_root": catalog.repo_root,
        "catalog_digest": catalog.catalog_digest,
        "created_at": catalog.created_at,
        "source_fingerprints": dict(catalog.source_fingerprints),
        "resolution": dict(catalog.resolution),
        "candidates": [
            {
                "skill_id": c.skill_id,
                "name": c.descriptor.name,
                "description": c.descriptor.description,
                "content_digest": c.descriptor.content_digest,
                "resource_digest": c.descriptor.resource_digest,
                "compatibility": list(c.descriptor.compatibility),
                "disable_model_invocation": c.descriptor.disable_model_invocation,
                "enabled_state": c.enabled_state,
                "trust_state": c.trust_state,
                "scope": c.source.scope,
                "dialect": c.source.dialect,
                "source_id": c.source.source_id,
                "source_root": str(c.source.root),
            }
            for c in catalog.candidates
        ],
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_catalog_snapshot(path: str | Path) -> MultiCandidateCatalog:
    """Load a catalog snapshot persisted by ``save_catalog_snapshot``.

    Restores candidate *metadata* (identity, digests, states).  Instruction
    bodies are not stored in snapshots; they are recovered from the private
    snapshot store (SKILL-4) or re-read from the source on activation.
    """
    from .candidate import SkillDescriptor, SkillSource

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    candidates: list[SkillCandidate] = []
    for item in payload["candidates"]:
        source = SkillSource(
            source_id=item["source_id"],
            scope=item["scope"],  # type: ignore[arg-type]
            dialect=item["dialect"],  # type: ignore[arg-type]
            root=Path(item["source_root"]),
        )
        descriptor = SkillDescriptor(
            name=item["name"],
            description=item["description"],
            entry_path=Path(item["source_root"]) / "SKILL.md",
            root_path=Path(item["source_root"]),
            frontmatter={"name": item["name"], "description": item["description"]},
            content_digest=item["content_digest"],
            resource_digest=item["resource_digest"],
            # Policy metadata — backward-compatible defaults for snapshots
            # written before these fields existed (RFC section 二/四).
            compatibility=tuple(item.get("compatibility", ())),
            disable_model_invocation=bool(item.get("disable_model_invocation", False)),
        )
        candidates.append(
            SkillCandidate(
                skill_id=item["skill_id"],
                descriptor=descriptor,
                source=source,
                enabled_state=item["enabled_state"],  # type: ignore[arg-type]
                trust_state=item["trust_state"],  # type: ignore[arg-type]
            )
        )

    return MultiCandidateCatalog(
        generation=payload["generation"],
        cwd=payload["cwd"],
        repo_root=payload["repo_root"],
        candidates=tuple(candidates),
        source_fingerprints=payload["source_fingerprints"],
        catalog_digest=payload["catalog_digest"],
        created_at=payload["created_at"],
        # Snapshot restore never re-reads source files — bodies and resources
        # stay empty (RFC section 七: restore prefers the SnapshotRef, not
        # live files; P0-2 keeps resources frozen the same way).
        frozen_bodies={},
        frozen_resources={},
        resolution=dict(payload.get("resolution", {})),
        # Snapshots written before schema_version existed are v1 (legacy
        # digest algorithm without policy metadata).
        schema_version=int(payload.get("schema_version", 1)),
    )
