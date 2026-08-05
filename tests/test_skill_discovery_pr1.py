"""PR1: bounded recursive skill discovery tests.

Covers the SKILL-2 RFC revision — root-internal discovery is BOUNDED
recursion (max 6 levels, stop at an atomic Skill boundary), the same physical
file is deduplicated across overlapping roots, same-scope duplicates are
errors (non-builtin) while builtin install-duplication is tolerated, and
frontmatter name/directory mismatches warn instead of dropping.
"""

from __future__ import annotations

from pathlib import Path

from electromind.skills.discovery import DiscoveryPolicy, discover_skill_dirs
from electromind.skills.scopes import discover_candidate_sources, load_candidates


def _write_skill(root: Path, name: str) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test skill {name}\n---\nBody.\n",
        encoding="utf-8",
    )
    return d


# ── traversal engine ─────────────────────────────────────────────────

def test_discovers_direct_child_skill(tmp_path):
    d = _write_skill(tmp_path / "skills", "direct")
    assert discover_skill_dirs(tmp_path / "skills") == [d]


def test_discovers_grouped_skill(tmp_path):
    root = tmp_path / "skills"
    _write_skill(root / "procedures", "comp-chem-workflow")
    _write_skill(root / "tools", "cp2k")
    found = sorted(discover_skill_dirs(root))
    assert found == sorted(
        [root / "procedures" / "comp-chem-workflow", root / "tools" / "cp2k"]
    )


def test_discovers_aicc_collection_layout(tmp_path):
    """skills/aicc/procedures/<name>/SKILL.md — depth 3, within max_depth."""
    root = tmp_path / "skills"
    d = _write_skill(root / "aicc" / "procedures", "comp-chem-workflow")
    assert discover_skill_dirs(root) == [d]


def test_stops_at_atomic_skill_boundary(tmp_path):
    root = tmp_path / "skills"
    outer = _write_skill(root, "workflow-toolkit")
    nested = outer / "references" / "example-package"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text(
        "---\nname: example-package\ndescription: x\n---\n", encoding="utf-8"
    )
    found = discover_skill_dirs(root)
    assert found == [outer]
    assert nested not in found


def test_does_not_register_reference_skill_md(tmp_path):
    root = tmp_path / "skills"
    outer = _write_skill(root, "cp2k")
    ref = outer / "references"
    ref.mkdir()
    (ref / "SKILL.md").write_text("sample", encoding="utf-8")
    assert discover_skill_dirs(root) == [outer]


def test_respects_max_depth(tmp_path):
    root = tmp_path / "skills"
    deep = _write_skill(root / "a" / "b" / "c", "deep-skill")  # depth 3 ≤ 6
    assert deep in discover_skill_dirs(root)
    too_deep = _write_skill(
        root / "a" / "b" / "c" / "d" / "e" / "f" / "g", "too-deep"  # depth 7
    )
    found = discover_skill_dirs(root)
    assert too_deep not in found


def test_skips_hidden_and_ignored_dirs(tmp_path):
    root = tmp_path / "skills"
    _write_skill(root, "visible")
    _write_skill(root / ".hidden", "hidden-skill")
    _write_skill(root / "node_modules", "dep-skill")
    _write_skill(root / "__pycache__", "cache-skill")
    names = {p.name for p in discover_skill_dirs(root)}
    assert names == {"visible"}


def test_discovery_order_is_deterministic(tmp_path):
    root = tmp_path / "skills"
    _write_skill(root / "b", "b-skill")
    _write_skill(root / "a", "a-skill")
    _write_skill(root / "c", "c-skill")
    first = discover_skill_dirs(root)
    second = discover_skill_dirs(root)
    assert first == second
    assert [p.name for p in first] == sorted(p.name for p in first)


def test_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside"
    _write_skill(outside, "external")
    root = tmp_path / "skills"
    root.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    # default policy does not follow nested symlinks
    assert discover_skill_dirs(root) == []


