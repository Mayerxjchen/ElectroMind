"""End-to-end tests for project Skill auto-discovery with the real repository bundle.

These are **catalog contract tests** — they verify that Skills are correctly
discovered, described, and exposed to the agent.  They do **not** assert that
the model must choose a particular Skill; routing decisions belong to the agent.
"""

from pathlib import Path

import pytest

from electromind.skills.discovery import discover_skill_sources, load_skill_catalog
from electromind.skills.skill import build_skills_system_prompt

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def repo_catalog():
    """Load the real repository skill bundle once per test run."""
    sources = discover_skill_sources(str(REPO_ROOT))
    return load_skill_catalog(sources)


# ---------------------------------------------------------------------------
# Skill discoverability
# ---------------------------------------------------------------------------


def test_hpc_and_rsess_are_discovered(repo_catalog):
    """Both ``hpc-submit`` and ``rsess`` must be registered in the catalog."""
    names = repo_catalog.registry.names()
    assert "hpc-submit" in names, "hpc-submit must be discoverable"
    assert "rsess" in names, "rsess must be discoverable"


def test_every_skill_has_non_empty_description(repo_catalog):
    """No Skill description may be empty — the agent relies on them for routing."""
    for skill in repo_catalog.registry.list():
        assert skill.description.strip(), (
            f"Skill '{skill.name}' has an empty description"
        )


def test_knowledge_is_not_registered_as_skill(repo_catalog):
    """``knowledge/`` entries are reference material, not callable Skills."""
    names = repo_catalog.registry.names()
    assert "knowledge" not in names
    knowledge_like = {
        "bonding-analysis",
        "electrochemistry",
        "electronic-structure",
        "force-fields",
        "reaction-kinetics",
        "molecular-dynamics",
    }
    for kn in knowledge_like:
        assert kn not in names, f"knowledge entry '{kn}' must not be a Skill"


# ---------------------------------------------------------------------------
# Catalog integrity
# ---------------------------------------------------------------------------


def test_global_instructions_precede_skill_catalog(repo_catalog):
    """AGENTS.md content must appear before the skill catalog markers."""
    prompt = build_skills_system_prompt(repo_catalog)
    if "<!-- electromind:skills:start -->" not in prompt:
        return  # no catalog section, nothing to assert
    pos_routing = prompt.find("Routing")
    pos_start = prompt.find("<!-- electromind:skills:start -->")
    assert pos_routing >= 0, "AGENTS.md 'Routing' section must be present"
    assert pos_routing < pos_start, "Global instructions must precede the skill catalog"


def test_skill_has_source_id_and_sha256(repo_catalog):
    """Every Skill needs a source_id (provenance) and sha256 (change detection)."""
    for skill in repo_catalog.registry.list():
        assert skill.source_id, f"Skill '{skill.name}' missing source_id"
        assert skill.sha256, f"Skill '{skill.name}' missing sha256"
        assert len(skill.sha256) == 64, (
            f"Skill '{skill.name}' sha256 must be 64 hex chars"
        )


def test_catalog_fingerprint_is_stable(repo_catalog):
    """Loading the same sources twice must produce the same fingerprint."""
    sources = discover_skill_sources(str(REPO_ROOT))
    catalog2 = load_skill_catalog(sources)
    assert repo_catalog.fingerprint == catalog2.fingerprint


def test_prompt_contains_no_hardcoded_filesystem_paths(repo_catalog):
    """The generated prompt must not leak host filesystem paths."""
    prompt = build_skills_system_prompt(repo_catalog)
    repo_str = str(REPO_ROOT)
    if len(repo_str) > 10:
        assert repo_str not in prompt, (
            "Prompt must not contain hardcoded repo filesystem paths"
        )


# ---------------------------------------------------------------------------
# Non-coercion: registration does not force execution
# ---------------------------------------------------------------------------


def test_skill_registration_does_not_execute_anything(repo_catalog):
    """Loading the catalog must not execute any Skill script or produce
    subprocess / network / file-write side effects.

    We re-run discovery under instrumentation to prove this, rather than
    only asserting on the already-loaded catalog object.
    """
    import builtins
    import subprocess

    subprocess_calls: list = []
    open_writes: list = []

    real_popen = subprocess.Popen
    real_open = builtins.open

    def _fake_popen(*args, **kwargs):
        subprocess_calls.append((args, kwargs))
        return real_popen(*args, **kwargs)

    def _fake_open(file, mode="r", *args, **kwargs):
        if "w" in mode or "a" in mode or "+" in mode:
            open_writes.append((file, mode))
        return real_open(file, mode, *args, **kwargs)

    try:
        subprocess.Popen = _fake_popen  # type: ignore[assignment]
        builtins.open = _fake_open  # type: ignore[assignment]
        sources = discover_skill_sources(str(REPO_ROOT))
        load_skill_catalog(sources)
    finally:
        subprocess.Popen = real_popen  # type: ignore[assignment]
        builtins.open = real_open  # type: ignore[assignment]

    assert len(subprocess_calls) == 0, (
        f"Catalog loading must not spawn subprocesses; got {subprocess_calls}"
    )
    # open(…, 'w') calls during discovery must be zero
    assert len(open_writes) == 0, (
        f"Catalog loading must not write files; got {open_writes}"
    )
    # The loaded catalog itself is still valid
    assert repo_catalog.registry is not None
    assert isinstance(repo_catalog.fingerprint, str)


def test_skill_registration_does_not_grant_tool_permissions(repo_catalog):
    """Skill registration adds names to the catalog; it does not alter the
    execution-mode resolution, tool whitelist, or approval policy."""
    # Verify we only have catalog metadata (names, descriptions, fingerprints).
    for skill in repo_catalog.registry.list():
        assert isinstance(skill.name, str)
        assert isinstance(skill.description, str)
        # No skill carries an execution policy override
        assert not hasattr(skill, "execution_mode"), (
            f"Skill '{skill.name}' must not carry an execution_mode"
        )
        assert not hasattr(skill, "approval_policy"), (
            f"Skill '{skill.name}' must not carry an approval_policy"
        )


def test_use_skill_is_present_as_tool_when_catalog_non_empty(repo_catalog):
    """When the catalog is non-empty, ``use_skill`` must appear in the system
    prompt as the mechanism for the agent to load skill instructions."""
    names = repo_catalog.registry.names()
    if not names:
        pytest.skip("empty catalog")
    prompt = build_skills_system_prompt(repo_catalog)
    assert "use_skill" in prompt, (
        "System prompt must mention use_skill so the agent knows how to load skills"
    )


# ---------------------------------------------------------------------------
# Execution environment awareness
# ---------------------------------------------------------------------------


def test_agents_md_is_included_in_global_instructions(repo_catalog):
    """The full ``skills/AGENTS.md`` text must be present in global instructions
    so the agent can see routing guidance and execution-mode notes."""
    instructions = "\n".join(repo_catalog.global_instructions)
    assert "Routing" in instructions, (
        "AGENTS.md Routing section must be in global instructions"
    )
    assert "hpc-submit" in instructions, (
        "hpc-submit must be mentioned in global instructions"
    )
    assert "rsess" in instructions, "rsess must be mentioned in global instructions"
