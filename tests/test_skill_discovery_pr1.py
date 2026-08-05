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
        root / "a" / "b" / "c" / "d" / "e" / "f" / "g",
        "too-deep",  # depth 7
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
        d.code == "skill_name_directory_mismatch" for c in warned for d in c.diagnostics
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
        d.code == "skill_missing_description" for c in nodesc for d in c.diagnostics
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


# ── acceptance gates (PR1 plan) ───────────────────────────────────────


def test_matches_exact_skill_md_filename(tmp_path):
    root = tmp_path / "skills"
    good = _write_skill(root, "alpha")
    for idx, bad_name in enumerate(("SKILL.MD", "skill.md", "Skill.md")):
        d = root / f"bad-{idx}"
        d.mkdir(parents=True)
        (d / bad_name).write_text(
            "---\nname: x\ndescription: d\n---\n", encoding="utf-8"
        )
    found = discover_skill_dirs(root)
    assert found == [good]


def test_skips_generated_directories(tmp_path):
    root = tmp_path / "skills"
    _write_skill(root, "visible")
    for gen in ("dist", "build"):
        _write_skill(root / gen, f"gen-{gen}")
    names = {p.name for p in discover_skill_dirs(root)}
    assert names == {"visible"}


def test_continues_through_grouping_directories(tmp_path):
    root = tmp_path / "skills"
    d = _write_skill(root / "tools" / "simulation", "cp2k")
    assert discover_skill_dirs(root) == [d]


def test_discovers_atomic_siblings(tmp_path):
    root = tmp_path / "skills"
    alpha = _write_skill(root, "alpha")
    (alpha / "nested").mkdir()
    (alpha / "nested" / "SKILL.md").write_text(
        "---\nname: nested\ndescription: x\n---\n", encoding="utf-8"
    )
    beta = _write_skill(root, "beta")
    found = sorted(discover_skill_dirs(root))
    assert found == sorted([alpha, beta])


def test_broken_symlink_is_safe(tmp_path):
    root = tmp_path / "skills"
    good = _write_skill(root, "valid")
    (root / "broken").symlink_to(tmp_path / "does-not-exist", target_is_directory=True)
    assert discover_skill_dirs(root) == [good]


def test_nonexistent_root_is_safe(tmp_path):
    assert discover_skill_dirs(tmp_path / "nope") == []