def test_breaks_symlink_cycle_when_follow_enabled(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    (root / "loop").symlink_to(root, target_is_directory=True)
    _write_skill(root, "real")
    found = discover_skill_dirs(
        root, policy=DiscoveryPolicy(follow_directory_symlinks=True)
    )
    assert len(found) == 1  # visited-set breaks the cycle, no recursion error


# ── scoped discovery + candidates ────────────────────────────────────

def _make_project(tmp_path: Path, name: str = "proj") -> Path:
    proj = tmp_path / name
    proj.mkdir()
    return proj


def test_existing_procedures_tools_layout_works(tmp_path):
    proj = _make_project(tmp_path)
    _write_skill(proj / "skills" / "procedures", "comp-chem-workflow")
    _write_skill(proj / "skills" / "tools", "cp2k")
    sources = discover_candidate_sources(str(proj), cwd=str(proj))
    candidates = load_candidates(sources)
    proj_cands = [c for c in candidates if c.source.scope == "project"]
    names = sorted(c.descriptor.name for c in proj_cands)
    assert names == ["comp-chem-workflow", "cp2k"]


def test_same_physical_skill_project_and_builtin_deduplicated(tmp_path):
    proj = _make_project(tmp_path)
    _write_skill(proj / "skills" / "tools", "cp2k")
    builtin = [proj / "skills" / "tools"]  # builtin root = same physical file
    sources = discover_candidate_sources(
        str(proj), cwd=str(proj), builtin_roots=builtin
    )
    candidates = load_candidates(sources)
    cp2k = [c for c in candidates if c.descriptor.name == "cp2k"]
    assert len(cp2k) == 1, "same physical skill deduplicated to ONE candidate"
    assert cp2k[0].source.scope == "project"
    assert {s.scope for s in cp2k[0].discovery_sources} == {"project", "builtin"}


def test_symlink_and_real_path_do_not_register_twice(tmp_path):
    proj = _make_project(tmp_path)
    real = _write_skill(proj / "skills" / "tools", "cp2k")
    # a second root via symlink pointing at the same physical dir
    link = proj / ".agents" / "skills" / "cp2k-link"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(real, target_is_directory=True)
    sources = discover_candidate_sources(str(proj), cwd=str(proj), builtin_roots=[])
    candidates = load_candidates(sources)
    cp2k = [c for c in candidates if c.descriptor.name == "cp2k"]
    # symlinked entry either rejected or deduplicated — never two candidates
    assert len(cp2k) <= 1


def test_same_scope_duplicate_is_error(tmp_path):
    proj = _make_project(tmp_path)
    _write_skill(proj / "skills" / "tools", "cp2k")
    _write_skill(proj / "skills" / "legacy", "cp2k")
    sources = discover_candidate_sources(str(proj), cwd=str(proj), builtin_roots=[])
    candidates = load_candidates(sources)
    cp2k = [c for c in candidates if c.descriptor.name == "cp2k"]
    assert len(cp2k) == 2  # both kept for reporting
    errs = [
        d
        for c in cp2k
        for d in c.diagnostics
        if d.code == "duplicate_skill_name" and d.severity == "error"
    ]
    assert len(errs) == 2


def test_higher_scope_shadows_lower_scope(tmp_path):
    proj = _make_project(tmp_path)
    _write_skill(proj / "skills" / "tools", "cp2k")
    home = tmp_path / "home"
    _write_skill(home / ".agents" / "skills", "cp2k")
    sources = discover_candidate_sources(str(proj), cwd=str(proj), user_home=home)
    candidates = load_candidates(sources)
    cp2k = [c for c in candidates if c.descriptor.name == "cp2k"]
    assert any(c.source.scope == "project" for c in cp2k)


def test_name_parent_mismatch_warns_but_registers(tmp_path):
    proj = _make_project(tmp_path)
    d = proj / ".agents" / "skills" / "mismatched"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: other-name\ndescription: d\n---\n", encoding="utf-8"
    )
    sources = discover_candidate_sources(str(proj), cwd=str(proj))
    candidates = load_candidates(sources)
    names = [c.descriptor.name for c in candidates]
    assert "other-name" in names, "mismatched skill still registered"
    warned = [c for c in candidates if c.descriptor.name == "other-name"]
    assert any(
        d.code == "skill_name_directory_mismatch"
        for c in warned
        for d in c.diagnostics
    )


def test_missing_description_is_reported(tmp_path):
    proj = _make_project(tmp_path)
    d = proj / ".agents" / "skills" / "nodesc"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: nodesc\n---\nbody\n", encoding="utf-8")
    sources = discover_candidate_sources(str(proj), cwd=str(proj))
    candidates = load_candidates(sources)
    nodesc = [c for c in candidates if c.descriptor.name == "nodesc"]
    assert nodesc  # still a candidate
    assert any(
        d.code == "skill_missing_description"
        for c in nodesc
        for d in c.diagnostics
    )


def test_deduplication_precedes_name_conflict_resolution(tmp_path):
    """Physical-file dedup collapses overlap BEFORE same-name conflict logic."""
    proj = _make_project(tmp_path)
    _write_skill(proj / "skills" / "tools", "cp2k")
    builtin = [proj / "skills" / "tools"]
    sources = discover_candidate_sources(
        str(proj), cwd=str(proj), builtin_roots=builtin
    )
    candidates = load_candidates(sources)
    cp2k = [c for c in candidates if c.descriptor.name == "cp2k"]
    # dedup (project + builtin same file) must NOT surface as a duplicate error
    errs = [d for c in cp2k for d in c.diagnostics if d.code == "duplicate_skill_name"]
    assert errs == []
