"""Skill runtime: refresh skills at user-turn boundaries.

``SkillRuntime`` owns the Skill discovery/catalog lifecycle for a running
ElectroMind task.  It is created by ``BaseRunner`` and refreshed before each
user turn via ``prepare_turn()``.

Phase-2 (migration): the runtime now runs on the candidate/catalog chain
(``SkillCatalogService`` → ``MultiCandidateCatalog`` → ``SkillActivationService``)
while keeping the legacy public surface (``SkillRunView`` with a compat
``SkillRegistry`` facade) so existing callers and tests keep working.
``SkillRegistry`` itself is deprecated; new code should consume candidates.

Generation counter is monotonic and starts at 1.  Each content change produces
a new generation; runs within the same generation see frozen skill content.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from .catalog import MultiCandidateCatalog
from .catalog_service import SkillCatalogService
from .discovery import SkillMount
from .mounting import SkillMounter
from .skill import Skill, SkillRegistry, make_use_skill_tool
from .state import SkillRunView

if TYPE_CHECKING:
    from ..core.agent import AgentCore
    from ..core.tool import FunctionTool


class SkillRuntime:
    """Per-task Skill lifecycle manager.

    One instance per Runner.  Refreshed before each user turn via
    ``prepare_turn()``, which returns a frozen ``SkillRunView``.
    """

    def __init__(
        self,
        project_path: str | Path | None,
        *,
        configured_roots: Sequence[str | Path] = (),
        user_home: Path | None = None,
        is_project_trusted: Callable[[Path | None], bool] | None = None,
        resolution: dict[str, str] | None = None,
        overrides: dict[str, dict[str, str]] | None = None,
        admin_root: str | Path | None = None,
        builtin_roots: Sequence[str | Path] | None = None,
        mounter: "SkillMounter | None" = None,
        service: SkillCatalogService | None = None,
        capabilities: Sequence[str] = (),
    ) -> None:
        self.project_path: str | Path | None = project_path
        self.configured_roots: tuple[str | Path, ...] = tuple(configured_roots)
        self.user_home: Path | None = user_home
        self.mounter = mounter
        # Frozen Run capabilities: every rebuilt use_skill tool (including
        # apply_to_agent at each before_user_turn) carries the SAME
        # capabilities so capability-restricted skills stay enforced in
        # production, not just at initial assembly.
        self.capabilities: tuple[str, ...] = tuple(capabilities)

        # Phase-2: the catalog service is the single discovery source.
        # Explicitly injected (shared) service wins; otherwise build one
        # bound to this runtime's project/cwd.
        if service is not None:
            self._service = service
        else:
            self._service = SkillCatalogService(
                project_path=project_path,
                cwd=project_path or Path.cwd(),
                configured_roots=self.configured_roots,
                user_home=user_home,
                admin_root=admin_root,
                builtin_roots=builtin_roots,
                is_project_trusted=is_project_trusted,
                resolution=resolution,
                overrides=overrides,
            )

        # Current valid state
        self.snapshot: MultiCandidateCatalog | None = None
        self.mounts: dict[str, SkillMount] = {}
        self._set_snapshot: "object | None" = None  # SkillSetSnapshot

        # Generation tracking
        self._generation: int = 0  # 0 = not yet prepared
        self._current_view: SkillRunView | None = None

        # Activated skills in this task (all-time)
        self.activated: set[str] = set()
        # Activated skills in current run (reset each prepare_turn)
        self._loaded_this_run: set[str] = set()

        # Callback invoked when a skill is activated mid-run
        self._on_skill_state_change: "callable | None" = None

        # Diagnostics callback: (diagnostics) -> None
        self._on_diagnostics: "callable | None" = None

    # ── turn preparation ──────────────────────────────────────────────

    async def refresh_if_changed(self) -> bool:
        """Deprecated: use ``prepare_turn()`` instead.

        Returns ``True`` when discovery succeeds **and** produces a new
        generation (content actually changed).  Returns ``False`` when
        discovery fails or the catalog is rejected due to errors — the
        previous snapshot is preserved.

        Kept for backward compatibility with existing tests and callers.
        """
        previous_gen = self._generation
        self.prepare_turn()
        # True only when generation was bumped (content actually changed)
        return self._generation > previous_gen

    def prepare_turn(self) -> SkillRunView | None:
        """Discover, load, and pin a skill catalog for the next user turn.

        Phase-2: discovery runs through ``SkillCatalogService`` (candidates +
        trust + resolution pins).  Returns a frozen ``SkillRunView`` whose
        compat ``registry`` is rebuilt from the candidates; the view also
        carries the frozen ``MultiCandidateCatalog`` so activations consume
        exactly this generation's content.

        Returns ``None`` if discovery fails — the previous view (if any) is
        preserved.

        Generation rules:
        - First call → generation 1.
        - Same content (and same trust) → same generation, same view.
        - Content changed → generation +1, new view.
        - ``_loaded_this_run`` is cleared (new run = clean slate).
        """
        try:
            # reload() bumps the generation only on content/trust change;
            # the first call discovers generation 1.
            catalog = self._service.reload()
        except Exception:
            # Keep previous snapshot/view on failure
            return self._current_view

        # Phase-2 runtime keeps the legacy "error rejects the catalog"
        # semantics: candidates carrying error-severity diagnostics (broken
        # frontmatter, invalid names) do not enter the run view.  The
        # /skills picker (catalog_service) still shows them; the agent only
        # sees healthy candidates.
        if any(d.severity == "error" for d in catalog.diagnostics):
            return self._current_view

        # No change — reuse current generation and view
        if (
            self.snapshot is not None
            and catalog.catalog_digest == self.snapshot.catalog_digest
            and self._current_view is not None
        ):
            self._loaded_this_run = set()
            return self._current_view

        # Build the new view before mutating instance state
        new_view = self._build_view(catalog)

        # Atomic commit — all or nothing
        self.snapshot = catalog
        self._generation = catalog.generation
        self._set_snapshot = None
        self._current_view = new_view

        # Reset per-run tracking
        self._loaded_this_run = set()

        return self._current_view

    def _build_view(self, catalog: MultiCandidateCatalog) -> SkillRunView:
        """Build a compat ``SkillRunView`` from a candidate catalog."""
        from .candidate import registry_from_candidates

        registry = registry_from_candidates(catalog.candidates)
        return SkillRunView(
            generation=catalog.generation,
            digest=catalog.catalog_digest,
            registry=registry,
            mounted_roots=dict(self.mounts),
            catalog=catalog,
        )

    # ── watcher integration (SKILL-7) ─────────────────────────────────

    def attach_watcher(self, *, interval: float = 1.0, debounce: float = 0.5):
        """Start a ``SkillWatcher`` on this runtime's shared catalog service.

        Content/trust changes are detected between user turns; the current
        run keeps its frozen generation (the watcher only updates the
        shared service, and ``prepare_turn()`` picks up the new generation
        at the next user turn).
        """
        from .watcher import SkillWatcher

        watcher = SkillWatcher(
            self._service,
            interval=interval,
            debounce=debounce,
            on_reloaded=None,
        )
        watcher.start()
        return watcher

    # ── tool construction ────────────────────────────────────────────

    def _on_activate(self, skill: Skill) -> None:
        self.activated.add(skill.name)
        self._loaded_this_run.add(skill.name)
        if self._on_skill_state_change is not None:
            self._on_skill_state_change()

    def build_use_skill_tool(self, view: SkillRunView | None = None) -> "FunctionTool":
        """Return a ``use_skill`` tool bound to *view* (or the current view).

        Phase-2: the tool runs through ``SkillActivationService`` — the
        activation consumes ONLY the frozen bodies of the view's catalog
        (run-freeze guarantee), so results stay consistent for the entire
        run even if source files change mid-run.  A mounter (e.g.
        ``LazySkillMounter``) may be wired for sandbox mounts; without one
        the activation snapshots to the private store and reports the
        frozen content.
        """
        from .activation import SkillActivationService, make_activation_use_skill_tool
        from .snapstore import PrivateSnapshotStore

        target_view = view or self._current_view
        catalog = getattr(target_view, "catalog", None) if target_view else None
        if target_view is None or catalog is None:
            # Legacy / empty path: fall back to the compat tool with an empty
            # registry — no skills were discovered, nothing to activate.
            return make_use_skill_tool(SkillRegistry())

        service = SkillActivationService(
            catalog,
            store=PrivateSnapshotStore(),
            mounter=self.mounter,
            items_dir=PrivateSnapshotStore().root.parent / "activations",
            resolution=catalog.resolution,
        )
        tool = make_activation_use_skill_tool(
            service,
            thread_id="",
            run_id="",
            capabilities=self.capabilities,
        )
        # Keep the legacy `on_activate` hook wiring for state tracking.
        return _wrap_use_skill_tool(tool, self._on_activate)

    # ── prompt ───────────────────────────────────────────────────────

    def build_system_prompt_block(self, view: SkillRunView | None = None) -> str:
        """Return the ``<!-- electromind:skills:start -->`` block.

        Phase-2: renders the model-visible catalog (budgeted) — only
        trusted, enabled, model-invocable candidates appear; shadowed /
        disabled / untrusted candidates stay out (visible in the picker).
        """
        from .catalog import build_model_catalog

        target_view = view or self._current_view
        catalog = getattr(target_view, "catalog", None) if target_view else None
        if catalog is None:
            return _empty_prompt_block()
        budget = build_model_catalog(catalog)
        return _render_catalog_prompt(budget)

    # ── wire payload ─────────────────────────────────────────────────

    def state_payload(self, *, thread_id: str) -> dict:
        """Emit the ``SkillsState`` payload for the desktop UI."""
        catalog = self.snapshot
        view = self._current_view
        if catalog is None or view is None:
            return {
                "thread_id": thread_id,
                "fingerprint": "",
                "generation": 0,
                "digest": "",
                "skills": [],
                "loaded": [],
                "loaded_this_run": [],
                "diagnostics": [],
            }

        skills = []
        for c in catalog.candidates:
            skills.append(
                {
                    "name": c.descriptor.name,
                    "skill_id": c.skill_id,
                    "description": c.descriptor.description,
                    "source": c.source.source_id,
                    "scope": c.source.scope,
                    "sha256": c.descriptor.content_digest,
                    "status": (
                        "loaded" if c.descriptor.name in self.activated else "available"
                    ),
                    "enabled_state": c.enabled_state,
                    "trust_state": c.trust_state,
                }
            )

        diagnostics = []
        for c in catalog.candidates:
            for d in c.diagnostics:
                diagnostics.append(
                    {
                        "code": d.code,
                        "message": d.message,
                        "path": d.path,
                        "severity": d.severity,
                    }
                )

        return {
            "thread_id": thread_id,
            "fingerprint": catalog.catalog_digest,
            "generation": view.generation,
            "digest": view.digest,
            "skills": skills,
            "loaded": sorted(self.activated),
            "loaded_this_run": sorted(self._loaded_this_run),
            "diagnostics": diagnostics,
        }

    def build_skill_state_event(self, *, thread_id: str, which: str = "init") -> dict:
        """Build a ``SkillState`` event payload.

        Args:
            thread_id: Current thread identifier.
            which: Lifecycle trigger — ``"init"``, ``"prepare_turn"``,
                   ``"use_skill"``, ``"reset"``, or ``"reconnect"``.
        """
        payload = self.state_payload(thread_id=thread_id)
        payload["type"] = "SkillState"
        payload["which"] = which
        return payload

    # ── Agent replacement ────────────────────────────────────────────

    def apply_to_agent(self, agent: "AgentCore") -> bool:
        """Replace the agent's system prompt and tools with the current view.

        Returns ``True`` if the agent was modified.
        """
        view = self._current_view
        if view is None or self.snapshot is None:
            return False

        prompt_block = self.build_system_prompt_block(view)
        # Replace only the Electromind Skills section in the system text.
        new_system = _replace_skills_section(agent.system or "", prompt_block)
        new_tools = list(agent.tools)

        # Replace existing use_skill tool with the fresh one
        use_skill_tool = self.build_use_skill_tool(view)
        replaced = False
        for i, tool in enumerate(new_tools):
            if tool.name == "use_skill":
                new_tools[i] = use_skill_tool
                replaced = True
                break
        if not replaced and self.snapshot.candidates:
            new_tools.append(use_skill_tool)

        try:
            agent.replace_runtime_context(system=new_system, tools=new_tools)
        except ValueError:
            # Duplicate tool names — keep the previous agent state.
            # The error is logged but the turn continues with the old tools.
            return False
        return True


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

SKILLS_START = "<!-- electromind:skills:start -->"
SKILLS_END = "<!-- electromind:skills:end -->"


def _replace_skills_section(system: str, new_block: str) -> str:
    """Replace the ``<!-- electromind:skills:start -->`` … ``end -->``
    section in *system* with *new_block*.

    If no marker block exists the new block is appended.
    """
    start = system.find(SKILLS_START)
    end = system.find(SKILLS_END)
    if start != -1 and end != -1:
        return system[:start] + new_block + system[end + len(SKILLS_END) :]
    if system:
        return system + "\n" + new_block
    return new_block


def _empty_prompt_block() -> str:
    """The marker block for an empty catalog."""
    return f"{SKILLS_START}\n(暂无可用 skill)\n{SKILLS_END}\n"


def _render_catalog_prompt(budget) -> str:
    """Render the budgeted model-visible catalog as the skills prompt block.

    Keeps the legacy marker contract (``<!-- electromind:skills:start -->``)
    and the ``use_skill`` hint so callers/tests of the prompt shape keep
    working; the entries come from the model-visible budget (RFC 十一).
    """
    lines: list[str] = []
    lines.append(SKILLS_START)
    if budget.entries:
        lines.append("你可以按需加载这些 skill：")
        for entry in budget.entries:
            source = f" [{entry.source_label}]" if entry.source_label else ""
            if entry.description:
                lines.append(f"- `{entry.name}`{source}：{entry.description}")
            else:
                lines.append(f"- `{entry.name}`{source}")
        lines.append("调 `use_skill(name)` 会把对应 skill 的完整说明书加载进来。")
    else:
        lines.append("(暂无可用 skill)")
    lines.append(SKILLS_END)
    return "\n".join(lines) + "\n"


def _wrap_use_skill_tool(tool, on_activate) -> "FunctionTool":
    """Wrap the activation-backed tool to keep the legacy on-activate hook.

    The hook only records the activated name; the activation payload already
    carries the frozen instructions.  The wrapped func returns the same JSON
    string the activation tool would (normalize_tool_output handles it).
    """
    import json as _json

    original = tool.func

    async def wrapped(**kwargs):
        raw = await original(**kwargs)
        if isinstance(raw, str):
            try:
                payload = _json.loads(raw)
                if payload.get("ok") and on_activate is not None:
                    on_activate(
                        Skill(
                            name=payload.get("name", ""),
                            description=payload.get("description", ""),
                            instructions=payload.get("instructions", ""),
                            root=Path("/"),
                        )
                    )
            except (ValueError, TypeError):
                pass
        return raw

    from ..core.tool import FunctionTool

    return FunctionTool(
        name=tool.name,
        description=tool.description,
        parameters=tool.parameters,
        func=wrapped,
    )
