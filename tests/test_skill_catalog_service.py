"""SKILL-6 tests: shared catalog service + wire skills commands + CLI flags.

CLI, Desktop, and Service must share one catalog (one Generation fact source).
"""

import json
from pathlib import Path

import pytest

from electromind.skills.catalog_service import (
    SkillCatalogService,
    get_shared_catalog_service,
    reset_shared_catalog_service,
    set_shared_catalog_service,
)


def _write_skill(root: Path, name: str, description: str, body: str) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}",
        encoding="utf-8",
    )
    return d


@pytest.fixture(autouse=True)
def _isolate_shared_service():
    reset_shared_catalog_service()
    yield
    reset_shared_catalog_service()


class TestSkillCatalogService:
    def test_generation_bumps_on_change(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        skill_dir = _write_skill(proj / ".agents" / "skills", "a", "v1", "body1\n")
        service = SkillCatalogService(
            project_path=str(proj), cwd=str(proj), builtin_roots=()
        )

        c1 = service.list()
        assert c1.generation == 1
        assert len(c1.candidates) == 1

        (skill_dir / "SKILL.md").write_text(
            "---\nname: a\ndescription: v2\n---\nbody2\n", encoding="utf-8"
        )
        c2 = service.reload()
        assert c2.generation == 2
        assert c2.catalog_digest != c1.catalog_digest

    def test_reload_same_content_same_generation(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_skill(proj / ".agents" / "skills", "a", "v1", "body1\n")
        service = SkillCatalogService(
            project_path=str(proj), cwd=str(proj), builtin_roots=()
        )

        c1 = service.list()
        c2 = service.reload()
        assert c2.generation == c1.generation

    def test_changed_detection(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        skill_dir = _write_skill(proj / ".agents" / "skills", "a", "v1", "body1\n")
        service = SkillCatalogService(
            project_path=str(proj), cwd=str(proj), builtin_roots=()
        )
        service.list()

        assert service.changed() is False
        (skill_dir / "SKILL.md").write_text(
            "---\nname: a\ndescription: v2\n---\nbody2\n", encoding="utf-8"
        )
        assert service.changed() is True
        # changed() does not bump generation
        assert service.list().generation == 1

    def test_get_by_qualified_id(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_skill(proj / ".agents" / "skills", "cp2k", "d", "body\n")
        service = SkillCatalogService(
            project_path=str(proj), cwd=str(proj), builtin_roots=()
        )
        candidate = service.get(f"project:{proj.name}:agents:cp2k")
        assert candidate is not None
        assert candidate.descriptor.name == "cp2k"
        assert service.get("user:agents:nope") is None

    def test_shared_singleton(self):
        a = get_shared_catalog_service()
        b = get_shared_catalog_service()
        assert a is b
        set_shared_catalog_service(None)
        c = get_shared_catalog_service()
        assert c is not a


class TestWireSkillsCommands:
    @pytest.fixture
    def captured(self, monkeypatch):
        """Capture _emit_jsonrpc calls instead of stdout."""
        from app import wire

        calls: list[tuple[str, dict]] = []

        def fake(method, params):
            calls.append((method, params))

        monkeypatch.setattr(wire, "_emit_jsonrpc", fake)
        return calls

    @pytest.mark.asyncio
    async def test_skills_list_command(self, tmp_path, monkeypatch, captured):
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_skill(proj / ".agents" / "skills", "cp2k", "d", "body\n")
        service = SkillCatalogService(
            project_path=str(proj), cwd=str(proj), builtin_roots=()
        )
        set_shared_catalog_service(service)

        from app import wire

        runner = None
        await wire.handle_command(
            {"cmd": "skills/list", "thread_id": "t1"},
            runner,
            config=None,
            state={},
        )
        method, params = captured[-1]
        assert method == "skills/list"
        assert params["generation"] == 1
        assert len(params["skills"]) == 1
        assert params["skills"][0]["name"] == "cp2k"

    @pytest.mark.asyncio
    async def test_skills_get_command(self, tmp_path, monkeypatch, captured):
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_skill(proj / ".agents" / "skills", "cp2k", "d", "body\n")
        service = SkillCatalogService(project_path=str(proj), cwd=str(proj))
        set_shared_catalog_service(service)

        from app import wire

        await wire.handle_command(
            {"cmd": "skills/get", "skill_id": f"project:{proj.name}:agents:cp2k"},
            None,
            config=None,
            state={},
        )
        method, params = captured[-1]
        assert method == "skills/get"
        assert params["found"] is True
        assert params["candidate"]["dialect"] == "agents"

    @pytest.mark.asyncio
    async def test_skills_changed_command(self, tmp_path, monkeypatch, captured):
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_skill(proj / ".agents" / "skills", "cp2k", "d", "body\n")
        service = SkillCatalogService(
            project_path=str(proj), cwd=str(proj), builtin_roots=()
        )
        service.list()
        set_shared_catalog_service(service)

        from app import wire

        await wire.handle_command(
            {"cmd": "skills/changed", "thread_id": "t1"},
            None,
            config=None,
            state={},
        )
        method, params = captured[-1]
        assert method == "skills/changed"
        assert params["changed"] is False


class TestCliSkillsFlags:
    def test_list_json(self, tmp_path, monkeypatch):
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_skill(proj / ".agents" / "skills", "cp2k", "d", "body\n")
        monkeypatch.chdir(proj)

        from app.commands import skills as skills_cmd

        out = _run_capture(skills_cmd.run, ["list", "--json"])
        payload = json.loads(out)
        assert payload["generation"] == 1
        assert payload["candidates"][0]["name"] == "cp2k"

    def test_reload_prints_generation(self, tmp_path, monkeypatch):
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_skill(proj / ".agents" / "skills", "cp2k", "d", "body\n")
        monkeypatch.chdir(proj)
        # 隔离内置 bundle，使候选数可精确断言
        monkeypatch.setattr(
            "electromind.skills.builtin._candidate_builtin_bases",
            lambda: [],
        )

        from app.commands import skills as skills_cmd

        out = _run_capture(skills_cmd.run, ["reload"])
        assert "generation: 1" in out
        assert "candidates: 1" in out

    def test_paths(self, tmp_path, monkeypatch):
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_skill(proj / ".agents" / "skills", "cp2k", "d", "body\n")
        monkeypatch.chdir(proj)

        from app.commands import skills as skills_cmd

        out = _run_capture(skills_cmd.run, ["paths"])
        assert "project/agents" in out
        assert str(proj.resolve()) in out

    def test_doctor_reports_untrusted(self, tmp_path, monkeypatch, capsys):
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_skill(proj / ".agents" / "skills", "cp2k", "d", "body\n")
        monkeypatch.chdir(proj)

        from app.commands import skills as skills_cmd
        from app.exitcodes import EXIT_CLI

        def untrusted(_root):
            return False

        # doctor uses default service → project untrusted under fake HOME
        from electromind.skills.catalog_service import reset_shared_catalog_service

        reset_shared_catalog_service()
        code = skills_cmd.run(["doctor"])
        assert code == EXIT_CLI  # untrusted project skills are flagged


def _run_capture(fn, argv: list[str]) -> str:
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(argv)
    return buf.getvalue()


class TestTrustRefresh:
    """FIX-8: Workspace Trust 变化（文件不变）也触发 reload。"""

    def test_trust_flip_refreshes_candidates(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_skill(proj / ".agents" / "skills", "s", "v1", "body\n")

        trust_store = {"trusted": set()}

        def evaluator(project_root):
            return str(project_root) in trust_store["trusted"]

        service = SkillCatalogService(
            project_path=str(proj),
            cwd=str(proj),
            builtin_roots=(),
            is_project_trusted=evaluator,
        )
        c1 = service.list()
        assert c1.generation == 1
        assert all(c.trust_state == "untrusted" for c in c1.candidates)

        # Files unchanged — but the user trusts the workspace now
        trust_store["trusted"].add(str(proj.resolve()))
        c2 = service.reload()
        assert c2.generation == 2  # trust flip bumps the generation
        assert all(c.trust_state == "trusted" for c in c2.candidates)

        # No further change → same generation
        c3 = service.reload()
        assert c3.generation == 2

    def test_trust_revoke_refreshes_candidates(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_skill(proj / ".agents" / "skills", "s", "v1", "body\n")

        trusted = {str(proj.resolve())}

        def evaluator(project_root):
            return str(project_root) in trusted

        service = SkillCatalogService(
            project_path=str(proj),
            cwd=str(proj),
            builtin_roots=(),
            is_project_trusted=evaluator,
        )
        c1 = service.list()
        assert all(c.trust_state == "trusted" for c in c1.candidates)

        # Revoke trust — files unchanged
        trusted.clear()
        c2 = service.reload()
        assert c2.generation == 2
        assert all(c.trust_state == "untrusted" for c in c2.candidates)


class TestServiceOverrides:
    """FIX-9: [skills.overrides] state 进入服务主链。"""

    def test_override_state_applied_in_service(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_skill(proj / ".agents" / "skills", "cp2k", "d", "body\n")
        skill_id = f"project:{proj.name}:agents:cp2k"

        service = SkillCatalogService(
            project_path=str(proj),
            cwd=str(proj),
            builtin_roots=(),
            overrides={skill_id: {"state": "manual_only"}},
        )
        catalog = service.list()
        cand = catalog.by_qualified_id()[skill_id]
        assert cand.enabled_state == "manual_only"

    def test_override_off_excludes_from_model_catalog(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_skill(proj / ".agents" / "skills", "cp2k", "d", "body\n")
        skill_id = f"project:{proj.name}:agents:cp2k"

        service = SkillCatalogService(
            project_path=str(proj),
            cwd=str(proj),
            builtin_roots=(),
            overrides={skill_id: {"state": "off"}},
        )
        catalog = service.list()
        cand = catalog.by_qualified_id()[skill_id]
        assert cand.enabled_state == "off"

        from electromind.skills.catalog import build_model_catalog

        budget = build_model_catalog(catalog)
        assert budget.entries == ()


class TestChangedIncludesTrust:
    """P1: changed() 也要感知 Trust-only 变化（watcher 依赖它）。"""

    def test_changed_true_on_trust_flip(self, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        _write_skill(proj / ".agents" / "skills", "s", "v1", "body\n")

        trusted = set()

        def evaluator(project_root):
            return str(project_root) in trusted

        service = SkillCatalogService(
            project_path=str(proj),
            cwd=str(proj),
            builtin_roots=(),
            is_project_trusted=evaluator,
        )
        service.list()
        assert service.changed() is False

        # Files unchanged, trust flips → changed() must report True
        trusted.add(str(proj.resolve()))
        assert service.changed() is True


class TestResolutionPinPropagation:
    """P1: CatalogService 的 resolution pin 自动传给 ActivationService。"""

    def test_pin_survives_service_to_activation(self, tmp_path):
        import asyncio

        from electromind.skills.activation import (
            ActivationRequest,
            SkillActivationService,
        )
        from electromind.skills.snapstore import PrivateSnapshotStore

        proj = tmp_path / "proj"
        proj.mkdir()
        # 同名两个候选：project 与 user 不同 source
        d1 = proj / ".agents" / "skills" / "cp2k"
        d1.mkdir(parents=True)
        (d1 / "SKILL.md").write_text(
            "---\nname: cp2k\ndescription: proj\n---\nproj body\n",
            encoding="utf-8",
        )
        user_skills = tmp_path / "home" / ".agents" / "skills"
        d2 = user_skills / "cp2k"
        d2.mkdir(parents=True)
        (d2 / "SKILL.md").write_text(
            "---\nname: cp2k\ndescription: user\n---\nuser body\n",
            encoding="utf-8",
        )
        user_id = "user:agents:cp2k"
        service = SkillCatalogService(
            project_path=str(proj),
            cwd=str(proj),
            user_home=tmp_path / "home",
            builtin_roots=(),
            resolution={"cp2k": user_id},
        )
        catalog = service.list()
        assert catalog.resolution == {"cp2k": user_id}

        # 不手工传 resolution —— 从冻结 catalog 自动继承
        svc = SkillActivationService(
            catalog,
            store=PrivateSnapshotStore(tmp_path / "snapshots"),
            items_dir=tmp_path / "items",
        )
        assert svc.resolution == {"cp2k": user_id}
        result = asyncio.run(
            svc.activate(
                ActivationRequest(
                    request_id="r1",
                    thread_id="t",
                    run_id="run",
                    skill_id=user_id,
                )
            )
        )
        assert result.payload["skill_id"] == user_id

        # name 解析也用 pin（同名候选不再是歧义）
        from electromind.skills.activation import _resolve_invocation_skill_id

        resolved = _resolve_invocation_skill_id(svc, "cp2k")
        assert resolved == user_id


class TestCliUsesSharedService:
    """P1: CLI 必须使用进程级共享 CatalogService（RFC 第 14 项）。"""

    def test_cli_uses_process_wide_service(self, tmp_path, monkeypatch):
        from app.commands import skills as skills_cmd
        from electromind.skills.catalog_service import (
            reset_shared_catalog_service,
            set_shared_catalog_service,
        )

        reset_shared_catalog_service()
        # 注入一个可识别的哨兵 service
        sentinel = SkillCatalogService(
            project_path=str(tmp_path), cwd=str(tmp_path), builtin_roots=()
        )
        set_shared_catalog_service(sentinel)
        try:
            monkeypatch.chdir(tmp_path)
            service = skills_cmd._catalog_service()
            assert service is sentinel  # 返回同一个进程级实例
        finally:
            reset_shared_catalog_service()

    def test_cli_service_reconfigured_for_new_cwd(self, tmp_path, monkeypatch):
        from app.commands import skills as skills_cmd
        from electromind.skills.catalog_service import (
            reset_shared_catalog_service,
            set_shared_catalog_service,
        )

        reset_shared_catalog_service()
        set_shared_catalog_service(
            SkillCatalogService(project_path="/old", cwd="/old", builtin_roots=())
        )
        try:
            monkeypatch.chdir(tmp_path)
            service = skills_cmd._catalog_service()
            assert service.cwd == Path(tmp_path).resolve()
            assert service is not None
        finally:
            reset_shared_catalog_service()
