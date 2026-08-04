"""RFC 第十六节 最终完成标准 — 机器可检查的 16 项验收清单。

每项对应 RFC spec `docs/superpowers/specs/2026-08-03-skill-runtime-phase2-rfc.md`
第十六节的表格。运行：`pytest tests/test_skill_acceptance.py -v`。
"""

from dataclasses import replace
from pathlib import Path

import pytest

from electromind.skills.activation import (
    ActivationRequest,
    SkillActivationService,
    make_activate_skill_tool,
    make_activation_use_skill_tool,
)
from electromind.skills.candidate import SkillCandidate, SkillDescriptor, SkillSource
from electromind.skills.catalog import (
    MultiCandidateCatalog,
    SkillResolutionAmbiguous,
    SkillResolver,
    build_catalog,
    save_catalog_snapshot,
)
from electromind.skills.catalog_service import SkillCatalogService
from electromind.skills.scopes import (
    discover_candidate_sources,
    load_candidates,
    model_visible_candidates,
)
from electromind.skills.snapstore import PrivateSnapshotStore, SkillSnapshotRef

REPO_ROOT = Path(__file__).resolve().parent.parent


def _candidate(
    name: str,
    *,
    scope: str = "project",
    dialect: str = "agents",
    project_dir: str = "repo",
    enabled: str = "on",
    trust: str = "trusted",
) -> SkillCandidate:
    source = SkillSource(
        source_id=f"{scope}-{dialect}-{name}",
        scope=scope,  # type: ignore[arg-type]
        dialect=dialect,  # type: ignore[arg-type]
        root=Path(f"/{scope}/{project_dir}/{dialect}/{name}"),
        project_root=Path(f"/{scope}/{project_dir}") if scope == "project" else None,
        trust_domain=str(Path(f"/{scope}/{project_dir}")),
    )
    from electromind.skills.candidate import make_skill_id

    descriptor = SkillDescriptor(
        name=name,
        description="d",
        entry_path=source.root / "SKILL.md",
        root_path=source.root,
        frontmatter={"name": name, "description": "d"},
        content_digest=f"c{name}",
        resource_digest=f"r{name}",
    )
    return SkillCandidate(
        skill_id=make_skill_id(
            scope=scope,
            name=name,
            dialect=dialect,
            project_dir=project_dir if scope == "project" else None,
        ),
        descriptor=descriptor,
        source=source,
        enabled_state=enabled,  # type: ignore[arg-type]
        trust_state=trust,  # type: ignore[arg-type]
    )


def _catalog(*candidates: SkillCandidate) -> MultiCandidateCatalog:
    return build_catalog(candidates, generation=1, cwd="/w", repo_root="/r")


# 1. 现有 Skill 功能和 91 个测试无回归
def test_01_skill_special_tests_pass():
    """真正执行 skill 专项测试文件，验证全部通过（非仅 collect-only）。"""
    import subprocess
    import sys

    skill_files = (
        "test_electromind_skills.py",
        "test_skills_snapshot.py",
        "test_project_skill_autodiscovery.py",
        "test_skill_candidates.py",
        "test_skill_scopes.py",
        "test_skill_catalog.py",
        "test_skill_activation.py",
        "test_skill_lazy_mount.py",
        "test_skill_catalog_service.py",
        "test_skill_watcher.py",
        "test_skill_builtin.py",
    )
    for f in skill_files:
        assert (REPO_ROOT / "tests" / f).is_file(), f
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            *(f"tests/{f}" for f in skill_files),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=300,
    )
    assert r.returncode == 0, "skill 专项测试未全绿:\n" + (r.stdout + r.stderr)[-2000:]


# 2. Discovery 返回全部 Candidate，不丢弃同名版本
def test_02_same_name_candidates_all_retained(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    # A+ W3/W5: 同名候选通过不同来源保留（每个目录名 == frontmatter name）；
    # 同一来源内同名目录在 W3 下是 invalid skill。
    for dialect_dir, desc in ((".agents", "one"), (".electromind", "two")):
        d = proj / dialect_dir / "skills" / "same"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f"---\nname: same\ndescription: {desc}\n---\nb\n", encoding="utf-8"
        )
    candidates = load_candidates(
        discover_candidate_sources(str(proj), cwd=str(proj), builtin_roots=())
    )
    same = [c for c in candidates if c.descriptor.name == "same"]
    assert len(same) == 2
    assert len({c.skill_id for c in same}) == 2  # qualified ids unique


