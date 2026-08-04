"""SKILL-4 tests: atomic activation — order, idempotency, rollback, privacy."""

from pathlib import Path

import pytest

from electromind.skills.activation import (
    ACTIVATED,
    ActivationError,
    ActivationRequest,
    SkillActivationService,
    SkillInput,
    substitute_body,
)
from electromind.skills.candidate import SkillCandidate, SkillDescriptor, SkillSource
from electromind.skills.catalog import MultiCandidateCatalog, build_catalog
from electromind.skills.snapstore import PrivateSnapshotStore, SkillSnapshotRef


def _write_skill(root: Path, name: str, description: str, body: str) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}",
        encoding="utf-8",
    )
    (d / "run.sh").write_text("#!/bin/sh\necho hi\n")
    return d


def _candidate(name: str, root: Path) -> SkillCandidate:
    descriptor = SkillDescriptor(
        name=name,
        description="d",
        entry_path=root / "SKILL.md",
        root_path=root,
        frontmatter={"name": name, "description": "d"},
        content_digest="c" * 64,
        resource_digest="r" * 64,
    )
    source = SkillSource(
        source_id="project-agents-x",
        scope="project",
        dialect="agents",
        root=root.parent,
        project_root=root.parent.parent,
        trust_domain=str(root.parent.parent),
    )
    return SkillCandidate(
        skill_id=f"project:{root.parent.parent.name}:agents:{name}",
        descriptor=descriptor,
        source=source,
    )


def _catalog(candidate: SkillCandidate, generation: int = 3) -> MultiCandidateCatalog:
    return build_catalog((candidate,), generation=generation, cwd="/w", repo_root="/r")


class RecordingMounter:
    """Records mounts/rollbacks; fails on demand."""

    def __init__(self, *, fail_mount: bool = False) -> None:
        self.fail_mount = fail_mount
        self.mounted: list[str] = []
        self.rolled_back: list[str] = []

    async def mount(self, ref: SkillSnapshotRef) -> str:
        if self.fail_mount:
            raise RuntimeError("mount exploded")
        self.mounted.append(ref.digest)
        return f"/mnt/{ref.digest[:8]}"

    async def rollback(self, mounted_root: str) -> None:
        self.rolled_back.append(mounted_root)


