"""SKILL-1 tests: SkillSource / SkillDescriptor / SkillCandidate / Qualified ID.

These lock in the RFC target model introduced alongside the legacy pipeline.
The legacy behavior (SkillRegistry, discovery) is unchanged — see
test_electromind_skills.py / test_skills_snapshot.py for those guarantees.
"""

from pathlib import Path

import pytest

from electromind.skills.candidate import (
    QualifiedSkillID,
    SkillCandidate,
    SkillDescriptor,
    SkillSource,
    build_candidate,
    build_descriptor,
    candidates_from_catalog,
    make_skill_id,
    registry_from_candidates,
    validate_agents_frontmatter,
    validate_agents_skill_dir,
)
from electromind.skills.discovery import (
    SkillSource as LegacySkillSource,
)
from electromind.skills.discovery import (
    discover_skill_sources,
    load_skill_catalog,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Qualified Skill ID
# ---------------------------------------------------------------------------


class TestQualifiedSkillID:
    @pytest.mark.parametrize(
        "text",
        [
            "builtin:procedure:cp2k",
            "user:agents:cp2k",
            "project:repo-root:agents:cp2k",
            "project:packages-water:claude:cp2k",
        ],
    )
    def test_parse_round_trip(self, text):
        """Parsing then serializing reproduces the exact RFC example id."""
        parsed = QualifiedSkillID.parse(text)
        assert str(parsed) == text

    def test_parse_fields(self):
        qid = QualifiedSkillID.parse("project:repo-root:agents:cp2k")
        assert qid.scope == "project"
        assert qid.name == "cp2k"
        assert qid.middle == ("repo-root", "agents")

    def test_parse_builtin_fields(self):
        qid = QualifiedSkillID.parse("builtin:procedure:cp2k")
        assert qid.scope == "builtin"
        assert qid.name == "cp2k"
        assert qid.middle == ("procedure",)

    def test_parse_malformed_raises(self):
        with pytest.raises(ValueError):
            QualifiedSkillID.parse("just-one")
        with pytest.raises(ValueError):
            QualifiedSkillID.parse(":empty-scope:name")
        with pytest.raises(ValueError):
            QualifiedSkillID.parse("scope:empty-name:")

    def test_make_skill_id_project(self):
        assert (
            make_skill_id(
                scope="project", name="cp2k", dialect="agents", project_dir="repo-root"
            )
            == "project:repo-root:agents:cp2k"
        )

    def test_make_skill_id_builtin(self):
        assert (
            make_skill_id(scope="builtin", name="cp2k", kind="procedure")
            == "builtin:procedure:cp2k"
        )

    def test_make_skill_id_user(self):
        assert (
            make_skill_id(scope="user", name="cp2k", dialect="agents")
            == "user:agents:cp2k"
        )

    def test_make_skill_id_project_requires_dir(self):
        with pytest.raises(ValueError):
            make_skill_id(scope="project", name="cp2k", dialect="agents")


# ---------------------------------------------------------------------------
# SkillSource (RFC model)
# ---------------------------------------------------------------------------


class TestSkillSourceModel:
    def test_rfc_shape_fields(self):
        src = SkillSource(
            source_id="project-standard-abc",
            scope="project",
            dialect="agents",
            root=Path("/proj/.agents/skills"),
            project_root=Path("/proj"),
            distance_from_cwd=0,
            trust_domain="project",
            read_only=False,
        )
        assert src.scope == "project"
        assert src.dialect == "agents"
        assert src.project_root == Path("/proj")
        assert src.read_only is False


# ---------------------------------------------------------------------------
# Descriptor + Candidate builders (compat parsing from legacy pipeline)
# ---------------------------------------------------------------------------


def _write_skill(root: Path, name: str, description: str, body: str) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}",
        encoding="utf-8",
    )
    return d