def test_empty_root_returns_empty(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    assert discover_skill_dirs(root) == []


def test_expected_repository_skill_set(tmp_path):
    """The repo's own grouped skills/ discover EXACTLY the 17 known skills.

    The expected list is hand-confirmed (NOT generated by the discoverer), so
    the test catches both missing and unexpected skills.
    """
    repo = Path(__file__).resolve().parents[1]  # repo root
    sources = discover_candidate_sources(str(repo), cwd=str(repo))
    candidates = load_candidates(sources)
    proj = [c for c in candidates if c.source.scope == "project"]
    actual = sorted(c.descriptor.name for c in proj)
    expected = sorted(
        [
            # procedures
            "comp-chem-workflow",
            "literature-to-calculation",
            "research-orchestrator",
            "review-response",
            # tools
            "cp2k",
            "deepmd",
            "hpc-submit",
            "lammps",
            "lobster",
            "mlp",
            "multiwfn",
            "packmol",
            "report",
            "rsess",
            "structure-prep",
            "vasp",
            "vaspkit",
        ]
    )
    assert actual == expected, (
        f"missing={sorted(set(expected) - set(actual))} "
        f"unexpected={sorted(set(actual) - set(expected))}"
    )


def test_no_unexpected_repository_skills(tmp_path):
    """The repo's grouped skills/ produce no false positives from internals."""
    repo = Path(__file__).resolve().parents[1]
    sources = discover_candidate_sources(str(repo), cwd=str(repo))
    candidates = load_candidates(sources)
    names = {c.descriptor.name for c in candidates if c.source.scope == "project"}
    # No reference/nested SKILL.md inside a skill may surface as a skill.
    for n in names:
        assert "/" not in n and n not in {"example", "sample", "demo"}


# ── C3: adopted root (entry symlink) policy ───────────────────────────


def test_trusted_entry_symlink_is_discovered(tmp_path):
    proj = _make_project(tmp_path)
    ext = tmp_path / "external-aicc"
    _write_skill(ext / "procedures", "cp2k")
    (proj / "skills").mkdir()
    (proj / "skills" / "aicc").symlink_to(ext, target_is_directory=True)
    sources = discover_candidate_sources(
        str(proj), cwd=str(proj), external_skill_roots=[ext], builtin_roots=[]
    )
    candidates = load_candidates(sources)
    names = sorted(c.descriptor.name for c in candidates)
    assert names == ["cp2k"]


def test_untrusted_entry_symlink_is_rejected(tmp_path):
    proj = _make_project(tmp_path)
    evil = tmp_path / "etc"
    _write_skill(evil, "evil")
    (proj / "skills").mkdir()
    (proj / "skills" / "system").symlink_to(evil, target_is_directory=True)
    sources = discover_candidate_sources(str(proj), cwd=str(proj), builtin_roots=[])
    candidates = load_candidates(sources)
    names = [c.descriptor.name for c in candidates]
    assert "evil" not in names


def test_entry_symlink_policy_is_disableable(tmp_path):
    proj = _make_project(tmp_path)
    ext = tmp_path / "external"
    _write_skill(ext, "external-skill")
    (proj / "skills").mkdir()
    (proj / "skills" / "link").symlink_to(ext, target_is_directory=True)
    # No external_skill_roots configured → entry symlink NOT adopted.
    sources = discover_candidate_sources(str(proj), cwd=str(proj), builtin_roots=[])
    candidates = load_candidates(sources)
    names = [c.descriptor.name for c in candidates]
    assert "external-skill" not in names


def test_nested_symlink_is_skipped_even_when_adopted(tmp_path):
    proj = _make_project(tmp_path)
    ext = tmp_path / "ext"
    _write_skill(ext, "outer")
    (proj / "skills").mkdir()
    (proj / "skills" / "aicc").symlink_to(ext, target_is_directory=True)
    # a nested symlink INSIDE the adopted root is still skipped
    nested = ext / "sub"
    nested.mkdir()
    nested_target = tmp_path / "elsewhere"
    _write_skill(nested_target, "nested-skill")
    (nested / "x").symlink_to(nested_target, target_is_directory=True)
    sources = discover_candidate_sources(
        str(proj), cwd=str(proj), external_skill_roots=[ext], builtin_roots=[]
    )
    candidates = load_candidates(sources)
    names = [c.descriptor.name for c in candidates]
    assert "outer" in names
    assert "nested-skill" not in names


# ── trust: dedup merges provenance, never elevates trust ─────────────


def test_project_builtin_same_file_uses_project_scope(tmp_path):
    proj = _make_project(tmp_path)
    _write_skill(proj / "skills" / "tools", "cp2k")
    builtin = [proj / "skills" / "tools"]  # same physical file also via builtin
    sources = discover_candidate_sources(
        str(proj), cwd=str(proj), builtin_roots=builtin
    )
    candidates = load_candidates(sources, is_project_trusted=lambda pr: True)
    cp2k = [c for c in candidates if c.descriptor.name == "cp2k"]
    assert len(cp2k) == 1
    assert cp2k[0].source.scope == "project"  # project wins over builtin
    assert {s.scope for s in cp2k[0].discovery_sources} == {"project", "builtin"}


def test_project_builtin_same_file_requires_workspace_trust(tmp_path):
    proj = _make_project(tmp_path)
    _write_skill(proj / "skills" / "tools", "cp2k")
    builtin = [proj / "skills" / "tools"]
    sources = discover_candidate_sources(
        str(proj), cwd=str(proj), builtin_roots=builtin
    )
    candidates = load_candidates(sources, is_project_trusted=lambda pr: False)
    cp2k = [c for c in candidates if c.descriptor.name == "cp2k"]
    assert len(cp2k) == 1
    assert cp2k[0].trust_state == "untrusted", "project skill needs workspace trust"


def test_builtin_provenance_does_not_elevate_project_trust(tmp_path):
    proj = _make_project(tmp_path)
    _write_skill(proj / "skills" / "tools", "cp2k")
    builtin = [proj / "skills" / "tools"]
    sources = discover_candidate_sources(
        str(proj), cwd=str(proj), builtin_roots=builtin
    )
    candidates = load_candidates(sources, is_project_trusted=lambda pr: False)
    cp2k = [c for c in candidates if c.descriptor.name == "cp2k"]
    # Builtin provenance is recorded, but it must NOT grant builtin trust.
    assert {s.scope for s in cp2k[0].discovery_sources} == {"project", "builtin"}
    assert cp2k[0].trust_state == "untrusted"


def test_packaged_builtin_skill_remains_trusted(tmp_path):
    """A PURE builtin candidate (no project overlap) keeps builtin trust."""
    builtin = tmp_path / "packaged"
    _write_skill(builtin / "tools", "vasp")
    sources = discover_candidate_sources(
        None, cwd=str(tmp_path), builtin_roots=[builtin / "tools"]
    )
    candidates = load_candidates(sources, is_project_trusted=lambda pr: False)
    vasp = [c for c in candidates if c.descriptor.name == "vasp"]
    assert len(vasp) == 1
    assert vasp[0].source.scope == "builtin"
    assert vasp[0].trust_state == "trusted"
