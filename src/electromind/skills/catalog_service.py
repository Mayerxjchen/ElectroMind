"""SKILL-6: process-wide shared Skill catalog service.

CLI, Desktop, and the HTTP service all read from **one** catalog instance so
they stop scanning skill directories independently (RFC completion condition).

``SkillCatalogService`` owns:

- the current ``MultiCandidateCatalog`` (a single Generation fact source);
- ``reload()`` — re-discovers; content changes bump the generation;
- ``changed()`` — fingerprint-based change detection for watchers/clients;
- ``list()/get()`` — shared views for CLI / wire / desktop.

The service is a process-level singleton; tests inject their own instance.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .candidate import SkillCandidate
from .catalog import MultiCandidateCatalog, build_catalog
from .scopes import (
    discover_candidate_sources,
    fingerprint_source,
    load_candidates,
)

# Cap on reload generations to avoid unbounded growth in long-lived services.
_MAX_GENERATIONS = 1_000_000


class SkillCatalogService:
    """Shared catalog with generation semantics (RFC section 八)."""

    def __init__(
        self,
        *,
        project_path: str | Path | None = None,
        cwd: str | Path | None = None,
        configured_roots: Sequence[str | Path] = (),
        user_home: Path | None = None,
        admin_root: str | Path | None = None,
        builtin_roots: Sequence[str | Path] | None = None,
        is_project_trusted: Callable[[Path | None], bool] | None = None,
        on_reloaded: Callable[[MultiCandidateCatalog], None] | None = None,
        overrides: Mapping[str, Mapping[str, str]] | None = None,
        resolution: Mapping[str, str] | None = None,
    ) -> None:
        self.project_path = project_path
        self.cwd = Path(cwd or os.getcwd())
        self.configured_roots = tuple(configured_roots)
        self.user_home = user_home
        self.admin_root = admin_root
        self.builtin_roots = tuple(builtin_roots) if builtin_roots is not None else None
        self.is_project_trusted = is_project_trusted
        self.on_reloaded = on_reloaded
        # RFC section 十一: state overrides + default-resolution pins.
        self.overrides = dict(overrides or {})
        self.resolution = dict(resolution or {})

        self._lock = threading.Lock()
        self._catalog: MultiCandidateCatalog | None = None
        self._source_fingerprints: dict[str, str] = {}
        self._last_trust_signature: tuple = ()

    # -- lifecycle --------------------------------------------------------

    def ensure_loaded(self) -> MultiCandidateCatalog:
        """Discover on first access; return the current catalog."""
        with self._lock:
            if self._catalog is None:
                self._reload_locked()
            assert self._catalog is not None
            return self._catalog

    def reload(self) -> MultiCandidateCatalog:
        """Re-discover; bump generation on content OR trust change (RFC 八).

        Same content and same trust state → same generation, same catalog.
        Content or Workspace Trust changed (e.g. untrusted → trusted while
        files are unchanged) → generation +1 and ``on_reloaded`` after commit.
        """
        with self._lock:
            old = self._catalog
            if old is None:
                return self._reload_locked()
            sources = discover_candidate_sources(
                self.project_path,
                cwd=str(self.cwd),
                configured_roots=self.configured_roots,
                user_home=self.user_home,
                admin_root=self.admin_root,
                builtin_roots=self.builtin_roots,
            )
            fingerprints = {s.source_id: fingerprint_source(s) for s in sources}
            trust_signature = self._trust_signature(sources)
            if (
                fingerprints == self._source_fingerprints
                and trust_signature == self._last_trust_signature
            ):
                return old
            new = self._reload_locked()
            self._last_trust_signature = trust_signature
            if self.on_reloaded is not None:
                self.on_reloaded(new)
            return new

    def changed(self) -> bool:
        """Whether the sources changed since the last reload.

        Re-runs discovery to compute fingerprints AND the trust signature;
        does NOT bump generation (use ``reload()`` to commit a new one).
        A Workspace-Trust flip with unchanged files still reports ``True`` so
        watchers relying on ``changed()`` refresh automatically.
        """
        if self._catalog is None:
            return True
        sources = discover_candidate_sources(
            self.project_path,
            cwd=str(self.cwd),
            configured_roots=self.configured_roots,
            user_home=self.user_home,
            admin_root=self.admin_root,
            builtin_roots=self.builtin_roots,
        )
        current = {s.source_id: fingerprint_source(s) for s in sources}
        if current != self._source_fingerprints:
            return True
        return self._trust_signature(sources) != self._last_trust_signature

    # -- views ------------------------------------------------------------

    def list(self) -> MultiCandidateCatalog:
        """Current catalog (auto-loads)."""
        return self.ensure_loaded()

    def sources(self) -> tuple:
        """The discovered source roots (auto-loads discovery)."""
        if self._catalog is None:
            self.ensure_loaded()
        return discover_candidate_sources(
            self.project_path,
            cwd=str(self.cwd),
            configured_roots=self.configured_roots,
            user_home=self.user_home,
            admin_root=self.admin_root,
            builtin_roots=self.builtin_roots,
        )

    def get(self, skill_id: str) -> SkillCandidate | None:
        """Exact qualified-id lookup in the current catalog."""
        return self.list().by_qualified_id().get(skill_id)

    def candidates(self) -> tuple[SkillCandidate, ...]:
        """All candidates (picker view — no filtering)."""
        return self.list().candidates

    # -- internals --------------------------------------------------------

    def _trust_signature(self, sources: tuple) -> tuple:
        """Per-project trust decisions — content-independent change signal.

        Workspace Trust flips (untrusted → trusted) while files are unchanged
        must still trigger a reload so the candidate trust states refresh.
        """
        if self.is_project_trusted is None:
            return ()
        signature: list[tuple] = []
        for source in sources:
            if source.scope == "project":
                signature.append(
                    (
                        source.source_id,
                        bool(self.is_project_trusted(source.project_root)),
                    )
                )
        return tuple(sorted(signature))

    def _reload_locked(self) -> MultiCandidateCatalog:
        from .catalog import apply_overrides

        sources = discover_candidate_sources(
            self.project_path,
            cwd=str(self.cwd),
            configured_roots=self.configured_roots,
            user_home=self.user_home,
            admin_root=self.admin_root,
            builtin_roots=self.builtin_roots,
        )
        candidates = load_candidates(
            sources, is_project_trusted=self.is_project_trusted
        )
        # Apply [skills.overrides] state overrides + validate the
        # default-resolution pins (RFC section 十一).  The validated pins are
        # carried by the frozen catalog so downstream consumers (activation
        # service, resolvers) share the SAME map without re-passing by hand.
        resolution_map: dict[str, str] = dict(self.resolution)
        if self.overrides or self.resolution:
            candidates, resolution_map, _diags = apply_overrides(
                candidates, self.overrides, self.resolution
            )
        generation = self._catalog.generation + 1 if self._catalog is not None else 1
        catalog = build_catalog(
            candidates,
            generation=generation,
            cwd=str(self.cwd),
            repo_root=(
                str(Path(self.project_path).resolve())
                if self.project_path is not None
                else None
            ),
            source_fingerprints={s.source_id: fingerprint_source(s) for s in sources},
            resolution=resolution_map,
        )
        self._source_fingerprints = dict(catalog.source_fingerprints)
        self._last_trust_signature = self._trust_signature(sources)
        self._catalog = catalog
        return catalog


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------

_service_lock = threading.Lock()
_service: SkillCatalogService | None = None


def get_shared_catalog_service() -> SkillCatalogService:
    """Return the process-wide shared catalog service (SKILL-6).

    The lazily-created default instance carries ``_unconfigured_default=True``
    so CLI entry points can tell "never configured" apart from a deliberately
    injected instance and reconfigure the default with cwd + trust wiring.
    """
    global _service
    with _service_lock:
        if _service is None:
            _service = SkillCatalogService()
            _service._unconfigured_default = True  # type: ignore[attr-defined]
        return _service


def set_shared_catalog_service(service: SkillCatalogService | None) -> None:
    """Replace the process-wide service (tests inject their own).

    An explicitly injected instance never carries the
    ``_unconfigured_default`` marker, so CLI entry points reuse it as-is.
    """
    global _service
    with _service_lock:
        if service is not None:
            service._unconfigured_default = False  # type: ignore[attr-defined]
        _service = service


def reset_shared_catalog_service() -> None:
    """Drop the process-wide service (test isolation)."""
    set_shared_catalog_service(None)