# 3. Scope、Dialect、Trust、State 分离建模
def test_03_separate_model_fields():
    import dataclasses

    cand_fields = {f.name for f in dataclasses.fields(SkillCandidate)}
    assert {"enabled_state", "trust_state"}.issubset(cand_fields)
    src_fields = {f.name for f in dataclasses.fields(SkillSource)}
    assert {"scope", "dialect", "trust_domain"}.issubset(src_fields)


# 4. Catalog Generation 按 Run 冻结（激活不读实时文件）
@pytest.mark.asyncio
async def test_04_run_freeze_ignores_live_changes(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: cp2k\ndescription: d\n---\nOLD\n", encoding="utf-8"
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
        skill_id="project:tmp:agents:cp2k",
        descriptor=SkillDescriptor(
            name="cp2k",
            description="d",
            entry_path=d / "SKILL.md",
            root_path=d,
            frontmatter={"name": "cp2k"},
            content_digest="c" * 64,
            resource_digest="r" * 64,
        ),
        source=source,
    )
    catalog = build_catalog((cand,), generation=1, cwd="/w", repo_root=None)
    (d / "SKILL.md").write_text(
        "---\nname: cp2k\ndescription: d\n---\nNEW\n", encoding="utf-8"
    )
    svc = SkillActivationService(
        catalog,
        store=PrivateSnapshotStore(tmp_path / "snap"),
        items_dir=tmp_path / "items",
    )
    result = await svc.activate(
        ActivationRequest("r1", "t", "run", "project:tmp:agents:cp2k")
    )
    assert "OLD" in result.payload["instructions"]
    assert "NEW" not in result.payload["instructions"]


# 5. Qualified ID 可以唯一定位 Skill
def test_05_qualified_id_exact():
    a = _candidate("cp2k", scope="user", dialect="agents")
    b = _candidate("cp2k", scope="project", project_dir="repo")
    catalog = _catalog(a, b)
    idx = catalog.by_qualified_id()
    assert idx["user:agents:cp2k"] is a
    assert idx["project:repo:agents:cp2k"] is b


# 6. 显式、隐式和 Picker 使用不同解析策略
def test_06_three_resolver_policies():
    a = _candidate("cp2k", scope="user", dialect="agents")
    # 同 scope 同 dialect、不同来源 → 同 rank 真正歧义
    b = replace(a, skill_id="user:agents:cp2k-alt")
    catalog = _catalog(a, b)
    resolver = SkillResolver(catalog)
    # 显式：歧义 → Ambiguous（Picker）
    with pytest.raises(SkillResolutionAmbiguous):
        resolver.resolve_unqualified("cp2k", interactive=True)
    # 隐式：同层歧义 → 不激活
    result = resolver.resolve_implicit("cp2k")
    assert isinstance(result, SkillResolutionAmbiguous)
    # Picker：全部候选
    assert len(resolver.picker_candidates()) == 2


# 7. 未信任项目 Skill 不进入模型上下文
def test_07_untrusted_excluded_from_model():
    a = _candidate("cp2k", trust="untrusted")
    catalog = _catalog(a)
    result = SkillResolver(catalog).resolve_implicit("cp2k")
    assert isinstance(result, SkillResolutionAmbiguous)
    assert result.candidates == ()
    assert model_visible_candidates(catalog.candidates) == ()


# 8. Trust 复用现有 Workspace Trust + 翻转刷新 + 不建新库
def test_08_trust_reuse_and_refresh(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    d = proj / ".agents" / "skills" / "s"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: s\ndescription: d\n---\nb\n", encoding="utf-8"
    )
    trusted = set()
    svc = SkillCatalogService(
        project_path=str(proj),
        cwd=str(proj),
        builtin_roots=(),
        is_project_trusted=lambda pr: str(pr) in trusted,
    )
    c1 = svc.list()
    assert all(c.trust_state == "untrusted" for c in c1.candidates)
    trusted.add(str(proj.resolve()))
    # 文件不变：reload() 与 changed() 都必须感知 Trust-only 变化
    assert svc.changed() is True
    c2 = svc.reload()  # 文件不变，trust 翻转
    assert c2.generation == 2
    assert all(c.trust_state == "trusted" for c in c2.candidates)
    assert svc.changed() is False  # 提交后不再报告变化
    assert not (tmp_path / "trusted.json").exists()  # 不建新库