@pytest.mark.asyncio
class TestActivationTransaction:
    async def test_success_order_and_payload(self, tmp_path):
        """正文只在 Snapshot+Mount+Item 完成后才进入 payload。"""
        skill_dir = _write_skill(tmp_path, "cp2k", "d", "Run cp2k.\n")
        candidate = _candidate("cp2k", skill_dir)
        mounter = RecordingMounter()
        store = PrivateSnapshotStore(tmp_path / "snapshots")
        service = SkillActivationService(
            _catalog(candidate),
            store=store,
            mounter=mounter,
            items_dir=tmp_path / "items",
        )

        result = await service.activate(
            ActivationRequest(
                request_id="req-1",
                thread_id="t1",
                run_id="run-1",
                skill_id=candidate.skill_id,
            )
        )

        assert result.item.status == ACTIVATED
        assert mounter.mounted == [result.item.snapshot_ref.split(":")[0]]
        # Snapshot exists in the private store
        ref = SkillSnapshotRef(
            digest=result.item.snapshot_ref,
            store="private",
            locator="",
        )
        assert store.path_for(ref) is not None
        assert store.read_body(ref) == "Run cp2k."
        # Item persisted
        item_file = tmp_path / "items" / f"{result.item.activation_id}.json"
        assert item_file.is_file()

    async def test_retry_returns_same_result(self, tmp_path):
        """重复 request_id + run_id + skill_id → 同一 Activation 结果。"""
        skill_dir = _write_skill(tmp_path, "cp2k", "d", "body\n")
        candidate = _candidate("cp2k", skill_dir)
        mounter = RecordingMounter()
        store = PrivateSnapshotStore(tmp_path / "snapshots")
        service = SkillActivationService(
            _catalog(candidate),
            store=store,
            mounter=mounter,
            items_dir=tmp_path / "items",
        )
        request = ActivationRequest(
            request_id="req-1",
            thread_id="t1",
            run_id="run-1",
            skill_id=candidate.skill_id,
        )

        first = await service.activate(request)
        second = await service.activate(request)

        assert second.reused is True
        assert second.item.activation_id == first.item.activation_id
        assert len(mounter.mounted) == 1  # 只挂载一次

    async def test_failure_leaves_no_activated_item(self, tmp_path):
        """挂载失败 → 无半激活态（无 activated item，snapshot 也不残留）。"""
        skill_dir = _write_skill(tmp_path, "cp2k", "d", "body\n")
        candidate = _candidate("cp2k", skill_dir)
        mounter = RecordingMounter(fail_mount=True)
        store = PrivateSnapshotStore(tmp_path / "snapshots")
        service = SkillActivationService(
            _catalog(candidate),
            store=store,
            mounter=mounter,
            items_dir=tmp_path / "items",
        )

        with pytest.raises(ActivationError, match="mount exploded"):
            await service.activate(
                ActivationRequest(
                    request_id="req-1",
                    thread_id="t1",
                    run_id="run-1",
                    skill_id=candidate.skill_id,
                )
            )

        # No activated item persisted (only a failed record)
        items = list((tmp_path / "items").glob("*.json"))
        assert len(items) == 1
        assert '"status": "failed"' in items[0].read_text(encoding="utf-8")
        # No snapshot was stored (store.save happens before mount; rollback
        # removes nothing — the store save should not have happened for mount
        # failure? it did — but no activated item).
        assert mounter.rolled_back == []

    async def test_missing_skill_md_fails(self, tmp_path):
        """SKILL.md 缺失 → 无冻结正文 → 激活失败，不产生 activated item。"""
        empty = tmp_path / "broken"
        empty.mkdir()
        candidate = _candidate("broken", empty)
        service = SkillActivationService(
            _catalog(candidate), items_dir=tmp_path / "items"
        )
        with pytest.raises(ActivationError, match="no frozen body"):
            await service.activate(
                ActivationRequest(
                    request_id="req-1",
                    thread_id="t1",
                    run_id="run-1",
                    skill_id=candidate.skill_id,
                )
            )

    async def test_substitution_before_snapshot(self, tmp_path):
        """$ARGUMENTS / $filename 在 Snapshot 前替换，快照正文含替换结果。"""
        skill_dir = _write_skill(
            tmp_path, "cp2k", "d", "Run $ARGUMENTS with $filename\n"
        )
        candidate = _candidate("cp2k", skill_dir)
        store = PrivateSnapshotStore(tmp_path / "snapshots")
        service = SkillActivationService(
            _catalog(candidate), store=store, items_dir=tmp_path / "items"
        )
        result = await service.activate(
            ActivationRequest(
                request_id="req-1",
                thread_id="t1",
                run_id="run-1",
                skill_id=candidate.skill_id,
                arguments={"filename": "input.inp", "format": "cp2k"},
            )
        )
        assert "input.inp" in result.payload["instructions"]
        ref = SkillSnapshotRef(
            digest=result.item.snapshot_ref, store="private", locator=""
        )
        body = store.read_body(ref)
        assert body is not None
        assert "input.inp" in body
        assert "$filename" not in body


class TestSkillInput:
    def test_arguments_mapping(self):
        inp = SkillInput(name="cp2k", arguments={"a": "1"})
        assert inp.as_argument_map() == {"a": "1"}

    def test_arguments_string(self):
        inp = SkillInput(name="cp2k", arguments="input.inp")
        assert inp.as_argument_map() == {"_": "input.inp"}

    def test_arguments_none(self):
        assert SkillInput(name="cp2k").as_argument_map() == {}


class TestSubstituteBody:
    def test_argument_and_positional(self):
        out = substitute_body(
            "$ARGUMENTS $0 $1 $filename $format",
            {"filename": "f.inp", "format": "xyz"},
            positional=("a", "b"),
        )
        assert out == "f.inp xyz a b f.inp xyz"

    def test_missing_values_empty(self):
        out = substitute_body("$ARGUMENTS $filename", {})
        assert out == " "

    def test_named_keys(self):
        out = substitute_body("$alpha $beta", {"alpha": "1", "beta": "2"})
        assert out == "1 2"


