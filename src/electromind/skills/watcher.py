"""SKILL-7: skill-root watcher with debounce and generation freeze.

``SkillWatcher`` watches the known skill roots via a ``SkillCatalogService``:

- **Debounce**: filesystem events within a quiet window are coalesced.
- **Fingerprint dedup**: ``service.reload()`` only bumps the generation when
  the content actually changed, so repeated events never double-bump.
- **Run freeze**: the current run keeps its frozen catalog; only the *next*
  run sees the new generation (RFC section 八) — the watcher only updates the
  shared catalog, never an in-flight run's view.

Nested monorepo discovery (RFC SKILL-7): when the agent actually enters a
subproject, its path is added to ``ContextRoots`` and discovery re-checks the
fixed skill dirs on that path chain — without scanning the whole monorepo.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from .catalog_service import SkillCatalogService
from .scopes import STANDARD_SKILL_DIRS, discover_candidate_sources


@dataclass
class ContextRoot:
    """A nested subproject the agent actually entered (SKILL-7)."""

    path: Path
    added_at: float = field(default_factory=time.time)


class ContextRoots:
    """Tracks nested subproject paths for on-demand discovery.

    Only paths the agent actually entered are added — no monorepo-wide scan
    (RFC section 十: 动态嵌套发现按需进行).
    """

    def __init__(self) -> None:
        self._roots: dict[str, ContextRoot] = {}

    def add(self, path: str | Path) -> None:
        resolved = Path(path).expanduser().resolve()
        self._roots[str(resolved)] = ContextRoot(path=resolved)

    def remove(self, path: str | Path) -> None:
        resolved = Path(path).expanduser().resolve()
        self._roots.pop(str(resolved), None)

    def paths(self) -> tuple[Path, ...]:
        return tuple(sorted(r.path for r in self._roots.values()))

    def __len__(self) -> int:
        return len(self._roots)


class SkillWatcher:
    """Poll-based watcher with debounce and fingerprint-dedup reloads.

    Args:
        service: The shared catalog service to refresh.
        interval: Poll interval in seconds.
        debounce: Quiet window (seconds) before a reload is committed.
        on_reloaded: Called with the new catalog after a content change.
    """

    def __init__(
        self,
        service: SkillCatalogService,
        *,
        interval: float = 1.0,
        debounce: float = 0.5,
        on_reloaded: Callable | None = None,
    ) -> None:
        self.service = service
        self.interval = interval
        self.debounce = debounce
        self.on_reloaded = on_reloaded
        self.context_roots = ContextRoots()

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_change_seen: float | None = None
        self.reload_count = 0

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Start the watcher thread (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="skill-watcher", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the watcher thread (idempotent)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # -- poll loop --------------------------------------------------------

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                # A failed poll must not kill the watcher.
                pass
            time.sleep(self.interval)

    def _tick(self) -> None:
        """One poll: detect change, debounce, reload with fingerprint dedup.

        Debounce semantics: the quiet window is measured from the FIRST
        detection of a change — continuous changes do not reset the timer.
        The commit happens once ``debounce`` seconds have passed; content-
        based fingerprint dedup inside ``service.reload()`` guarantees the
        generation bumps at most once per real content change.
        """
        changed = self._detect_change()
        now = time.time()
        with self._lock:
            if changed:
                if self._last_change_seen is None:
                    self._last_change_seen = now
                if now - self._last_change_seen >= self.debounce:
                    self._last_change_seen = None
                    commit = True
                else:
                    commit = False
            else:
                self._last_change_seen = None
                commit = False

        if not commit:
            return

        catalog = self.service.reload()
        self.reload_count += 1
        if self.on_reloaded is not None:
            self.on_reloaded(catalog)

    def _detect_change(self) -> bool:
        """Fingerprint-based change detection (dedup by content)."""
        return self.service.changed()

    def poll_once(self) -> bool:
        """Synchronous single-tick for tests (returns whether a reload happened)."""
        before = self.reload_count
        self._tick()
        return self.reload_count > before


# ---------------------------------------------------------------------------
# Context-root-aware discovery (nested monorepo, on-demand)
# ---------------------------------------------------------------------------


def discover_with_context_roots(
    service: SkillCatalogService,
    context_roots: Sequence[Path],
) -> tuple:
    """Discover sources including nested *context_roots*.

    The base discovery runs with the main project; every context root is
    additionally checked for the fixed skill dirs (``.electromind/skills``,
    ``.agents/skills``, ``.claude/skills``) — never a full-tree scan.
    """
    sources = list(
        discover_candidate_sources(
            service.project_path,
            cwd=str(service.cwd),
            configured_roots=service.configured_roots,
            user_home=service.user_home,
            admin_root=service.admin_root,
        )
    )

    import hashlib

    from .candidate import SkillSource
    from .scopes import DIALECT_BY_DIR

    for ctx in context_roots:
        for dir_name in STANDARD_SKILL_DIRS:
            root = ctx / dir_name / "skills"
            if root.is_dir():
                h = hashlib.sha256(root.as_posix().encode("utf-8")).hexdigest()[:12]
                sources.append(
                    SkillSource(
                        source_id=f"project-{DIALECT_BY_DIR[dir_name]}-{h}",
                        scope="project",
                        dialect=DIALECT_BY_DIR[dir_name],  # type: ignore[arg-type]
                        root=root,
                        project_root=ctx,
                        distance_from_cwd=0,
                        trust_domain=str(ctx),
                        read_only=False,
                    )
                )
    return tuple(sources)