# 9. Activation 是可回滚的原子事务
@pytest.mark.asyncio
async def test_09_atomic_activation_rollback(tmp_path):
    from electromind.skills.activation import ActivationError

    d = tmp_path / "s"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: cp2k\ndescription: d\n---\nb\n", encoding="utf-8"
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
        skill_id="project:tmp:agents:cp2k",
        descriptor=SkillDescriptor(
            name="cp2k",
            description="d",
            entry_path=d / "SKILL.md",
            root_path=d,
            frontmatter={"name": "cp2k"},
            content_digest="c" * 64,
            resource_digest="r" * 64,
        ),
        source=source,
    )
    catalog = build_catalog((cand,), generation=1, cwd="/w", repo_root=None)

    class BoomMounter:
        async def mount(self, ref):
            raise RuntimeError("boom")

        async def rollback(self, root):
            pass

    svc = SkillActivationService(
        catalog, mounter=BoomMounter(), items_dir=tmp_path / "items"
    )
    with pytest.raises(ActivationError, match="boom"):
        await svc.activate(
            ActivationRequest("r1", "t", "run", "project:tmp:agents:cp2k")
        )
    items = list((tmp_path / "items").glob("*.json"))
    assert len(items) == 1
    assert '"status": "failed"' in items[0].read_text(encoding="utf-8")


# 10. 正文在 Snapshot+Mount+Item 完成后才可见
@pytest.mark.asyncio
async def test_10_payload_only_after_transaction(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: cp2k\ndescription: d\n---\nbody\n", encoding="utf-8"
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
        skill_id="project:tmp:agents:cp2k",
        descriptor=SkillDescriptor(
            name="cp2k",
            description="d",
            entry_path=d / "SKILL.md",
            root_path=d,
            frontmatter={"name": "cp2k"},
            content_digest="c" * 64,
            resource_digest="r" * 64,
        ),
        source=source,
    )
    catalog = build_catalog((cand,), generation=1, cwd="/w", repo_root=None)
    store = PrivateSnapshotStore(tmp_path / "snap")
    svc = SkillActivationService(catalog, store=store, items_dir=tmp_path / "items")
    result = await svc.activate(
        ActivationRequest("r1", "t", "run", "project:tmp:agents:cp2k")
    )
    assert result.payload["instructions"] == "body"
    ref = SkillSnapshotRef(digest=result.item.snapshot_ref, store="private", locator="")
    assert store.path_for(ref) is not None  # snapshot 已落盘
    assert result.item.status == "activated"


# 11. 私有 Skill 正文不默认进入项目导出
def test_11_snapshots_never_persist_bodies(tmp_path):
    a = _candidate("cp2k")
    path = tmp_path / "catalog.json"
    save_catalog_snapshot(_catalog(a), path)
    raw = path.read_text(encoding="utf-8")
    assert "instructions" not in raw
    assert "body" not in raw.lower()
    ref = SkillSnapshotRef(
        digest="d" * 64, store="private", locator="", export_policy="private"
    )
    assert ref.export_policy == "private"


