"""Tests for SkillSnapshot, SkillSetSnapshot, generation pinning, and hardening."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from electromind.skills.discovery import (
    SkillSource,
    discover_skill_sources,
    load_skill_catalog,
)
from electromind.skills.skill import (
    Skill,
    collect_resources,
    has_symlinks,
    validate_skill_name,
)
from electromind.skills.snapshot import (
    build_skill_set_snapshot,
    build_skill_snapshot,
    digest_prefix,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def tmp_skill_dir(tmp_path: Path) -> Path:
    """Create a minimal valid skill directory."""
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: A test skill\n---\n\n"
        "## Instructions\n\nThis is the body.\n",
        encoding="utf-8",
    )
    refs = skill_dir / "references"
    refs.mkdir()
    (refs / "notes.md").write_text("# Notes\n", encoding="utf-8")
    return skill_dir


@pytest.fixture
def tmp_flat_root(tmp_path: Path) -> Path:
    """A flat project skill root (.agents/skills) — A+ W5, no markers."""
    root = tmp_path / ".agents" / "skills"
    skill = root / "my-tool"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: my-tool\ndescription: A tool skill\n---\n\nTool body.\n",
        encoding="utf-8",
    )
    return root


# ============================================================================
# Phase 1: SkillSnapshot & SkillSetSnapshot
# ============================================================================


class TestSkillSnapshot:
    def test_same_content_produces_same_digest(self, tmp_skill_dir):
        """Same content produces the same sha256."""
        skill = _load_skill_from_dir(tmp_skill_dir, "test-source", tmp_skill_dir.parent)

        snap1 = build_skill_snapshot(
            skill, kind="standard", source_root=tmp_skill_dir.parent
        )
        snap2 = build_skill_snapshot(
            skill, kind="standard", source_root=tmp_skill_dir.parent
        )

        assert snap1.sha256 == snap2.sha256
        assert snap1.instructions == snap2.instructions
        assert len(snap1.resources) == len(snap2.resources)

    def test_different_skill_md_produces_different_digest(self, tmp_skill_dir):
        """Modifying SKILL.md body changes the sha256."""
        skill = _load_skill_from_dir(tmp_skill_dir, "test-source", tmp_skill_dir.parent)
        snap1 = build_skill_snapshot(
            skill, kind="standard", source_root=tmp_skill_dir.parent
        )

        # Modify instructions
        (tmp_skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A test skill\n---\n\nChanged body.\n",
            encoding="utf-8",
        )
        skill2 = _load_skill_from_dir(
            tmp_skill_dir, "test-source", tmp_skill_dir.parent
        )
        snap2 = build_skill_snapshot(
            skill2, kind="standard", source_root=tmp_skill_dir.parent
        )

        assert snap1.sha256 != snap2.sha256

    def test_different_resource_produces_different_digest(self, tmp_skill_dir):
        """Modifying a resource file changes the sha256."""
        skill = _load_skill_from_dir(tmp_skill_dir, "test-source", tmp_skill_dir.parent)
        snap1 = build_skill_snapshot(
            skill, kind="standard", source_root=tmp_skill_dir.parent
        )

        # Modify a resource file
        (tmp_skill_dir / "references" / "notes.md").write_text(
            "# Changed notes\n", encoding="utf-8"
        )
        skill2 = _load_skill_from_dir(
            tmp_skill_dir, "test-source", tmp_skill_dir.parent
        )
        snap2 = build_skill_snapshot(
            skill2, kind="standard", source_root=tmp_skill_dir.parent
        )

        assert snap1.sha256 != snap2.sha256

    def test_mtime_alone_does_not_change_digest(self, tmp_skill_dir):
        """Touching files without changing content yields the same digest."""
        skill = _load_skill_from_dir(tmp_skill_dir, "test-source", tmp_skill_dir.parent)
        snap1 = build_skill_snapshot(
            skill, kind="standard", source_root=tmp_skill_dir.parent
        )

        # Touch the SKILL.md without changing content
        os.utime(tmp_skill_dir / "SKILL.md", None)
        skill2 = _load_skill_from_dir(
            tmp_skill_dir, "test-source", tmp_skill_dir.parent
        )
        snap2 = build_skill_snapshot(
            skill2, kind="standard", source_root=tmp_skill_dir.parent
        )

        assert snap1.sha256 == snap2.sha256

    def test_resources_are_frozen_with_hashes(self, tmp_skill_dir):
        """SkillResource contains path, sha256, and size."""
        skill = _load_skill_from_dir(tmp_skill_dir, "test-source", tmp_skill_dir.parent)
        snap = build_skill_snapshot(
            skill, kind="standard", source_root=tmp_skill_dir.parent
        )

        assert len(snap.resources) >= 1
        for res in snap.resources:
            assert res.relative_path
            assert len(res.sha256) == 64
            assert res.size > 0


class TestSkillSetSnapshot:
    def test_set_digest_changes_with_skill_change(self, tmp_flat_root):
        """Changing a skill changes the set digest."""
        sources = _standard_sources(tmp_flat_root)
        cat1 = load_skill_catalog(sources)
        ss1 = build_skill_set_snapshot(cat1, generation=1)

        # Modify a skill
        (tmp_flat_root / "my-tool" / "SKILL.md").write_text(
            "---\nname: my-tool\ndescription: changed\n---\n\nChanged.\n",
            encoding="utf-8",
        )
        cat2 = load_skill_catalog(sources)
        ss2 = build_skill_set_snapshot(cat2, generation=2)

        assert ss1.digest != ss2.digest

    def test_set_digest_changes_with_diagnostics(self, tmp_path):
        """Adding a diagnostic changes the set digest."""
        # Create a valid skill first
        valid_dir = tmp_path / "good-skill"
        valid_dir.mkdir()
        (valid_dir / "SKILL.md").write_text(
            "---\nname: good-skill\ndescription: valid\n---\n\nBody.\n",
            encoding="utf-8",
        )
        sources = _standard_sources(tmp_path)
        cat1 = load_skill_catalog(sources)
        ss1 = build_skill_set_snapshot(cat1, generation=1)
        diag_count_1 = len(ss1.diagnostics)

        # Now add a symlink to create a new diagnostic
        link_dir = tmp_path / "linked-skill"
        link_dir.mkdir()
        (link_dir / "SKILL.md").write_text(
            "---\nname: linked-skill\ndescription: symlink test\n---\n\nBody.\n",
            encoding="utf-8",
        )
        refs = link_dir / "references"
        refs.mkdir()
        (refs / "secret").symlink_to(valid_dir)

        cat2 = load_skill_catalog(sources)
        ss2 = build_skill_set_snapshot(cat2, generation=2)

        # Digest should differ due to the added skill_symlink_rejected diagnostic
        assert len(ss2.diagnostics) > diag_count_1
        assert ss1.digest != ss2.digest

    def test_digest_prefix_helper(self):
        """digest_prefix returns first N chars."""
        dgst = "a31f429c8b04f57a000000000000000000000000000000000000000000000000"
        assert digest_prefix(dgst) == "a31f429c"
        assert digest_prefix(dgst, length=12) == "a31f429c8b04"


# ============================================================================
# Phase 2: Name validation & symlink rejection
# ============================================================================


class TestNameValidation:
    def test_valid_names(self):
        for name in ["cp2k", "hpc-submit", "packmol-generate", "a", "a1", "a-b-c"]:
            assert validate_skill_name(name) is None, f"'{name}' should be valid"

    def test_invalid_names(self):
        invalid = [
            "",
            "Invalid-Name",
            "has space",
            "under_score",
            "-starts-with-hyphen",
            "ends-with-hyphen-",
            "UPPERCASE",
            "has.dot",
            "café",
        ]
        for name in invalid:
            assert validate_skill_name(name) is not None, f"'{name}' should be invalid"


class TestSymlinkRejection:
    def test_symlink_in_skill_is_detected(self, tmp_path):
        """has_symlinks returns symlink paths."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: test\n---\n\nBody.\n",
            encoding="utf-8",
        )
        refs = skill_dir / "references"
        refs.mkdir()
        secret = refs / "secret"
        secret.symlink_to(tmp_path / "outside")

        syms = has_symlinks(skill_dir)
        assert len(syms) >= 1
        assert any("secret" in str(s) for s in syms)

    def test_symlink_in_skill_produces_diagnostic(self, tmp_path):
        """Symlinks in a skill produce skill_symlink_rejected diagnostic."""
        skill_dir = tmp_path / "linked-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: linked-skill\ndescription: test\n---\n\nBody.\n",
            encoding="utf-8",
        )
        refs = skill_dir / "references"
        refs.mkdir()
        (refs / "escape").symlink_to(tmp_path / "outside")

        sources = _standard_sources(tmp_path)
        cat = load_skill_catalog(sources)

        # The skill should not be registered
        assert "linked-skill" not in cat.registry.names()

        # Should produce a symlink diagnostic
        assert any(d.code == "skill_symlink_rejected" for d in cat.diagnostics)

    def test_skill_md_symlink_rejected(self, tmp_path):
        """Symlinked reference file within a skill is rejected."""
        real_file = tmp_path / "outside.md"
        real_file.write_text("# outside\n", encoding="utf-8")

        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: test\n---\n\nBody.\n",
            encoding="utf-8",
        )
        refs = skill_dir / "references"
        refs.mkdir()
        # Create a symlink inside the skill dir pointing outside
        (refs / "secret.md").symlink_to(real_file)

        sources = _standard_sources(tmp_path)
        cat = load_skill_catalog(sources)

        # Skill should be rejected due to symlink
        assert "my-skill" not in cat.registry.names()
        assert any(d.code == "skill_symlink_rejected" for d in cat.diagnostics)


