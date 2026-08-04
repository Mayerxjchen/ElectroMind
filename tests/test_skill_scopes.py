"""SKILL-2 tests: multi-scope discovery — ancestor walk, admin, .claude, trust.

The legacy ``discover_skill_sources`` / ``load_skill_catalog`` behavior is
unchanged (locked by test_electromind_skills.py / test_skills_snapshot.py);
these tests cover the new ``scopes`` discovery path only.
"""

from pathlib import Path

from electromind.skills.scopes import (
    discover_candidate_sources,
    fingerprint_source,
    load_candidates,
    model_visible_candidates,
    source_rank,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_skill(root: Path, name: str, description: str, body: str) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}",
        encoding="utf-8",
    )
    return d


def _make_structured(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "AGENTS.md").write_text("# Global\n", encoding="utf-8")
    tool = root / "tools" / "hpc-submit"
    tool.mkdir(parents=True)
    (tool / "SKILL.md").write_text(
        "---\nname: hpc-submit\ndescription: Submit HPC jobs\n---\nSubmit.\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Source discovery
# ---------------------------------------------------------------------------


class TestDiscoverCandidateSources:
    def test_project_structured_and_standard(self, tmp_path):
        """Repo root level finds the structured bundle + fixed standard dirs."""
        proj = tmp_path / "proj"
        proj.mkdir()
        _make_structured(proj / "skills")
        _write_skill(proj / ".agents" / "skills", "agent-helper", "a", "b\n")
        _write_skill(proj / ".claude" / "skills", "claude-helper", "c", "d\n")

        sources = discover_candidate_sources(str(proj), cwd=str(proj))

        roots = {s.root for s in sources if s.scope == "project"}
        assert (proj / "skills").resolve() in roots
        assert (proj / ".agents" / "skills").resolve() in roots
        assert (proj / ".claude" / "skills").resolve() in roots

    def test_ancestor_discovery_from_subdir(self, tmp_path):
        """从仓库子目录启动可发现仓库根 Skill（RFC SKILL-2 完成条件）。"""
        proj = tmp_path / "repo"
        proj.mkdir()
        _make_structured(proj / "skills")
        (proj / ".git").mkdir()  # repo marker
        subdir = proj / "packages" / "water"
        subdir.mkdir(parents=True)
        _write_skill(subdir / ".electromind" / "skills", "water-helper", "w", "b\n")

        sources = discover_candidate_sources(str(proj), cwd=str(subdir))
        project_sources = [s for s in sources if s.scope == "project"]

        # Both the sub-project level and the repo-root level are found.
        assert len(project_sources) == 2  # sub .electromind + repo structured
        # Nearest project (distance 0) is the subdir level.
        nearest = [s for s in project_sources if s.distance_from_cwd == 0]
        assert len(nearest) == 1
        assert nearest[0].root == (subdir / ".electromind" / "skills").resolve()
        # Repo-root structured bundle is at a larger distance.
        repo_level = [s for s in project_sources if s.distance_from_cwd == 2]
        assert len(repo_level) == 1
        assert repo_level[0].root == (proj / "skills").resolve()

    def test_ancestor_walk_only_fixed_dirs(self, tmp_path):
        """Non-fixed dirs at ancestor levels are never scanned."""
        proj = tmp_path / "repo"
        proj.mkdir()
        _make_structured(proj / "skills")
        (proj / ".git").mkdir()
        subdir = proj / "a" / "b"
        subdir.mkdir(parents=True)
        # A skills dir with an unexpected name must NOT be discovered.
        _write_skill(proj / "a" / "skills", "stray", "s", "b\n")
        _write_skill(proj / "a" / "b" / "vendor" / "skills", "vendor", "v", "b\n")

        sources = discover_candidate_sources(str(proj), cwd=str(subdir))
        names = [s.root.name for s in sources]
        # Only <level>/skills (structured), .agents, .electromind, .claude.
        assert "stray" not in names
        assert "vendor" not in names

    def test_user_scope_includes_claude(self, tmp_path):
        """~/.claude/skills is a user-scope source (RFC section 十)."""
        home = tmp_path / "home"
        _write_skill(home / ".claude" / "skills", "u", "user skill", "b\n")
        sources = discover_candidate_sources(None, cwd=str(tmp_path), user_home=home)
        claude = [s for s in sources if s.dialect == "claude" and s.scope == "user"]
        assert len(claude) == 1

    def test_admin_scope(self, tmp_path):
        """Admin root is discovered with scope 'admin' and read_only."""
        admin = tmp_path / "etc" / "electromind" / "skills"
        _write_skill(admin, "op", "ops skill", "b\n")
        sources = discover_candidate_sources(
            None, cwd=str(tmp_path), admin_root=str(admin)
        )
        admin_srcs = [s for s in sources if s.scope == "admin"]
        assert len(admin_srcs) == 1
        assert admin_srcs[0].read_only is True
        assert admin_srcs[0].dialect == "electromind"

    def test_add_dir_roots(self, tmp_path):
        """configured_roots map to scope 'add_dir'."""
        proj = tmp_path / "proj"
        proj.mkdir()
        extra = tmp_path / "extra-skills"
        _write_skill(extra, "x", "extra", "b\n")
        sources = discover_candidate_sources(
            str(proj), cwd=str(proj), configured_roots=(extra,)
        )
        add = [s for s in sources if s.scope == "add_dir"]
        assert len(add) == 1
        assert add[0].root == extra.resolve()

    def test_priority_order(self, tmp_path):
        """Ordering follows RFC section 三: admin > user > project > add_dir."""
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_skill(proj / ".agents" / "skills", "p", "proj", "b\n")
        home = tmp_path / "home"
        _write_skill(home / ".agents" / "skills", "u", "user", "b\n")
        admin = tmp_path / "admin"
        _write_skill(admin, "a", "admin", "b\n")
        extra = tmp_path / "extra"
        _write_skill(extra, "x", "extra", "b\n")

        sources = discover_candidate_sources(
            str(proj),
            cwd=str(proj),
            user_home=home,
            admin_root=str(admin),
            configured_roots=(extra,),
            builtin_roots=(),
        )
        scopes = [s.scope for s in sources]
        # admin first, then user, then add_dir, then project
        assert scopes == ["admin", "user", "add_dir", "project"]

    def test_source_rank_nearest_project_first(self):
        """Within project scope, nearer ancestors rank before higher ones."""
        from electromind.skills.candidate import SkillSource

        far = SkillSource(
            source_id="p-far",
            scope="project",
            dialect="electromind",
            root=Path("/repo/skills"),
            project_root=Path("/repo"),
            distance_from_cwd=3,
            trust_domain="/repo",
        )
        near = SkillSource(
            source_id="p-near",
            scope="project",
            dialect="claude",
            root=Path("/repo/sub/.claude/skills"),
            project_root=Path("/repo/sub"),
            distance_from_cwd=1,
            trust_domain="/repo/sub",
        )
        assert source_rank(near) < source_rank(far)


# ---------------------------------------------------------------------------
# Candidates + Trust
# ---------------------------------------------------------------------------


class TestCandidatesAndTrust:
    def test_load_candidates_carries_qualified_ids(self, tmp_path):
        """Candidates carry project-scope qualified ids built from real source."""
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_skill(proj / ".agents" / "skills", "my-helper", "h", "b\n")
        sources = discover_candidate_sources(str(proj), cwd=str(proj))
        candidates = load_candidates(sources)

        helper = [c for c in candidates if c.descriptor.name == "my-helper"]
        assert len(helper) == 1
        assert helper[0].skill_id == f"project:{proj.name}:agents:my-helper"

    def test_untrusted_project_candidates_marked(self, tmp_path):
        """未信任项目的候选标记为 untrusted，且不进入模型 Catalog。"""
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_skill(proj / ".agents" / "skills", "secret", "private", "b\n")
        home = tmp_path / "home"
        _write_skill(home / ".agents" / "skills", "pub", "public", "b\n")

        # Trust evaluator: only the user home is trusted; proj is NOT.
        def evaluator(project_root: Path | None) -> bool:
            return project_root is None or str(project_root) != str(proj.resolve())

        sources = discover_candidate_sources(str(proj), cwd=str(proj), user_home=home)
        candidates = load_candidates(sources, is_project_trusted=evaluator)

        by_name = {c.descriptor.name: c for c in candidates}
        assert by_name["secret"].trust_state == "untrusted"
        assert by_name["pub"].trust_state == "trusted"

        visible = model_visible_candidates(candidates)
        visible_names = {c.descriptor.name for c in visible}
        assert "secret" not in visible_names
        assert "pub" in visible_names

    def test_user_and_admin_default_trusted(self, tmp_path):
        """User/admin scope candidates default to trusted without a store."""
        home = tmp_path / "home"
        _write_skill(home / ".agents" / "skills", "u", "user", "b\n")
        admin = tmp_path / "admin"
        _write_skill(admin, "a", "admin", "b\n")

        sources = discover_candidate_sources(
            None, cwd=str(tmp_path), user_home=home, admin_root=str(admin)
        )
        candidates = load_candidates(sources)  # no evaluator → default trusted
        assert all(c.trust_state == "trusted" for c in candidates)

    def test_fingerprint_changes_with_content(self, tmp_path):
        """Per-source fingerprint detects content changes."""
        proj = tmp_path / "proj"
        proj.mkdir()
        skill_dir = _write_skill(proj / ".agents" / "skills", "s", "v1", "body1\n")
        sources = discover_candidate_sources(str(proj), cwd=str(proj))
        fp1 = fingerprint_source([s for s in sources if s.scope == "project"][0])

        (skill_dir / "SKILL.md").write_text(
            "---\nname: s\ndescription: v2\n---\nbody2\n", encoding="utf-8"
        )
        sources2 = discover_candidate_sources(str(proj), cwd=str(proj))
        fp2 = fingerprint_source([s for s in sources2 if s.scope == "project"][0])
        assert fp1 != fp2


# ---------------------------------------------------------------------------
# Real repo smoke test
# ---------------------------------------------------------------------------


def test_repo_bundle_found_from_subdir():
    """从仓库真实子目录（本测试目录）可发现仓库根 skills/ bundle。"""
    cwd = REPO_ROOT / "tests"
    sources = discover_candidate_sources(str(REPO_ROOT), cwd=str(cwd))
    candidates = load_candidates(sources)

    names = {c.descriptor.name for c in candidates}
    assert "hpc-submit" in names
    assert "rsess" in names
    # Repo skills are trusted by default when no evaluator is wired.
    assert all(c.trust_state == "trusted" for c in candidates)