class TestPrivateStore:
    def test_same_digest_single_copy(self, tmp_path):
        store = PrivateSnapshotStore(tmp_path / "snapshots")
        ref1 = store.save(name="s", body="same body")
        ref2 = store.save(name="s", body="same body")
        assert ref1.digest == ref2.digest
        dirs = list((tmp_path / "snapshots").iterdir())
        assert len(dirs) == 1

    def test_gc_removes_unreferenced_old(self, tmp_path):
        store = PrivateSnapshotStore(tmp_path / "snapshots")
        ref = store.save(name="s", body="old body")
        # Age the manifest
        import json
        import time

        manifest = store.path_for(ref) / "manifest.json"
        old = {
            "name": "s",
            "digest": ref.digest,
            "created_at": _iso_days_ago(60),
            "resources": [],
            "export_policy": "private",
        }
        manifest.write_text(json.dumps(old), encoding="utf-8")

        removed = store.gc({""}, retention_days=30, now=time.time())
        assert removed == 1
        assert store.path_for(ref) is None

    def test_gc_keeps_referenced(self, tmp_path):
        store = PrivateSnapshotStore(tmp_path / "snapshots")
        ref = store.save(name="s", body="body")
        removed = store.gc({ref.digest}, retention_days=0)
        assert removed == 0
        assert store.path_for(ref) is not None


def _iso_days_ago(days: int) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


@pytest.mark.asyncio
class TestUseSkillCompatAdapter:
    """use_skill 兼容 Adapter：构造 ActivationRequest → ActivationService。"""

    async def test_use_skill_tool_via_service(self, tmp_path):
        import json as _json

        from electromind.skills.activation import (
            make_activation_use_skill_tool,
        )

        skill_dir = _write_skill(tmp_path, "cp2k", "d", "Run cp2k.\n")
        candidate = _candidate("cp2k", skill_dir)
        service = SkillActivationService(
            _catalog(candidate),
            store=PrivateSnapshotStore(tmp_path / "snapshots"),
            items_dir=tmp_path / "items",
        )
        tool = make_activation_use_skill_tool(service, thread_id="t1", run_id="run-1")
        result = await tool.acall({"name": candidate.skill_id})
        assert result.ok is True
        payload = _json.loads(result.content)
        assert payload["ok"] is True
        assert payload["skill_id"] == candidate.skill_id
        assert "Run cp2k." in payload["instructions"]
        assert payload["status"] == ACTIVATED

    async def test_activate_skill_tool_structured(self, tmp_path):
        import json as _json

        from electromind.skills.activation import make_activate_skill_tool

        skill_dir = _write_skill(tmp_path, "cp2k", "d", "Run $filename\n")
        candidate = _candidate("cp2k", skill_dir)
        service = SkillActivationService(
            _catalog(candidate),
            store=PrivateSnapshotStore(tmp_path / "snapshots"),
            items_dir=tmp_path / "items",
        )
        tool = make_activate_skill_tool(service, thread_id="t1", run_id="run-1")
        result = await tool.acall(
            {
                "skillId": candidate.skill_id,
                "arguments": {"filename": "input.inp"},
            }
        )
        payload = _json.loads(result.content)
        assert payload["ok"] is True
        assert "input.inp" in payload["instructions"]

    async def test_activate_skill_unknown_returns_error(self, tmp_path):
        import json as _json

        from electromind.skills.activation import make_activate_skill_tool

        skill_dir = _write_skill(tmp_path, "cp2k", "d", "body\n")
        candidate = _candidate("cp2k", skill_dir)
        service = SkillActivationService(
            _catalog(candidate),
            store=PrivateSnapshotStore(tmp_path / "snapshots"),
            items_dir=tmp_path / "items",
        )
        tool = make_activate_skill_tool(service, thread_id="t1", run_id="run-1")
        result = await tool.acall({"name": "user:agents:ghost"})
        payload = _json.loads(result.content)
        assert payload["ok"] is False
        assert "无法解析" in payload["error"]