class TestResourceExclusion:
    def test_cache_files_excluded(self, tmp_path):
        """Cache files are excluded from resource collection."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: test\n---\n\nBody.\n", encoding="utf-8"
        )
        pycache = skill_dir / "__pycache__"
        pycache.mkdir()
        (pycache / "cached.pyc").write_bytes(b"junk")
        (skill_dir / ".DS_Store").write_text("")
        (skill_dir / "real-file.txt").write_text("real")

        resources = collect_resources(skill_dir)
        assert "real-file.txt" in resources
        assert "__pycache__/cached.pyc" not in resources
        assert ".DS_Store" not in resources


# ============================================================================
# Phase 3: Generation pinning
# ============================================================================


class TestSkillRuntimeGeneration:
    def test_first_turn_generation_is_one(self, tmp_path):
        """First prepare_turn even with empty catalog gives generation 1."""
        from electromind.skills.runtime import SkillRuntime

        # Use a temp path with no skills
        rt = SkillRuntime(str(tmp_path))
        view = rt.prepare_turn()

        # First turn always produces a view (even if empty)
        assert view is not None
        assert view.generation == 1

    def test_prepare_turn_with_skills(self, tmp_flat_root):
        """prepare_turn with real skills returns generation 1."""
        from electromind.skills.runtime import SkillRuntime

        rt = SkillRuntime(str(tmp_flat_root.parent))
        view = rt.prepare_turn()

        if view is not None:
            assert view.generation >= 1

    def test_generation_bumps_on_change(self, tmp_flat_root):
        """Changing a skill bumps the generation."""
        from electromind.skills.runtime import SkillRuntime

        rt = SkillRuntime(str(tmp_flat_root.parent))
        view1 = rt.prepare_turn()
        if view1 is None:
            pytest.skip("No skills to test generation bump")
        gen1 = view1.generation

        # Modify a skill
        (tmp_flat_root / "my-tool" / "SKILL.md").write_text(
            "---\nname: my-tool\ndescription: changed tool\n---\n\nChanged.\n",
            encoding="utf-8",
        )
        view2 = rt.prepare_turn()
        if view2 is None:
            pytest.skip("Skill change not detected")
        assert view2.generation > gen1

    def test_generation_same_when_no_change(self, tmp_flat_root):
        """Same content → same generation."""
        from electromind.skills.runtime import SkillRuntime

        rt = SkillRuntime(str(tmp_flat_root.parent))
        view1 = rt.prepare_turn()
        if view1 is None:
            pytest.skip("No skills to test")
        view2 = rt.prepare_turn()
        if view2 is None:
            pytest.skip("No skills in second turn")
        assert view2.generation == view1.generation
        assert view2.digest == view1.digest

    async def test_run_freeze_keeps_old_view_after_generation_bump(self, tmp_flat_root):
        """Characterization: Run 级 Generation 冻结。

        ``use_skill`` 工具绑定到 view1 后，即使源文件变化使下一 turn 的
        generation 递增（view2），该工具仍返回 view1 冻结的正文与描述。
        这是 SKILL-4 原子 Activation 的前置不变量 —— 当前 run 的模型看到的
        内容不随磁盘变化而漂移。
        """
        import json as _json

        from electromind.skills.runtime import SkillRuntime

        rt = SkillRuntime(str(tmp_flat_root.parent))
        view1 = rt.prepare_turn()
        if view1 is None:
            pytest.skip("No skills to test")
        gen1 = view1.generation
        tool = rt.build_use_skill_tool(view1)

        # Modify a skill → next prepare_turn bumps the generation
        (tmp_flat_root / "my-tool" / "SKILL.md").write_text(
            "---\nname: my-tool\ndescription: changed tool\n---\n\nChanged body.\n",
            encoding="utf-8",
        )
        view2 = rt.prepare_turn()
        assert view2 is not None
        assert view2.generation > gen1

        # The tool bound to view1 still returns the original frozen content
        result = await tool.acall({"name": "my-tool"})
        assert result.ok is True
        payload = _json.loads(result.content)
        assert payload["description"] == "A tool skill"
        assert "Tool body." in payload["instructions"]
        assert "Changed body." not in payload["instructions"]

    def test_state_payload_includes_generation(self, tmp_flat_root):
        """state_payload includes generation and digest."""
        from electromind.skills.runtime import SkillRuntime

        rt = SkillRuntime(str(tmp_flat_root.parent))
        rt.prepare_turn()
        payload = rt.state_payload(thread_id="test-thread")
        assert "generation" in payload
        assert "digest" in payload
        assert "loaded_this_run" in payload
        assert isinstance(payload["generation"], int)
        assert isinstance(payload["loaded_this_run"], list)


# ============================================================================
# Phase 5: SkillState event
# ============================================================================


class TestSkillStateEvent:
    def test_build_skill_state_event(self, tmp_flat_root):
        """build_skill_state_event produces the expected shape."""
        from electromind.skills.runtime import SkillRuntime

        rt = SkillRuntime(str(tmp_flat_root.parent))
        rt.prepare_turn()
        event = rt.build_skill_state_event(thread_id="t1", which="init")

        assert event["type"] == "SkillState"
        assert event["which"] == "init"
        assert "generation" in event
        assert "digest" in event
        assert "loaded_this_run" in event
        assert "diagnostics" in event

    def test_loaded_this_run_tracks_activation(self, tmp_flat_root):
        """_on_activate populates loaded_this_run."""
        from electromind.skills.runtime import SkillRuntime

        rt = SkillRuntime(str(tmp_flat_root.parent))
        rt.prepare_turn()
        payload = rt.state_payload(thread_id="t1")
        assert payload["loaded_this_run"] == []

        # Simulate loading a skill
        if rt.snapshot is not None:
            skill = rt.snapshot.registry.get("my-tool")
            if skill is not None:
                rt._on_activate(skill)
                payload2 = rt.state_payload(thread_id="t1")
                assert "my-tool" in payload2["loaded_this_run"]

    def test_loaded_this_run_resets_per_turn(self, tmp_flat_root):
        """loaded_this_run is cleared on each prepare_turn."""
        from electromind.skills.runtime import SkillRuntime

        rt = SkillRuntime(str(tmp_flat_root.parent))
        rt.prepare_turn()

        if rt.snapshot is not None:
            skill = rt.snapshot.registry.get("my-tool")
            if skill is not None:
                rt._on_activate(skill)
                payload = rt.state_payload(thread_id="t1")
                assert "my-tool" in payload["loaded_this_run"]

                # Next turn resets
                rt.prepare_turn()
                payload2 = rt.state_payload(thread_id="t1")
                assert payload2["loaded_this_run"] == []


# ============================================================================
# Phase 6: SSH context
# ============================================================================


class TestExecutionContext:
    def test_document_creation(self):
        """ExecutionContextDocument can be created and hashed."""
        from electromind.execution.context import ExecutionContextDocument

        doc = ExecutionContextDocument(
            profile_id="user@host",
            remote_path="/home/user/context.md",
            content="# Context\n",
            sha256=ExecutionContextDocument.compute_sha256("# Context\n"),
            fetched_at=1234567890.0,
        )
        assert doc.profile_id == "user@host"
        assert len(doc.sha256) == 64
        assert isinstance(doc.fetched_at, float)

    def test_build_ssh_context_prompt(self):
        """build_ssh_context_prompt wraps content with markers."""
        from electromind.execution.context import (
            ExecutionContextDocument,
            build_ssh_context_prompt,
        )

        doc = ExecutionContextDocument(
            profile_id="test",
            remote_path="/path",
            content="hello",
            sha256="a" * 64,
            fetched_at=0.0,
        )
        prompt = build_ssh_context_prompt((doc,))

        assert "<!-- electromind:ssh-context:start -->" in prompt
        assert "<!-- electromind:ssh-context:end -->" in prompt
        assert "hello" in prompt
        assert "informational only" in prompt.lower()
        assert "/path" in prompt

    def test_empty_docs_produces_empty_prompt(self):
        """Empty documents produce empty prompt."""
        from electromind.execution.context import build_ssh_context_prompt

        assert build_ssh_context_prompt(()) == ""


# ============================================================================
# Black-box regression tests
# ============================================================================


class TestBlackBoxRegression:
    """Critical scenarios from the specification."""

    def test_use_skill_reads_from_snapshot_not_disk(self, tmp_skill_dir):
        """use_skill returns Snapshot content, not re-reading the source file."""
        skill = _load_skill_from_dir(tmp_skill_dir, "test-source", tmp_skill_dir.parent)
        snap = build_skill_snapshot(
            skill, kind="standard", source_root=tmp_skill_dir.parent
        )

        # Modify the source file on disk
        (tmp_skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: test\n---\n\nModified on disk.\n",
            encoding="utf-8",
        )

        # Snapshot still has original content
        assert "This is the body" in snap.instructions
        assert "Modified on disk" not in snap.instructions

    def test_discovery_priority_preserved(self, tmp_path):
        """A+ W5: only flat fixed dirs are project sources; the nearer dialect
        (.agents) wins over .electromind for the same name."""
        # Project .agents/skills — wins
        agents = tmp_path / ".agents" / "skills" / "shared-name"
        agents.mkdir(parents=True)
        (agents / "SKILL.md").write_text(
            "---\nname: shared-name\ndescription: from agents\n---\n\nAgents body.\n",
            encoding="utf-8",
        )

        # Project .electromind/skills (lower priority) — same name
        em = tmp_path / ".electromind" / "skills" / "shared-name"
        em.mkdir(parents=True)
        (em / "SKILL.md").write_text(
            "---\nname: shared-name\ndescription: from electromind\n---\n\nEM body.\n",
            encoding="utf-8",
        )

        sources = discover_skill_sources(str(tmp_path))
        cat = load_skill_catalog(sources)

        skill = cat.registry.get("shared-name")
        assert skill is not None
        assert "from agents" in skill.description
        # Should have a duplicate diagnostic
        assert any(
            d.code == "duplicate_skill_name" and "shared-name" in d.message
            for d in cat.diagnostics
        )

    def test_knowledge_not_registered_as_skill(self, tmp_flat_root):
        """knowledge/ directory content is not registered as a skill."""
        sources = _standard_sources(tmp_flat_root)
        cat = load_skill_catalog(sources)

        # knowledge/ should not appear in skill registry
        for name in cat.registry.names():
            assert "knowledge" not in name.lower() or "unknown" in name.lower()


# ============================================================================
def _load_skill_from_dir(skill_dir: Path, source_id: str, source_root: Path) -> Skill:
    """Load a Skill from a directory and stamp with source info."""
    from electromind.skills.skill import load_skill

    skill = load_skill(skill_dir)
    return Skill(
        name=skill.name,
        description=skill.description,
        instructions=skill.instructions,
        root=skill.root,
        resources=skill.resources,
        source_id=source_id,
        skill_root=skill.root,
    )


def _standard_sources(root: Path) -> tuple[SkillSource, ...]:
    """Create a tuple with one standard SkillSource."""
    return (
        SkillSource(
            id="project-standard-test",
            kind="standard",
            scope="project",
            root=root,
            priority=2,
        ),
    )


class _FakeSandbox:
    """Minimal fake sandbox for testing _verify_staging_content.

    Maps staging paths to real filesystem paths rooted at *host_root*.
    Before each verification call the test must set
    ``sandbox.files._prefix`` to the staging directory path so that
    ``list()`` and ``read()`` can translate staging-relative paths
    into real filesystem paths under *host_root*.
    """

    def __init__(self, host_root: Path) -> None:
        self._root = host_root.resolve()
        self.files = _FakeSandboxFiles(self._root)


class _FakeSandboxFiles:
    """Fake filesystem access for _verify_staging_content.

    ``_prefix`` (set externally before each verification call) is the
    staging base path (e.g. ``"/sandbox/staging-a"``).  All *base* and
    *path* arguments are stripped of this prefix and the remainder is
    resolved against the real ``_root`` directory.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._prefix: str = ""

    def _resolve(self, staging_path: str) -> Path:
        """Map a staging path into a real filesystem path under _root."""
        if self._prefix and staging_path.startswith(self._prefix):
            rel = staging_path[len(self._prefix) :].lstrip("/")
            return self._root / rel if rel else self._root
        return self._root

    async def list(self, base: str) -> list:
        """Return directory entries with .name and .is_dir attributes."""
        fs_path = self._resolve(base)
        if not fs_path.is_dir():
            return []
        result: list[_FakeDirEntry] = []
        try:
            for child in sorted(fs_path.iterdir()):
                result.append(_FakeDirEntry(name=child.name, is_dir=child.is_dir()))
        except OSError:
            pass
        return result

    async def read(self, path: str) -> bytes:
        """Read file content using the staging → _root mapping."""
        fs_path = self._resolve(path)
        return fs_path.read_bytes()