# 12. use_skill 兼容 + activate_skill + name 走 resolver
@pytest.mark.asyncio
async def test_12_use_skill_adapter_and_name_resolution(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: cp2k\ndescription: d\n---\nbody\n", encoding="utf-8"
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
        skill_id="project:tmp:agents:cp2k",
        descriptor=SkillDescriptor(
            name="cp2k",
            description="d",
            entry_path=d / "SKILL.md",
            root_path=d,
            frontmatter={"name": "cp2k"},
            content_digest="c" * 64,
            resource_digest="r" * 64,
        ),
        source=source,
    )
    catalog = build_catalog((cand,), generation=1, cwd="/w", repo_root=None)
    svc = SkillActivationService(
        catalog,
        store=PrivateSnapshotStore(tmp_path / "snap"),
        items_dir=tmp_path / "items",
    )
    import json as _json

    tool = make_activation_use_skill_tool(svc, thread_id="t", run_id="run")
    out = await tool.acall({"name": "cp2k"})  # bare name, not qualified id
    assert _json.loads(out.content)["ok"] is True
    tool2 = make_activate_skill_tool(svc, thread_id="t", run_id="run")
    out2 = await tool2.acall({"skillId": "project:tmp:agents:cp2k"})
    assert _json.loads(out2.content)["ok"] is True

    # resolution pin：同名候选 + pin → use_skill 解析到 pin 目标
    from dataclasses import replace as _r

    dup = _r(
        cand,
        skill_id="user:agents:cp2k",
        source=_r(
            cand.source,
            source_id="user-agents-x",
            scope="user",
            project_root=None,
        ),
    )
    pinned_catalog = build_catalog(
        (cand, dup),
        generation=1,
        cwd="/w",
        repo_root=None,
        resolution={"cp2k": "user:agents:cp2k"},
    )
    pinned_svc = SkillActivationService(
        pinned_catalog,
        store=PrivateSnapshotStore(tmp_path / "snap2"),
        items_dir=tmp_path / "items2",
    )
    # 未手工传 resolution —— 从冻结 catalog 自动继承
    assert pinned_svc.resolution == {"cp2k": "user:agents:cp2k"}
    tool3 = make_activation_use_skill_tool(pinned_svc, thread_id="t", run_id="run")
    out3 = await tool3.acall({"name": "cp2k"})
    assert _json.loads(out3.content)["skill_id"] == "user:agents:cp2k"


# 13. 只挂载被激活的 Skill（100 发现 1 激活）
@pytest.mark.asyncio
async def test_13_lazy_mount_one_of_many(tmp_path):
    from electromind import Sandbox
    from electromind.skills.mounting import LazySkillMounter

    proj = tmp_path / "proj"
    proj.mkdir()
    root = proj / ".agents" / "skills"
    root.mkdir(parents=True)
    for i in range(100):
        d = root / f"skill-{i:03d}"
        d.mkdir()
        (d / "SKILL.md").write_text(
            f"---\nname: skill-{i:03d}\ndescription: d\n---\nbody {i}\n",
            encoding="utf-8",
        )
    candidates = load_candidates(
        discover_candidate_sources(str(proj), cwd=str(proj), builtin_roots=())
    )
    assert len(candidates) == 100
    catalog = build_catalog(
        candidates, generation=1, cwd=str(proj), repo_root=str(proj)
    )
    target = next(c for c in candidates if c.descriptor.name == "skill-042")
    store = PrivateSnapshotStore(tmp_path / "snap")

    async with await Sandbox.create(
        backend="local", workdir=str(tmp_path / "box")
    ) as box:
        svc = SkillActivationService(
            catalog,
            store=store,
            mounter=LazySkillMounter(box, store=store),
            items_dir=tmp_path / "items",
        )
        result = await svc.activate(
            ActivationRequest("r1", "t", "run", target.skill_id)
        )
        assert result.item.mounted_root is not None
        skills_dir = Path(box.resolve("/home/agent/.skills"))
        dirs = [
            p for p in skills_dir.iterdir() if p.is_dir() and not p.name.startswith(".")
        ]
        assert len(dirs) == 1  # 环境只接收 1 个


# 14. CLI、Desktop 和 Service 使用同一 Catalog
def test_14_shared_catalog_service(tmp_path, monkeypatch):
    from app.commands import skills as skills_cmd
    from electromind.skills.catalog_service import (
        get_shared_catalog_service,
        reset_shared_catalog_service,
        set_shared_catalog_service,
    )

    reset_shared_catalog_service()
    # CLI 消费者必须返回进程级共享实例（注入哨兵 → 原样复用）
    sentinel = SkillCatalogService(
        project_path=str(tmp_path), cwd=str(tmp_path), builtin_roots=()
    )
    set_shared_catalog_service(sentinel)
    try:
        monkeypatch.chdir(tmp_path)
        assert skills_cmd._catalog_service() is sentinel
    finally:
        reset_shared_catalog_service()

    # 未配置的默认单例 → CLI 会配置 cwd + Trust evaluator 后复用同一实例
    reset_shared_catalog_service()
    monkeypatch.chdir(tmp_path)
    svc = skills_cmd._catalog_service()
    assert svc is get_shared_catalog_service()
    assert svc.cwd == Path(tmp_path).resolve()
    # 再次调用不再重建（同一实例）
    assert skills_cmd._catalog_service() is svc
    reset_shared_catalog_service()


