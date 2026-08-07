"""M6: Artifact Manifest 与 Registry 测试。"""

from __future__ import annotations

import pytest

from electromind.artifacts import (
    ArtifactIntegrityError,
    ArtifactManifest,
    ArtifactRegistry,
    ArtifactStatus,
    ArtifactTransitionError,
    allowed_artifact_transitions,
    sha256_file,
)


def _manifest(**kw) -> ArtifactManifest:
    base = dict(
        artifact_id="art-1",
        type="parsed_result",
        path="out/energy.json",
        sha256="abc",
        run_id="run-1",
        step_id="s1",
        created_by="tool_call_1",
        units="Hartree",
    )
    base.update(kw)
    return ArtifactManifest(**base)


# ── 状态语义 ────────────────────────────────────────────────────────────


def test_artifact_status_transition_table():
    # REJECTED 可修复恢复（回到 COMPLETED/VALIDATED），但不能回到 CREATED
    assert ArtifactStatus.COMPLETED in allowed_artifact_transitions(
        ArtifactStatus.REJECTED
    )
    assert ArtifactStatus.CREATED not in allowed_artifact_transitions(
        ArtifactStatus.REJECTED
    )
    assert ArtifactStatus.ACCEPTED in allowed_artifact_transitions(
        ArtifactStatus.VALIDATED
    )
    assert ArtifactStatus.SUPERSEDED in allowed_artifact_transitions(
        ArtifactStatus.ACCEPTED
    )
    assert not allowed_artifact_transitions(ArtifactStatus.SUPERSEDED)  # 终态


def test_completed_is_not_validated():
    m = _manifest()
    completed = m.complete()
    assert completed.acceptance_status == ArtifactStatus.COMPLETED
    # 程序正常结束绝不自动 VALIDATED
    assert completed.acceptance_status != ArtifactStatus.VALIDATED


def test_validate_requires_parser():
    m = _manifest().complete()
    validated = m.validate(parser="energy_parser")
    # P0-7 双状态分离：validate 只动 validation_status
    assert validated.validation_status == ArtifactStatus.VALIDATED
    assert validated.acceptance_status == ArtifactStatus.COMPLETED
    assert validated.parser == "energy_parser"
    with pytest.raises(ArtifactTransitionError, match="解析器名"):
        m.validate(parser="")
    # 未 COMPLETED 不能直接 VALIDATED（acceptance 未完成时 validation 不可跳级）
    with pytest.raises(ArtifactTransitionError):
        _manifest().validate(parser="p")


def test_accept_requires_independent_who():
    m = _manifest().complete().validate(parser="p")
    accepted = m.accept(who="user-alice")
    assert accepted.acceptance_status == ArtifactStatus.ACCEPTED
    assert accepted.validation_status == ArtifactStatus.VALIDATED  # 双状态保留
    assert accepted.accepted_by == "user-alice"  # P0-7: 确认者持久化
    # 无确认者 → 拒绝
    with pytest.raises(ArtifactTransitionError, match="确认者"):
        m.accept(who="")
    # 创建者不能自行 ACCEPTED
    with pytest.raises(ArtifactTransitionError, match="自行 ACCEPTED"):
        _manifest().complete().validate(parser="p").accept(who="tool_call_1")


def test_reject_and_supersede():
    m = _manifest().complete()
    with pytest.raises(ArtifactTransitionError, match="原因"):
        m.reject(reason="")
    rejected = m.reject(reason="能量为正值，物理不可信")
    assert rejected.acceptance_status == ArtifactStatus.REJECTED
    # 修复后重新完成可恢复（P0-7 双状态：reject 只动 acceptance）
    recovered = rejected.complete().validate(parser="p2")
    assert recovered.acceptance_status == ArtifactStatus.COMPLETED
    assert recovered.validation_status == ArtifactStatus.VALIDATED
    superseded = recovered.accept(who="reviewer-bob").supersede(by="art-2")
    assert superseded.acceptance_status == ArtifactStatus.SUPERSEDED
    with pytest.raises(ArtifactTransitionError):
        superseded.complete()  # 终态不可再转换


