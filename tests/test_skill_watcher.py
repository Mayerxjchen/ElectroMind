"""SKILL-7 tests: watcher (debounce, fingerprint dedup, run freeze) + context roots."""

from pathlib import Path

from electromind.skills.catalog_service import SkillCatalogService
from electromind.skills.watcher import (
    ContextRoots,
    SkillWatcher,
    discover_with_context_roots,
)


def _write_skill(root: Path, name: str, description: str, body: str) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}",
        encoding="utf-8",
    )
    return d


class TestSkillWatcher:
    def test_debounce_and_fingerprint_dedup(self, tmp_path):
        """重复事件 → fingerprint 去重 → 只 bump 一次 generation。"""
        proj = tmp_path / "proj"
        proj.mkdir()
        skill_dir = _write_skill(proj / ".agents" / "skills", "a", "v1", "body1\n")
        service = SkillCatalogService(project_path=str(proj), cwd=str(proj))
        watcher = SkillWatcher(service, interval=0.01, debounce=0.0)

        service.list()  # generation 1
        (skill_dir / "SKILL.md").write_text(
            "---\nname: a\ndescription: v2\n---\nbody2\n", encoding="utf-8"
        )

        # Multiple ticks with unchanged content between them
        assert watcher.poll_once() is True  # first change → reload
        assert watcher.poll_once() is False  # same content → dedup, no reload
        assert watcher.reload_count == 1
        assert service.list().generation == 2  # bumped exactly once

    def test_generation_freeze_current_run(self, tmp_path):
        """修改 Skill 后当前 Run 不变，下一 Run 使用新 Generation。"""
        proj = tmp_path / "proj"
        proj.mkdir()
        skill_dir = _write_skill(proj / ".agents" / "skills", "a", "v1", "body1\n")
        service = SkillCatalogService(project_path=str(proj), cwd=str(proj))
        watcher = SkillWatcher(service, interval=0.01, debounce=0.0)

        # The run freezes a view at generation 1
        frozen = service.list()
        assert frozen.generation == 1

        # Content changes; watcher reloads → generation 2
        (skill_dir / "SKILL.md").write_text(
            "---\nname: a\ndescription: v2\n---\nbody2\n", encoding="utf-8"
        )
        watcher.poll_once()
        current = service.list()
        assert current.generation == 2

        # The frozen run view is unchanged (digest + candidates identical)
        assert frozen.catalog_digest != current.catalog_digest
        assert frozen.generation == 1

    def test_no_change_no_reload(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_skill(proj / ".agents" / "skills", "a", "v1", "body1\n")
        service = SkillCatalogService(project_path=str(proj), cwd=str(proj))
        watcher = SkillWatcher(service, interval=0.01, debounce=0.0)

        service.list()
        assert watcher.poll_once() is False
        assert service.list().generation == 1

    def test_context_roots_tracking(self, tmp_path):
        roots = ContextRoots()
        sub = tmp_path / "monorepo" / "packages" / "water"
        roots.add(sub)
        assert len(roots) == 1
        assert roots.paths() == (sub.resolve(),)
        roots.add(sub)  # idempotent
        assert len(roots) == 1
        roots.remove(sub)
        assert len(roots) == 0

    def test_discover_with_context_roots(self, tmp_path):
        """Agent 进入子项目后，该子路径上的固定 Skill 目录被发现。"""
        proj = tmp_path / "monorepo"
        proj.mkdir()
        _write_skill(proj / ".agents" / "skills", "root-skill", "r", "b\n")
        sub = proj / "packages" / "water"
        _write_skill(sub / ".claude" / "skills", "water-skill", "w", "b\n")

        service = SkillCatalogService(project_path=str(proj), cwd=str(proj))
        base_names = {s.root.name for s in service.sources()}
        assert ".agents" not in base_names  # root .agents/skills IS found
        # context root discovery finds the subproject's .claude/skills
        sources = discover_with_context_roots(service, (sub,))
        found = {str(s.root) for s in sources}
        assert str((sub / ".claude" / "skills").resolve()) in found
        assert str((proj / ".agents" / "skills").resolve()) in found


class TestWatcherThroughRuntime:
    """SKILL-7 收尾：watcher 接入 SkillRuntime（下一 turn 用新 generation）。"""

    def test_runtime_watcher_updates_next_turn(self, tmp_path):
        from electromind.skills.catalog_service import SkillCatalogService
        from electromind.skills.runtime import SkillRuntime

        proj = tmp_path / "proj"
        proj.mkdir()
        skill_dir = proj / ".agents" / "skills" / "a"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: a\ndescription: v1\n---\nbody1\n", encoding="utf-8"
        )

        # Runtime 使用独立 service（非进程共享），watcher 附着其上
        service = SkillCatalogService(
            project_path=str(proj), cwd=str(proj), builtin_roots=()
        )
        rt = SkillRuntime(str(proj), service=service)
        view1 = rt.prepare_turn()
        assert view1 is not None
        assert view1.generation == 1

        watcher = rt.attach_watcher(interval=0.01, debounce=0.0)
        try:
            # 内容变化 → watcher reload → 下一 turn 新 generation
            (skill_dir / "SKILL.md").write_text(
                "---\nname: a\ndescription: v2\n---\nbody2\n", encoding="utf-8"
            )
            assert watcher.poll_once() is True

            view2 = rt.prepare_turn()
            assert view2 is not None
            assert view2.generation == 2
            assert view2.digest != view1.digest
        finally:
            watcher.stop()