# 15. 内置 Skill 在真实安装产物中可用（真实 wheel data 布局）
def test_15_builtin_roots_find_real_wheel_layout(tmp_path, monkeypatch):
    import subprocess
    import sys
    import zipfile

    from electromind.skills.builtin import builtin_roots

    # 构建真实 wheel，解包 .data/data 到假 venv 根（uv_build data 安装位）
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    build = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(wheel_dir)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if build.returncode != 0:
        pytest.skip(f"uv build unavailable: {build.stderr[:200]}")
    wheels = list(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1
    fake_prefix = tmp_path / "venv"
    with zipfile.ZipFile(wheels[0]) as zf:
        data_prefix = next(
            (n for n in zf.namelist() if n.endswith(".data/data/")), None
        )
        assert data_prefix is not None
        for name in zf.namelist():
            if name.startswith(data_prefix) and not name.endswith("/"):
                rel = name[len(data_prefix) :]
                dest = fake_prefix / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(name))

    monkeypatch.setattr(sys, "prefix", str(fake_prefix))
    roots = builtin_roots()
    # A+ W5: venv 根布局以扁平根形式被发现（procedures/ 与 tools/ 本身）
    assert (fake_prefix / "procedures").resolve() in roots
    assert (fake_prefix / "tools").resolve() in roots
    # A+ W6: 运行时 wheel 不含顶层 knowledge/
    assert not (fake_prefix / "knowledge").is_dir()
    candidates = load_candidates(
        discover_candidate_sources(None, cwd=str(fake_prefix), builtin_roots=roots)
    )
    names = {c.descriptor.name for c in candidates}
    assert "cp2k" in names  # 真实安装产物可发现内置 Skill


# 16. 安装器保持后置且不能由模型自主触发
def test_16_installer_user_invoked_not_model_triggerable():
    """SKILL-9: 安装器存在但只能由用户显式调用（模型不可触发）。"""
    from electromind.skills.installer import SkillInstaller

    # 安装器存在（CLI-only），核心 API 是 install_from_dir/archive/git
    assert hasattr(SkillInstaller, "install_from_dir")
    assert hasattr(SkillInstaller, "install_from_archive")
    assert hasattr(SkillInstaller, "install_from_git")

    # 模型工具命名空间绝不暴露安装能力：
    # - 无名为 install_skill / uninstall_skill 的工具
    # - activation 工具（use_skill / activate_skill）不携带安装参数
    import electromind.skills as skills_pkg

    for forbidden in ("install_skill", "uninstall_skill", "install_from_dir"):
        assert not hasattr(skills_pkg, forbidden), (
            f"{forbidden} 不得从 electromind.skills 顶层暴露给模型"
        )
    # 安装器模块本身不是工具模块（无 FunctionTool 构造）
    assert not hasattr(SkillInstaller, "func")


# 4b. Catalog snapshot round-trip 保留策略元数据且 digest 一致（P1 回归）
def test_04b_snapshot_round_trip_preserves_policy(tmp_path):
    from electromind.skills.catalog import (
        _catalog_digest,
        load_catalog_snapshot,
        save_catalog_snapshot,
    )

    ssh_only = _candidate("cp2k")
    ssh_only = replace(
        ssh_only,
        descriptor=replace(
            ssh_only.descriptor,
            compatibility=("ssh",),
            disable_model_invocation=True,
        ),
    )
    user = _candidate("cp2k", scope="user", dialect="agents")
    catalog = build_catalog(
        (ssh_only, user),
        generation=5,
        cwd="/w",
        repo_root="/r",
        resolution={"cp2k": "user:agents:cp2k"},
    )
    path = tmp_path / "policy.json"
    save_catalog_snapshot(catalog, path)
    restored = load_catalog_snapshot(path)

    # 策略元数据保留
    assert restored.resolution == {"cp2k": "user:agents:cp2k"}
    proj = restored.by_qualified_id()["project:repo:agents:cp2k"]
    assert proj.descriptor.compatibility == ("ssh",)
    assert proj.descriptor.disable_model_invocation is True
    # digest 一致：持久化 == 恢复后重算
    assert restored.catalog_digest == catalog.catalog_digest
    assert _catalog_digest(restored.candidates) == restored.catalog_digest
