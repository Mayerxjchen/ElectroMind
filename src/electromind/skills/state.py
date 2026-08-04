"""Skill state payloads and run-view for desktop UI and agent binding.

``SkillRunView`` pins a generation to an agent run, ensuring ``use_skill``
returns consistent content for the entire run duration.

``SkillState`` is the wire event payload sent to desktop clients.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .discovery import SkillDiagnostic, SkillMount
    from .skill import SkillRegistry


@dataclass(frozen=True, slots=True)
class SkillRunView:
    """Immutable skill state for the duration of one agent run.

    Once created, this view does not change — even if source files are
    modified and a new generation is discovered. The agent's ``use_skill``
    tool captures this view and returns consistent results.

    Attributes:
        generation: Monotonically increasing integer (1-based).
        digest: Content-addressed hash of the skill set.
        registry: The ``SkillRegistry`` for this generation (compat facade).
        agents_md: ``AGENTS.md`` content from structured skill roots, or ``None``.
        mounted_roots: ``name -> SkillMount`` mapping for sandbox paths.
        catalog: The frozen ``MultiCandidateCatalog`` backing this view.
            Activations consume ONLY this catalog's frozen bodies
            (run-freeze guarantee); ``None`` for legacy-constructed views.
    """

    generation: int
    digest: str
    registry: "SkillRegistry"
    agents_md: str | None
    mounted_roots: dict[str, "SkillMount"]
    catalog: "object | None" = None


@dataclass(frozen=True, slots=True)
class SkillState:
    """Wire event payload for the Skills panel in desktop/web clients.

    Attributes:
        generation: Current generation number.
        digest: Content-addressed hash of the skill set.
        available: List of available skill summaries.
        loaded_this_run: Names of skills loaded via ``use_skill`` in the current run.
        diagnostics: Non-fatal issues from discovery/loading.
    """

    generation: int
    digest: str
    available: tuple[dict, ...]
    loaded_this_run: tuple[str, ...]
    diagnostics: tuple["SkillDiagnostic", ...]


@dataclass(frozen=True, slots=True)
class ExecutionContextState:
    """Wire event payload for remote execution context in desktop/web clients.

    Attributes:
        target: Execution target label (e.g. ``"ssh"``).
        profile_id: SSH profile/host identifier.
        documents: List of loaded context document summaries.
        diagnostics: Any issues encountered during context loading.
    """

    target: str
    profile_id: str
    documents: tuple[dict, ...]
    diagnostics: tuple[dict, ...]


def build_execution_context_state(
    *,
    backend_type: str,
    profile_id: str,
    documents: tuple = (),
    context_diagnostics: tuple = (),
    thread_id: str = "",
) -> dict:
    """Build an ``ExecutionContextState`` wire event payload.

    Args:
        backend_type: The backend type string (e.g. ``"ssh"``).
        profile_id: SSH profile/host identifier.
        documents: ``ExecutionContextDocument`` instances from the backend.
        context_diagnostics: Per-file diagnostics from context loading.
        thread_id: Current thread identifier.

    Returns:
        A dict suitable for JSON serialization over the wire.
    """
    doc_summaries: list[dict] = []
    for doc in documents:
        doc_summaries.append(
            {
                "remote_path": getattr(doc, "remote_path", ""),
                "sha256": getattr(doc, "sha256", ""),
                "fetched_at": getattr(doc, "fetched_at", 0.0),
            }
        )

    return {
        "type": "ExecutionContextState",
        "thread_id": thread_id,
        "target": backend_type,
        "profile_id": profile_id,
        "documents": tuple(doc_summaries),
        "diagnostics": tuple(context_diagnostics),
    }