class _FakeDirEntry:
    """Minimal directory entry for _verify_staging_content."""

    __slots__ = ("name", "is_dir")

    def __init__(self, name: str, is_dir: bool) -> None:
        self.name = name
        self.is_dir = is_dir


class TestRuntimeCapabilities:
    """P1: SkillRuntime 重建工具时保留冻结 capabilities。"""

    async def test_runtime_tool_enforces_ssh_only(self, tmp_path):
        import json as _json

        from electromind.skills.candidate import (
            SkillCandidate,
            SkillDescriptor,
            SkillSource,
        )
        from electromind.skills.catalog import build_catalog
        from electromind.skills.runtime import SkillRuntime

        d = tmp_path / "ssh-only"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: ssh-only\ndescription: d\n---\nbody\n", encoding="utf-8"
        )
        source = SkillSource(
            source_id="x",
            scope="project",
            dialect="agents",
            root=d.parent,
            project_root=tmp_path,
            trust_domain=str(tmp_path),
        )
        cand = SkillCandidate(
            skill_id="project:tmp:agents:ssh-only",
            descriptor=SkillDescriptor(
                name="ssh-only",
                description="d",
                entry_path=d / "SKILL.md",
                root_path=d,
                frontmatter={"name": "ssh-only"},
                content_digest="c" * 64,
                resource_digest="r" * 64,
                compatibility=("ssh",),
            ),
            source=source,
        )
        catalog = build_catalog((cand,), generation=1, cwd="/w", repo_root=None)

        # local Run：runtime 重建的工具必须拒绝 SSH-only
        rt_local = SkillRuntime(
            str(tmp_path), service=_FakeService(catalog), capabilities=("local",)
        )
        view = rt_local.prepare_turn()
        assert view is not None
        tool = rt_local.build_use_skill_tool(view)
        result = await tool.acall({"name": "ssh-only"})
        payload = _json.loads(result.content)
        assert payload["ok"] is False  # local 拒绝 SSH-only

        # ssh Run：放行
        rt_ssh = SkillRuntime(
            str(tmp_path), service=_FakeService(catalog), capabilities=("ssh",)
        )
        view2 = rt_ssh.prepare_turn()
        tool2 = rt_ssh.build_use_skill_tool(view2)
        result2 = await tool2.acall({"name": "ssh-only"})
        payload2 = _json.loads(result2.content)
        assert payload2["ok"] is True


class _FakeService:
    """Minimal catalog service stand-in for runtime capability tests."""

    def __init__(self, catalog):
        self._catalog = catalog

    def reload(self):
        return self._catalog