def test_manifest_roundtrip():
    m = _manifest(units="eV", input_artifacts=("in-1",)).complete().validate(parser="p")
    d = m.to_dict()
    assert ArtifactManifest.from_dict(d) == m


def test_manifest_model_roundtrip():
    """P5: model 溯源字段随序列化往返，状态推进不丢失。"""
    m = _manifest(model="deepseek-v4-pro")
    d = m.to_dict()
    assert d["model"] == "deepseek-v4-pro"
    assert ArtifactManifest.from_dict(d).model == "deepseek-v4-pro"
    # 状态推进（complete/validate）不得清空 model
    progressed = m.complete().validate(parser="p")
    assert progressed.model == "deepseek-v4-pro"


def test_manifest_model_absent_backward_compat():
    """旧数据无 model 字段 → 空串（向后兼容）。"""
    d = _manifest().to_dict()
    del d["model"]
    assert ArtifactManifest.from_dict(d).model == ""


# ── Registry ────────────────────────────────────────────────────────────


def test_registry_register_and_query(tmp_path):
    registry = ArtifactRegistry()
    m = _manifest()
    registry.register(m)
    assert registry.get("art-1") == m
    assert len(registry) == 1
    assert [a.artifact_id for a in registry.for_run("run-1")] == ["art-1"]
    assert registry.by_status(ArtifactStatus.CREATED) == [m]
    assert registry.by_status(ArtifactStatus.ACCEPTED) == []


def test_registry_replace_records_event(tmp_path):
    registry = ArtifactRegistry()
    registry.register(_manifest(sha256="old"))
    registry.register(_manifest(sha256="new"))
    events = registry.events()
    assert any(e["event"] == "replace" and e["old_sha256"] == "old" for e in events)
    # P1.1：新版本成为当前版本（不再被标 SUPERSEDED）；旧版本保留在 @v1 槽
    current = registry.get("art-1")
    assert current.sha256 == "new"
    assert current.acceptance_status == ArtifactStatus.CREATED
    old = registry.get("art-1@v1")
    assert old.sha256 == "old"
    assert old.acceptance_status == ArtifactStatus.SUPERSEDED
    # 历史版本仅来自槽位查询；all()/len 只看当前版本
    assert len(registry) == 1
    assert [m.artifact_id for m in registry.all()] == ["art-1"]


def test_registry_replace_persists_both_versions(tmp_path):
    # P1.1：替换路径必须落盘——旧版本（SUPERSEDED）与新版本都要持久化，
    # 重新加载后一致（旧实现替换路径不 flush，新版本丢失）。
    path = tmp_path / "artifacts.jsonl"
    registry = ArtifactRegistry(path)
    registry.register(_manifest(sha256="old"))
    registry.register(_manifest(sha256="new"))
    reloaded = ArtifactRegistry(path)
    assert reloaded.get("art-1").sha256 == "new"
    assert reloaded.get("art-1").acceptance_status == ArtifactStatus.CREATED
    assert reloaded.get("art-1@v1").sha256 == "old"
    assert reloaded.get("art-1@v1").acceptance_status == ArtifactStatus.SUPERSEDED


def test_registry_replace_keeps_version_chain(tmp_path):
    # P1.1：连续多次替换必须保留全部历史版本，不能覆盖（旧 @old 单槽会丢 v1）。
    registry = ArtifactRegistry()
    registry.register(_manifest(sha256="v1"))
    registry.register(_manifest(sha256="v2"))
    registry.register(_manifest(sha256="v3"))
    assert registry.get("art-1").sha256 == "v3"
    assert registry.get("art-1@v1").sha256 == "v1"
    assert registry.get("art-1@v2").sha256 == "v2"
    assert [m.sha256 for m in registry.history("art-1")] == ["v1", "v2"]
    assert all(
        m.acceptance_status == ArtifactStatus.SUPERSEDED
        for m in registry.history("art-1")
    )
    # 持久化后版本链一致
    path = tmp_path / "artifacts.jsonl"
    registry2 = ArtifactRegistry(path)
    registry2.register(_manifest(sha256="v1"))
    registry2.register(_manifest(sha256="v2"))
    registry2.register(_manifest(sha256="v3"))
    reloaded = ArtifactRegistry(path)
    assert [m.sha256 for m in reloaded.history("art-1")] == ["v1", "v2"]
    assert reloaded.get("art-1@v2").sha256 == "v2"
    assert reloaded.get("art-1").sha256 == "v3"