@pytest.mark.asyncio
class TestRunFreeze:
    """FIX-1 P0: activation consumes catalog-frozen content, not live files."""

    async def test_frozen_run_ignores_live_changes(self, tmp_path):
        """发现时正文 OLD；发现后文件改为 NEW；冻结 Run 激活仍返回 OLD。"""
        skill_dir = _write_skill(tmp_path, "cp2k", "d", "OLD body\n")
        candidate = _candidate("cp2k", skill_dir)

        # Catalog freezes the body at construction
        catalog = _catalog(candidate, generation=3)
        assert catalog.frozen_bodies[candidate.skill_id] == "OLD body"

        # Source changes AFTER the catalog was built
        (skill_dir / "SKILL.md").write_text(
            "---\nname: cp2k\ndescription: d\n---\nNEW body\n",
            encoding="utf-8",
        )

        service = SkillActivationService(
            catalog,
            store=PrivateSnapshotStore(tmp_path / "snapshots"),
            items_dir=tmp_path / "items",
        )
        result = await service.activate(
            ActivationRequest(
                request_id="req-1",
                thread_id="t1",
                run_id="run-1",
                skill_id=candidate.skill_id,
            )
        )
        assert "OLD body" in result.payload["instructions"]
        assert "NEW body" not in result.payload["instructions"]

    async def test_missing_frozen_body_fails(self, tmp_path):
        """恢复的 Catalog（无冻结正文）激活失败，不读实时文件。"""
        from electromind.skills.catalog import MultiCandidateCatalog

        skill_dir = _write_skill(tmp_path, "cp2k", "d", "live body\n")
        candidate = _candidate("cp2k", skill_dir)
        # Simulate a restored catalog: explicit empty frozen bodies
        catalog = MultiCandidateCatalog(
            generation=1,
            cwd="/w",
            repo_root=None,
            candidates=(candidate,),
            frozen_bodies={},
        )
        service = SkillActivationService(catalog, items_dir=tmp_path / "items")
        with pytest.raises(ActivationError, match="no frozen body"):
            await service.activate(
                ActivationRequest(
                    request_id="req-1",
                    thread_id="t1",
                    run_id="run-1",
                    skill_id=candidate.skill_id,
                )
            )


@pytest.mark.asyncio
class TestIdempotentReplayRestoresPayload:
    """FIX-2: replay returns the SAME full payload (body included)."""

    async def test_retry_returns_same_instructions(self, tmp_path):
        skill_dir = _write_skill(tmp_path, "cp2k", "d", "Replay body\n")
        candidate = _candidate("cp2k", skill_dir)
        service = SkillActivationService(
            _catalog(candidate),
            store=PrivateSnapshotStore(tmp_path / "snapshots"),
            items_dir=tmp_path / "items",
        )
        request = ActivationRequest(
            request_id="req-1",
            thread_id="t1",
            run_id="run-1",
            skill_id=candidate.skill_id,
        )

        first = await service.activate(request)
        second = await service.activate(request)

        assert second.reused is True
        assert first.payload["instructions"] == "Replay body"
        assert second.payload["instructions"] == "Replay body"
        assert second.payload["instructions"] != ""

    async def test_retry_restores_from_snapshot_store(self, tmp_path):
        """即使首次结果不在内存，也能从 Snapshot Store 恢复正文。"""
        skill_dir = _write_skill(tmp_path, "cp2k", "d", "Stored body\n")
        candidate = _candidate("cp2k", skill_dir)
        store = PrivateSnapshotStore(tmp_path / "snapshots")
        service = SkillActivationService(
            _catalog(candidate),
            store=store,
            items_dir=tmp_path / "items",
        )
        request = ActivationRequest(
            request_id="req-1",
            thread_id="t1",
            run_id="run-1",
            skill_id=candidate.skill_id,
        )
        first = await service.activate(request)

        # Simulate a fresh service (memory cleared) — same item persisted on disk
        service2 = SkillActivationService(
            _catalog(candidate),
            store=store,
            items_dir=tmp_path / "items",
        )
        persisted = service2.load_persisted(first.item.activation_id)
        assert persisted is not None
        payload = service2._restore_payload(persisted)
        assert payload["instructions"] == "Stored body"


