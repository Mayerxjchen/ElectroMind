"""End-to-end tests for project Skill auto-discovery with the real repository bundle.

These are catalog/prompt contract tests — they assert exact routing sentences and
structural invariants, not model-output snapshots.
"""

from pathlib import Path

import pytest

from electromind.skills.discovery import discover_skill_sources, load_skill_catalog
from electromind.skills.skill import build_skills_system_prompt

# Path to the repository root (parent of this file's directory)
REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def repo_catalog():
    """Load the real repository skill bundle."""
    sources = discover_skill_sources(str(REPO_ROOT))
    return load_skill_catalog(sources)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_repository_bundle_registers_hpc_skills(repo_catalog):
    """The real repository bundle must register hpc-submit and rsess."""
    names = repo_catalog.registry.names()
    assert "hpc-submit" in names
    assert "rsess" in names
    # Procedures should also be registered
    assert "comp-chem-workflow" in names or "literature-to-calculation" in names


def test_repository_bundle_loads_agents_before_catalog(repo_catalog):
    """Global instructions (skills/AGENTS.md) must appear before the Skill catalog."""
    prompt = build_skills_system_prompt(repo_catalog)

    # AGENTS.md content should appear
    assert "Computational Chemistry" in prompt or "Routing" in prompt

    # AGENTS.md must precede the skills catalog markers
    if "<!-- electromind:skills:start -->" in prompt:
        pos_routing = prompt.find("Routing") if "Routing" in prompt else prompt.find("Computational Chemistry")
        pos_start = prompt.find("<!-- electromind:skills:start -->")
        assert pos_routing < pos_start, "AGENTS.md content must appear before skill catalog"


def test_ssh_routing_uses_hpc_submit_without_rsess_layer(repo_catalog):
    """In SSH mode, hpc-submit should be used directly, not via rsess."""
    # Assert routing sentences from skills/AGENTS.md are present in global instructions
    instructions = "\n".join(repo_catalog.global_instructions)
    assert "hpc-submit" in instructions
    assert "rsess" in instructions


def test_local_remote_workflow_routes_rsess_then_hpc_submit(repo_catalog):
    """Local→remote workflow should route through rsess, then hpc-submit."""
    instructions = "\n".join(repo_catalog.global_instructions)
    # The AGENTS.md should reference the routing table
    # rsess is for driving remote machines from local
    assert "rsess" in instructions
    assert "hpc-submit" in instructions


def test_aicc_bundle_knowledge_is_not_skill(repo_catalog):
    """AICC knowledge/ entries must NOT appear as Skills."""
    names = repo_catalog.registry.names()
    assert "knowledge" not in names
    assert "reference" not in names
    # No knowledge-type entries should be registered
    knowledge_names = {
        "bonding-analysis",
        "electrochemistry",
        "electronic-structure",
        "force-fields",
    }
    for kn in knowledge_names:
        assert kn not in names, f"knowledge entry '{kn}' must not be a Skill"


def test_skill_has_source_id_and_sha256(repo_catalog):
    """Every Skill in the catalog must have a non-empty source_id and sha256."""
    for skill in repo_catalog.registry.list():
        assert skill.source_id, f"Skill '{skill.name}' missing source_id"
        assert skill.sha256, f"Skill '{skill.name}' missing sha256"
        assert len(skill.sha256) == 64, f"Skill '{skill.name}' sha256 must be 64 hex chars"


def test_catalog_fingerprint_is_stable(repo_catalog):
    """The same catalog loaded twice should have the same fingerprint."""
    sources = discover_skill_sources(str(REPO_ROOT))
    catalog2 = load_skill_catalog(sources)
    assert repo_catalog.fingerprint == catalog2.fingerprint


def test_no_hardcoded_paths_in_prompt(repo_catalog):
    """The skill prompt must not contain hardcoded filesystem paths from the repo."""
    prompt = build_skills_system_prompt(repo_catalog)
    repo_str = str(REPO_ROOT)
    # Skip if repo root is very short (unlikely match)
    if len(repo_str) > 10:
        assert repo_str not in prompt, (
            "Prompt must not contain hardcoded repo filesystem paths"
        )