def test_registry_recover_from_backup(tmp_path):
    """P1.3: artifacts.jsonl 整体损坏 → 从 .bak 自动恢复。"""

    path = tmp_path / "artifacts.jsonl"
    registry = ArtifactRegistry(path)
    registry.register(_manifest(sha256="v1"))  # 首写：无 .bak
    registry.register(_manifest(sha256="v2"))  # 二写：产生 .bak（含 v1）
    # 主文件损坏（截断的半写文件）
    path.write_text(
        '{"type": "manifest", "artifact_id": "art-1", "sha256": "v', encoding="utf-8"
    )
    reloaded = ArtifactRegistry(path)
    assert reloaded.get("art-1").sha256 == "v1"
    assert (tmp_path / "artifacts.jsonl.corrupt").exists()


def test_registry_delete_records_event(tmp_path):
    registry = ArtifactRegistry()
    registry.register(_manifest())
    assert registry.delete("art-1", reason="清理")
    assert registry.get("art-1") is None
    assert registry.events()[-1]["event"] == "delete"
    assert not registry.delete("art-1", reason="x")


# ── P2.5: 只有 ACCEPTED Artifact 可进 DeePMD 训练数据 ─────────────────


def test_training_data_candidates_only_accepted(tmp_path):
    from electromind.artifacts.training import (
        TrainingDataGateError,
        accepted_for_training,
        assert_accepted,
    )

    registry = ArtifactRegistry()
    # 一个写盘文件，供 SHA 校验
    f = tmp_path / "frame.xyz"
    f.write_text("3\n\nO 0 0 0\nH 1 0 0\nH 0 1 0\n", encoding="utf-8")
    digest = sha256_file(f)

    def manifest(**kw):
        base = dict(
            artifact_id="frame.xyz",
            type="data",
            path=str(f),
            sha256=digest,
            run_id="run-1",
            created_by="agent",
            units="Hartree",
        )
        base.update(kw)
        return ArtifactManifest(**base)

    # VALIDATED（未 ACCEPTED）→ 排除
    registry.register(manifest().complete().validate(parser="cp2k"))
    # COMPLETED（未验证）→ 排除
    registry.register(manifest(artifact_id="frame2.xyz").complete())
    # REJECTED → 排除
    registry.register(manifest(artifact_id="frame3.xyz").reject(reason="坏"))

    samples = accepted_for_training(registry, root=tmp_path)
    assert samples == []  # 没有任何 ACCEPTED → 训练集为空

    # 用户确认 ACCEPTED → 进入
    accepted = (
        manifest(artifact_id="frame4.xyz")
        .complete()
        .validate(parser="cp2k")
        .accept(who="user-alice")
    )
    registry.register(accepted)
    samples = accepted_for_training(registry, root=tmp_path)
    assert len(samples) == 1
    assert samples[0]["artifact_id"] == "frame4.xyz"
    assert samples[0]["accepted_by"] == "user-alice"
    assert samples[0]["parser"] == "cp2k"

    # assert_accepted 单点门
    assert_accepted(accepted)
    with pytest.raises(TrainingDataGateError, match="未 ACCEPTED"):
        assert_accepted(registry.get("frame.xyz"))