class TestCompatAdapter:
    def test_build_descriptor_from_skill(self, tmp_path):
        """build_descriptor preserves name/description/digest losslessly."""
        from electromind.skills.skill import load_skill

        skill_dir = _write_skill(tmp_path / "src", "greet", "Say hi", "body\n")
        skill = load_skill(skill_dir)
        descriptor = build_descriptor(skill)

        assert descriptor.name == "greet"
        assert descriptor.description == "Say hi"
        assert descriptor.entry_path == skill_dir / "SKILL.md"
        assert descriptor.root_path == skill_dir
        assert descriptor.content_digest == skill.sha256
        assert descriptor.frontmatter["name"] == "greet"

    def test_candidates_from_catalog_express_source_identity(self):
        """Every visible catalog skill becomes a candidate with scope + source."""
        from electromind.skills.discovery import SkillSource as LegacySkillSource

        sources = (
            LegacySkillSource(
                id="builtin:procedures",
                kind="standard",
                scope="project",
                root=(REPO_ROOT / "skills" / "procedures").resolve(),
                priority=1,
            ),
            LegacySkillSource(
                id="builtin:tools",
                kind="standard",
                scope="project",
                root=(REPO_ROOT / "skills" / "tools").resolve(),
                priority=1,
            ),
        )
        catalog = load_skill_catalog(sources)
        candidates = candidates_from_catalog(catalog)

        names = {c.descriptor.name for c in candidates}
        assert "hpc-submit" in names
        assert "rsess" in names

        for candidate in candidates:
            assert candidate.skill_id, "candidate must carry a qualified id"
            # The id's name segment matches the descriptor name
            qid = QualifiedSkillID.parse(candidate.skill_id)
            assert qid.name == candidate.descriptor.name
            # Source scope is preserved and non-empty
            assert candidate.source.scope in {"project", "add_dir", "user"}
            assert candidate.source.source_id

    def test_candidates_from_catalog_keep_count(self):
        """The candidate set matches the legacy registry one-to-one."""
        sources = discover_skill_sources(str(REPO_ROOT))
        catalog = load_skill_catalog(sources)
        candidates = candidates_from_catalog(catalog)
        assert len(candidates) == len(catalog.registry.list())

    def test_registry_from_candidates_first_wins(self, tmp_path):
        """registry_from_candidates drops later same-name candidates (compat)."""
        from electromind.skills.discovery import SkillSource as LSrc

        legacy_src = LSrc(
            id="user-standard-h1",
            kind="standard",
            scope="user",
            root=tmp_path / "home" / ".agents" / "skills",
            priority=20,
        )
        # Two candidates with the same name — first wins
        cand1 = SkillCandidate(
            skill_id="user:agents:dup",
            descriptor=SkillDescriptor(
                name="dup",
                description="first",
                entry_path=Path("/a/dup/SKILL.md"),
                root_path=Path("/a/dup"),
                frontmatter={"name": "dup"},
                content_digest="a" * 64,
                resource_digest="b" * 64,
            ),
            source=_legacy_to_source(legacy_src),
        )
        cand2 = SkillCandidate(
            skill_id="user:agents:dup",
            descriptor=SkillDescriptor(
                name="dup",
                description="second",
                entry_path=Path("/b/dup/SKILL.md"),
                root_path=Path("/b/dup"),
                frontmatter={"name": "dup"},
                content_digest="c" * 64,
                resource_digest="d" * 64,
            ),
            source=_legacy_to_source(legacy_src),
        )
        registry = registry_from_candidates((cand1, cand2))
        assert registry.names() == ["dup"]
        assert registry.get("dup").description == "first"

    def test_build_candidate_round_trip(self, tmp_path):
        """build_candidate expresses a legacy skill+source as a candidate."""
        from electromind.skills.skill import load_skill

        root = tmp_path / "proj"
        skills_dir = root / ".agents" / "skills"
        skill_dir = _write_skill(skills_dir, "my-helper", "helps", "body\n")

        skill = load_skill(skill_dir)
        legacy_src = LegacySkillSource(
            id="project-standard-h2",
            kind="standard",
            scope="project",
            root=skills_dir,
            priority=2,
        )
        candidate = build_candidate(skill, legacy_src)

        assert candidate.descriptor.name == "my-helper"
        assert candidate.source.scope == "project"
        assert candidate.source.project_root == root
        # project_dir is the project's directory name
        assert candidate.skill_id == f"project:{root.name}:agents:my-helper"


def _legacy_to_source(legacy: LegacySkillSource) -> SkillSource:
    """Minimal legacy→RFC source mapping used by tests."""
    return SkillSource(
        source_id=legacy.id,
        scope=legacy.scope,  # type: ignore[arg-type]
        dialect="agents",
        root=legacy.root,
        trust_domain=legacy.scope,
    )


# ---------------------------------------------------------------------------
# Agent Skills standard validator
# ---------------------------------------------------------------------------


class TestAgentsValidator:
    def test_valid_frontmatter_no_issues(self):
        errors, warnings = validate_agents_frontmatter(
            {"name": "greet", "description": "hi"}, dir_name="greet"
        )
        assert errors == []
        assert warnings == []

    def test_missing_description_is_error(self):
        errors, warnings = validate_agents_frontmatter({"name": "greet"})
        assert any("description" in e for e in errors)

    def test_missing_name_is_error(self):
        errors, _ = validate_agents_frontmatter({"description": "hi"})
        assert any("name" in e for e in errors)

    def test_invalid_name_is_error(self):
        errors, _ = validate_agents_frontmatter(
            {"name": "Bad Name", "description": "hi"}
        )
        assert any("invalid skill name" in e for e in errors)

    def test_name_dir_mismatch_is_error(self):
        """A+ W3：目录名 ≠ frontmatter name 是硬错误，不再是 warning。"""
        errors, warnings = validate_agents_frontmatter(
            {"name": "other", "description": "hi"}, dir_name="greet"
        )
        assert warnings == []
        assert any("does not match directory" in e for e in errors)

    def test_validate_skill_dir_ok(self, tmp_path):
        d = _write_skill(tmp_path, "good", "desc", "body\n")
        errors, warnings = validate_agents_skill_dir(d)
        assert errors == []
        assert warnings == []

    def test_validate_skill_dir_missing_file(self, tmp_path):
        missing = tmp_path / "nope"
        missing.mkdir()
        errors, _ = validate_agents_skill_dir(missing)
        assert any("missing SKILL.md" in e for e in errors)

    def test_validate_skill_dir_bad_frontmatter(self, tmp_path):
        d = tmp_path / "bad"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nnot: yaml: [: \n---\nbody\n", encoding="utf-8"
        )
        errors, _ = validate_agents_skill_dir(d)
        assert len(errors) >= 1
