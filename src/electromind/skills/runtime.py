"""Skill runtime: refresh skills at user-turn boundaries.

``SkillRuntime`` owns the Skill discovery/catalog lifecycle for a running
ElectroMind task.  It is created by ``BaseRunner`` and refreshed before each
user turn via ``before_user_turn()``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from .discovery import (
    SkillCatalogSnapshot,
    SkillMount,
    discover_skill_sources,
    load_skill_catalog,
)
from .skill import (
    Skill,
    SkillRegistry,
    build_skills_system_prompt,
    make_use_skill_tool,
)

if TYPE_CHECKING:
    from ..core.agent import AgentCore
    from ..core.tool import FunctionTool


class SkillRuntime:
    """Per-task Skill lifecycle manager.

    One instance per Runner.  Refreshed before each user turn via
    ``refresh_if_changed()``.
    """

    def __init__(
        self,
        project_path: str | Path | None,
        *,
        configured_roots: Sequence[str | Path] = (),
        user_home: Path | None = None,
    ) -> None:
        self.project_path: str | Path | None = project_path
        self.configured_roots: tuple[str | Path, ...] = tuple(configured_roots)
        self.user_home: Path | None = user_home

        # Current valid state
        self.snapshot: SkillCatalogSnapshot | None = None
        self.mounts: dict[str, SkillMount] = {}

        # Activated skills in this task
        self.activated: set[str] = set()

        # Diagnostics callback: (diagnostics) -> None
        self._on_diagnostics: "callable | None" = None

    # ── refresh ──────────────────────────────────────────────────────

    async def refresh_if_changed(self) -> bool:
        """Discover, load, and optionally install a new catalog.

        Returns ``True`` if the snapshot changed, ``False`` if the
        fingerprint was unchanged or if loading produced error diagnostics.
        On failure the previous snapshot and mounts are preserved.
        """
        sources = discover_skill_sources(
            self.project_path,
            configured_roots=self.configured_roots,
            user_home=self.user_home,
        )
        try:
            candidate = load_skill_catalog(sources)
        except Exception:
            # Keep previous snapshot on failure
            return False

        # Reject catalogs with error-level diagnostics (e.g. corrupted files).
        if any(d.severity == "error" for d in candidate.diagnostics):
            return False

        if self.snapshot is not None and candidate.fingerprint == self.snapshot.fingerprint:
            return False

        # Always accept the candidate — installation happens elsewhere (sandbox).
        self.snapshot = candidate
        return True

    # ── tool construction ────────────────────────────────────────────

    def _on_activate(self, skill: Skill) -> None:
        self.activated.add(skill.name)

    def build_use_skill_tool(self) -> "FunctionTool":
        """Return a ``use_skill`` tool bound to the current catalog and mounts."""
        if self.snapshot is None:
            return make_use_skill_tool(SkillRegistry())
        return make_use_skill_tool(
            self.snapshot,
            self.mounts,
            on_activate=self._on_activate,
        )

    # ── prompt ───────────────────────────────────────────────────────

    def build_system_prompt_block(self) -> str:
        """Return the ``<!-- electromind:skills:start -->`` block."""
        if self.snapshot is None:
            return build_skills_system_prompt(SkillRegistry())
        return build_skills_system_prompt(self.snapshot, self.mounts)

    # ── wire payload ─────────────────────────────────────────────────

    def state_payload(self, *, thread_id: str) -> dict:
        """Emit the ``SkillsState`` payload for the desktop UI."""
        snapshot = self.snapshot
        if snapshot is None:
            return {
                "thread_id": thread_id,
                "fingerprint": "",
                "skills": [],
                "loaded": [],
                "diagnostics": [],
            }

        skills = []
        for skill in snapshot.registry.list():
            skills.append(
                {
                    "name": skill.name,
                    "description": skill.description,
                    "source": skill.source_id,
                    "sha256": skill.sha256,
                    "status": "loaded" if skill.name in self.activated else "available",
                }
            )

        return {
            "thread_id": thread_id,
            "fingerprint": snapshot.fingerprint,
            "skills": skills,
            "loaded": sorted(self.activated),
            "diagnostics": [
                {"code": d.code, "message": d.message, "path": d.path, "severity": d.severity}
                for d in snapshot.diagnostics
            ],
        }

    # ── Agent replacement ────────────────────────────────────────────

    def apply_to_agent(self, agent: "AgentCore") -> bool:
        """Replace the agent's system prompt and tools with the current catalog.

        Returns ``True`` if the agent was modified.
        """
        if self.snapshot is None:
            return False

        prompt_block = self.build_system_prompt_block()
        # Replace only the Electromind Skills section in the system text.
        new_system = _replace_skills_section(agent.system or "", prompt_block)
        new_tools = list(agent.tools)

        # Replace existing use_skill tool with the fresh one
        use_skill_tool = self.build_use_skill_tool()
        replaced = False
        for i, tool in enumerate(new_tools):
            if tool.name == "use_skill":
                new_tools[i] = use_skill_tool
                replaced = True
                break
        if not replaced and self.snapshot.registry.skills:
            new_tools.append(use_skill_tool)

        agent.replace_runtime_context(system=new_system, tools=new_tools)
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