def test_training_gate_rejects_sha_mismatch(tmp_path):
    """P2.5: ACCEPTED 但文件被改 → 训练门拒绝（SHA 不一致不可信）。"""
    from electromind.artifacts.training import (
        TrainingDataGateError,
        accepted_for_training,
    )

    f = tmp_path / "frame.xyz"
    f.write_text("v1", encoding="utf-8")
    digest = sha256_file(f)
    registry = ArtifactRegistry()
    registry.register(
        _manifest(path=str(f), sha256=digest)
        .complete()
        .validate(parser="cp2k")
        .accept(who="user")
    )
    # 文件被改 → SHA 不符
    f.write_text("v2-changed", encoding="utf-8")
    with pytest.raises(TrainingDataGateError, match="SHA|摘要|禁止进入训练集"):
        accepted_for_training(registry, root=tmp_path)
    # 关闭 SHA 校验 → 仍返回（调用方自担风险），但默认必须校验
    samples = accepted_for_training(registry, root=tmp_path, verify_sha=False)
    assert len(samples) == 1


def test_registry_integrity(tmp_path):
    registry = ArtifactRegistry()
    f = tmp_path / "energy.json"
    f.write_text('{"value": -76.4}', encoding="utf-8")
    digest = sha256_file(f)
    registry.register(_manifest(path=str(f), sha256=digest))
    registry.verify_integrity(registry.get("art-1"), tmp_path)
    # 摘要不符
    registry.register(_manifest(artifact_id="art-2", path=str(f), sha256="wrong"))
    with pytest.raises(ArtifactIntegrityError, match="摘要不符"):
        registry.verify_integrity(registry.get("art-2"), tmp_path)
    # 指向不存在文件
    registry.register(_manifest(artifact_id="art-3", path="nope.json", sha256="x"))
    with pytest.raises(ArtifactIntegrityError, match="不存在"):
        registry.verify_integrity(registry.get("art-3"), tmp_path)
    # 相对路径基于 root 解析
    registry.register(_manifest(artifact_id="art-4", path="energy.json", sha256=digest))
    registry.verify_integrity(registry.get("art-4"), tmp_path)


def test_registry_verify_all(tmp_path):
    registry = ArtifactRegistry()
    f = tmp_path / "ok.json"
    f.write_text("ok", encoding="utf-8")
    registry.register(_manifest(path=str(f), sha256=sha256_file(f)))
    registry.register(_manifest(artifact_id="bad", path="missing.json", sha256="x"))
    errors = registry.verify_all(tmp_path)
    assert len(errors) == 1
    assert "bad" in errors[0]


def test_registry_dependency_graph(tmp_path):
    registry = ArtifactRegistry()
    registry.register(_manifest(artifact_id="in-1", type="data"))
    registry.register(
        _manifest(artifact_id="mid", input_artifacts=("in-1",), type="parsed_result")
    )
    registry.register(
        _manifest(artifact_id="out", input_artifacts=("mid",), type="report")
    )
    inputs = registry.inputs_of("out")
    assert [m.artifact_id for m in inputs] == ["mid"]
    chain = registry.trace("out")
    assert chain == ["out", "mid", "in-1"]


def test_registry_persistence(tmp_path):
    path = tmp_path / "registry.jsonl"
    registry = ArtifactRegistry(path)
    m = _manifest().complete().validate(parser="p").accept(who="user")
    registry.register(m)
    registry.delete("art-1", reason="清理")
    registry2 = ArtifactRegistry(path)
    assert registry2.get("art-1") is None
    assert registry2.events()[-1]["event"] == "delete"


# ── P0-7 验收：输入缺失 / 数值溯源 ──────────────────────────────────────


def test_registry_missing_input_recorded_and_verified(tmp_path):
    """P0-7: 输入 Artifact 缺失 → 注册事件 + verify_all 错误（不静默）。"""
    registry = ArtifactRegistry()
    registry.register(
        _manifest(artifact_id="out", input_artifacts=("in-1",), type="report")
    )
    assert any(e["event"] == "missing_input" for e in registry.events())
    errors = registry.verify_all(tmp_path)
    assert any("输入 in-1 缺失" in e for e in errors)
    # 补齐输入后不再报缺失
    registry.register(
        _manifest(artifact_id="in-1", type="data", path="in.txt", sha256="x")
    )
    errors2 = registry.verify_all(tmp_path)
    assert not any("输入" in e for e in errors2)