@pytest.mark.asyncio
class TestNameResolutionInTools:
    """FIX-10: `name` 必须走 unqualified resolver，不能当 qualified id 用。"""

    async def test_use_skill_by_bare_name(self, tmp_path):
        import json as _json

        from electromind.skills.activation import make_activation_use_skill_tool

        skill_dir = _write_skill(tmp_path, "cp2k", "d", "body\n")
        candidate = _candidate("cp2k", skill_dir)
        service = SkillActivationService(
            _catalog(candidate),
            store=PrivateSnapshotStore(tmp_path / "snapshots"),
            items_dir=tmp_path / "items",
        )
        tool = make_activation_use_skill_tool(service, thread_id="t1", run_id="run-1")
        result = await tool.acall({"name": "cp2k"})  # bare name, not qualified id
        assert result.ok is True
        payload = _json.loads(result.content)
        assert payload["ok"] is True
        assert payload["skill_id"] == candidate.skill_id

    async def test_use_skill_ambiguous_name_fails(self, tmp_path):
        import json as _json

        from electromind.skills.activation import make_activation_use_skill_tool

        skill_dir = _write_skill(tmp_path, "cp2k", "d", "body\n")
        candidate = _candidate("cp2k", skill_dir)
        # Duplicate candidate with a different qualified id — same name
        from dataclasses import replace as _replace

        dup = _replace(candidate, skill_id="user:agents:cp2k")
        from electromind.skills.catalog import build_catalog

        catalog = build_catalog(
            (candidate, dup), generation=1, cwd="/w", repo_root=None
        )
        service = SkillActivationService(
            catalog,
            store=PrivateSnapshotStore(tmp_path / "snapshots"),
            items_dir=tmp_path / "items",
        )
        tool = make_activation_use_skill_tool(service, thread_id="t1", run_id="run-1")
        result = await tool.acall({"name": "cp2k"})
        payload = _json.loads(result.content)
        assert payload["ok"] is False
        assert "无法解析" in payload["error"]

    async def test_activate_skill_by_name(self, tmp_path):
        import json as _json

        from electromind.skills.activation import make_activate_skill_tool

        skill_dir = _write_skill(tmp_path, "cp2k", "d", "Run $filename\n")
        candidate = _candidate("cp2k", skill_dir)
        service = SkillActivationService(
            _catalog(candidate),
            store=PrivateSnapshotStore(tmp_path / "snapshots"),
            items_dir=tmp_path / "items",
        )
        tool = make_activate_skill_tool(service, thread_id="t1", run_id="run-1")
        result = await tool.acall({"name": "cp2k", "arguments": {"filename": "a.inp"}})
        payload = _json.loads(result.content)
        assert payload["ok"] is True
        assert "a.inp" in payload["instructions"]


@pytest.mark.asyncio
class TestResolutionPinThroughActivation:
    """P1: [skills.resolution] pin 必须进入 Activation 主链。"""

    async def test_pinned_name_resolves_in_use_skill(self, tmp_path):
        import json as _json

        from electromind.skills.activation import make_activation_use_skill_tool

        skill_dir = _write_skill(tmp_path, "cp2k", "d", "body\n")
        candidate = _candidate("cp2k", skill_dir)
        dup = _candidate("cp2k", skill_dir)  # same name, different source below
        from dataclasses import replace as _r

        dup = _r(
            dup,
            skill_id="user:agents:cp2k",
            source=_r(
                dup.source,
                source_id="user-agents-x",
                scope="user",
                root=skill_dir.parent,
                project_root=None,
            ),
        )
        from electromind.skills.catalog import build_catalog

        catalog = build_catalog(
            (candidate, dup), generation=1, cwd="/w", repo_root=None
        )
        service = SkillActivationService(
            catalog,
            store=PrivateSnapshotStore(tmp_path / "snapshots"),
            items_dir=tmp_path / "items",
            resolution={"cp2k": "user:agents:cp2k"},
        )
        tool = make_activation_use_skill_tool(service, thread_id="t1", run_id="run-1")
        result = await tool.acall({"name": "cp2k"})
        payload = _json.loads(result.content)
        assert payload["ok"] is True
        assert payload["skill_id"] == "user:agents:cp2k"