def test_value_provenance_roundtrip(tmp_path):
    """P0-7: 数值级溯源（值→文件→行→解析规则→单位）持久化。"""
    from electromind.artifacts import ProvenanceStore, ValueProvenance

    store = ProvenanceStore(str(tmp_path / "provenance.jsonl"))
    store.record(
        ValueProvenance(
            value="-76.4",
            unit="Hartree",
            source_file="energy.out",
            source_line=3,
            source_snippet="ENERGY| Total FORCE_EVAL ( QS ) energy [Hartree] -76.4",
            parser="cp2k_energy_parser",
            artifact_id="energy-1",
        )
    )
    assert len(store) == 1
    assert store.for_artifact("energy-1")[0].unit == "Hartree"
    assert store.for_file("energy.out")[0].source_line == 3
    assert len(store.with_unit("eV")) == 0
    # 跨实例恢复
    store2 = ProvenanceStore(str(tmp_path / "provenance.jsonl"))
    assert store2.for_artifact("energy-1")[0].parser == "cp2k_energy_parser"


def test_provenance_no_path_no_flush(tmp_path):
    """P0-8: 无路径 ProvenanceStore 不落盘；损坏行 fail-soft。"""
    from electromind.artifacts import ProvenanceStore, ValueProvenance

    mem = ProvenanceStore()  # 无 path
    mem.record(ValueProvenance(value="1", unit="eV", source_file="f"))
    assert len(mem) == 1
    path = tmp_path / "p.jsonl"
    path.write_text("garbage\n", encoding="utf-8")
    store = ProvenanceStore(str(path))
    assert len(store) == 0


def test_artifact_memory_search_branches(tmp_path):
    import time

    from electromind.context import ArtifactMemory, ArtifactMemoryEntry

    memory = ArtifactMemory()
    e1 = ArtifactMemoryEntry(
        artifact_id="a",
        type="data",
        path="x",
        step_id="s1",
        run_id="r1",
        validation_status="created",
        created_at=time.time(),
    )
    memory.add(e1)
    assert memory.search(step_id="s2") == []
    assert memory.search(run_id="r2") == []
    assert memory.search(created_after=time.time() + 100) == []
    assert memory.search(step_id="s1")[0].artifact_id == "a"
    assert memory.search(created_after=0)[0].artifact_id == "a"


def test_registry_trace_and_cycle_branches(tmp_path):
    """P0-8: trace 去环 + 缺失输入节点 + 事件恢复。"""
    registry = ArtifactRegistry()
    registry.register(_manifest(artifact_id="a", type="data"))
    registry.register(
        _manifest(artifact_id="b", input_artifacts=("a", "missing"), type="mid")
    )
    registry.register(_manifest(artifact_id="b2", input_artifacts=("b",), type="out"))
    # trace 包含存在链；缺失输入不崩溃
    chain = registry.trace("b2")
    assert "b2" in chain and "b" in chain and "a" in chain
    # inputs_of 缺失 → 空（有 warning 事件）
    assert registry.inputs_of("nope") == []
    # 事件恢复：JSONL 含 event 行
    path = tmp_path / "r.jsonl"
    r2 = ArtifactRegistry(path)
    r2.register(_manifest(artifact_id="x", type="data"))
    r2.delete("x", reason="cleanup")
    r3 = ArtifactRegistry(path)
    assert r3.get("x") is None
    assert any(e["event"] == "delete" for e in r3.events())


def test_accept_requires_validated():
    """R2-6: 未 VALIDATED 不能 ACCEPTED（科学状态验收）。"""
    from electromind.artifacts.manifest import ArtifactTransitionError

    completed_only = _manifest().complete()
    with pytest.raises(ArtifactTransitionError, match="未 VALIDATED"):
        completed_only.accept(who="user")
    validated = completed_only.validate(parser="checker")
    accepted = validated.accept(who="user")
    assert accepted.acceptance_status == ArtifactStatus.ACCEPTED
