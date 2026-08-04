"""SKILL-3 tests: multi-candidate catalog, resolver, budget, overrides, snapshots.

The legacy first-wins ``SkillRegistry`` behavior is unchanged; these tests lock
in the new candidate-based catalog and its three resolver policies.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from electromind.skills.candidate import (
    SkillCandidate,
    SkillDescriptor,
    SkillSource,
)
from electromind.skills.catalog import (
    MultiCandidateCatalog,
    ResolvedSkill,
    SkillResolutionAmbiguous,
    SkillResolutionError,
    SkillResolver,
    apply_overrides,
    build_catalog,
    build_model_catalog,
    load_catalog_snapshot,
    save_catalog_snapshot,
)


def _candidate(
    name: str,
    *,
    scope: str = "project",
    dialect: str = "agents",
    project_dir: str = "repo",
    enabled: str = "on",
    trust: str = "trusted",
    description: str = "desc",
    compatibility: tuple[str, ...] = (),
) -> SkillCandidate:
    source = SkillSource(
        source_id=f"{scope}-{dialect}-{name}",
        scope=scope,  # type: ignore[arg-type]
        dialect=dialect,  # type: ignore[arg-type]
        root=Path(f"/{scope}/{project_dir}/{dialect}/{name}"),
        project_root=Path(f"/{scope}/{project_dir}") if scope == "project" else None,
        distance_from_cwd=0 if scope == "project" else None,
        trust_domain=f"/{scope}/{project_dir}" if scope == "project" else scope,
    )
    from electromind.skills.candidate import make_skill_id

    skill_id = make_skill_id(
        scope=scope,
        name=name,
        dialect=dialect,
        project_dir=project_dir if scope == "project" else None,
    )
    descriptor = SkillDescriptor(
        name=name,
        description=description,
        entry_path=source.root / "SKILL.md",
        root_path=source.root,
        frontmatter={"name": name, "description": description},
        content_digest=f"c{name}",
        resource_digest=f"r{name}",
        compatibility=compatibility,
    )
    return SkillCandidate(
        skill_id=skill_id,
        descriptor=descriptor,
        source=source,
        enabled_state=enabled,  # type: ignore[arg-type]
        trust_state=trust,  # type: ignore[arg-type]
    )


def _catalog(*candidates: SkillCandidate, generation: int = 1) -> MultiCandidateCatalog:
    return build_catalog(candidates, generation=generation, cwd="/w", repo_root="/r")


# ---------------------------------------------------------------------------
# Catalog: candidate retention
# ---------------------------------------------------------------------------


class TestMultiCandidateCatalog:
    def test_same_name_candidates_all_retained(self):
        """同名候选全部保留 — no first-wins dropping."""
        a = _candidate("cp2k", scope="user", dialect="agents")
        b = _candidate("cp2k", scope="project", project_dir="repo")
        catalog = _catalog(a, b)

        assert len(catalog.candidates) == 2
        assert catalog.names() == ["cp2k"]
        by_name = catalog.by_name()
        assert len(by_name["cp2k"]) == 2

    def test_qualified_id_index_exact(self):
        a = _candidate("cp2k", scope="user", dialect="agents")
        b = _candidate("cp2k", scope="project", project_dir="repo")
        catalog = _catalog(a, b)
        idx = catalog.by_qualified_id()
        assert idx["user:agents:cp2k"] is a
        assert idx["project:repo:agents:cp2k"] is b

    def test_shadowed_marks_lower_priority(self):
        """Higher-priority (first) candidate wins; later same-name is shadowed."""
        a = _candidate("cp2k", scope="user", dialect="agents")
        b = _candidate("cp2k", scope="project", project_dir="repo")
        catalog = _catalog(a, b)
        shadowed = catalog.shadowed()
        assert len(shadowed) == 1
        assert shadowed[0] is b

    def test_catalog_digest_changes_with_state(self):
        a = _candidate("cp2k")
        d1 = _catalog(a).catalog_digest
        b = replace(a, enabled_state="off")
        d2 = _catalog(b).catalog_digest
        assert d1 != d2


# ---------------------------------------------------------------------------
# Resolver: qualified explicit
# ---------------------------------------------------------------------------


class TestQualifiedResolution:
    def test_exact_match(self):
        a = _candidate("cp2k", scope="user", dialect="agents")
        catalog = _catalog(a)
        resolved = SkillResolver(catalog).resolve_qualified("user:agents:cp2k")
        assert isinstance(resolved, ResolvedSkill)
        assert resolved.candidate is a
        assert "qualified id match" in resolved.resolution_reason

    def test_unknown_id_raises(self):
        catalog = _catalog(_candidate("cp2k"))
        with pytest.raises(SkillResolutionError, match="unknown qualified"):
            SkillResolver(catalog).resolve_qualified("user:agents:nope")

    def test_disabled_raises(self):
        a = _candidate("cp2k", enabled="off")
        catalog = _catalog(a)
        with pytest.raises(SkillResolutionError, match="disabled"):
            SkillResolver(catalog).resolve_qualified("project:repo:agents:cp2k")

    def test_disabled_allowed_with_flag(self):
        a = _candidate("cp2k", enabled="off")
        catalog = _catalog(a)
        resolved = SkillResolver(catalog).resolve_qualified(
            "project:repo:agents:cp2k", allow_disabled=True
        )
        assert resolved.candidate is a

    def test_untrusted_raises_with_needs_trust(self):
        a = _candidate("cp2k", trust="untrusted")
        catalog = _catalog(a)
        with pytest.raises(SkillResolutionError) as exc:
            SkillResolver(catalog).resolve_qualified("project:repo:agents:cp2k")
        assert exc.value.needs_trust is True

    def test_capability_incompatible_raises(self):
        a = _candidate("cp2k", compatibility=("ssh",))
        catalog = _catalog(a)
        with pytest.raises(SkillResolutionError, match="incompatible"):
            SkillResolver(catalog).resolve_qualified(
                "project:repo:agents:cp2k", capabilities=("local",)
            )

    def test_capability_compatible_ok(self):
        a = _candidate("cp2k", compatibility=("ssh",))
        catalog = _catalog(a)
        resolved = SkillResolver(catalog).resolve_qualified(
            "project:repo:agents:cp2k", capabilities=("ssh",)
        )
        assert resolved.candidate is a


# ---------------------------------------------------------------------------
# Resolver: unqualified explicit
# ---------------------------------------------------------------------------


class TestUnqualifiedResolution:
    def test_unique_candidate_resolves(self):
        a = _candidate("cp2k")
        catalog = _catalog(a)
        resolved = SkillResolver(catalog).resolve_unqualified("cp2k", interactive=True)
        assert resolved.candidate is a

    def test_ambiguous_interactive_raises_ambiguous(self):
        a = _candidate("cp2k", scope="user", dialect="agents")
        b = _candidate("cp2k", scope="project", project_dir="repo")
        catalog = _catalog(a, b)
        with pytest.raises(SkillResolutionAmbiguous) as exc:
            SkillResolver(catalog).resolve_unqualified("cp2k", interactive=True)
        assert len(exc.value.candidates) == 2
        assert exc.value.requires_qualified_id is False

    def test_ambiguous_non_interactive_requires_qualified(self):
        a = _candidate("cp2k", scope="user", dialect="agents")
        b = _candidate("cp2k", scope="project", project_dir="repo")
        catalog = _catalog(a, b)
        with pytest.raises(SkillResolutionAmbiguous) as exc:
            SkillResolver(catalog).resolve_unqualified("cp2k", interactive=False)
        assert exc.value.requires_qualified_id is True
        assert "qualified skill id" in exc.value.reason

    def test_no_usable_raises_error(self):
        catalog = _catalog(_candidate("cp2k", trust="untrusted"))
        with pytest.raises(SkillResolutionError):
            SkillResolver(catalog).resolve_unqualified("cp2k", interactive=True)

    def test_shadowed_candidate_not_usable(self):
        """shadowed (lower-priority) candidate is not directly usable."""
        a = _candidate("cp2k", scope="user", dialect="agents")
        b = _candidate("cp2k", scope="project", project_dir="repo", enabled="off")
        catalog = _catalog(a, b)
        resolved = SkillResolver(catalog).resolve_unqualified("cp2k", interactive=True)
        assert resolved.candidate is a


# ---------------------------------------------------------------------------
# Resolver: model implicit
# ---------------------------------------------------------------------------


class TestImplicitResolution:
    def test_unique_visible_resolves(self):
        a = _candidate("cp2k")
        catalog = _catalog(a)
        result = SkillResolver(catalog).resolve_implicit("cp2k")
        assert isinstance(result, ResolvedSkill)
        assert result.candidate is a

    def test_manual_only_not_implicit(self):
        a = _candidate("cp2k", enabled="manual_only")
        catalog = _catalog(a)
        result = SkillResolver(catalog).resolve_implicit("cp2k")
        assert isinstance(result, SkillResolutionAmbiguous)
        assert result.candidates == ()

    def test_name_only_is_implicit(self):
        a = _candidate("cp2k", enabled="name_only")
        catalog = _catalog(a)
        result = SkillResolver(catalog).resolve_implicit("cp2k")
        assert isinstance(result, ResolvedSkill)

    def test_untrusted_not_implicit_no_dialog(self):
        """未信任候选 → 不解析；隐式调用绝不触发 Trust 对话（RFC 四 #3）。"""
        a = _candidate("cp2k", trust="untrusted")
        catalog = _catalog(a)
        result = SkillResolver(catalog).resolve_implicit("cp2k")
        assert isinstance(result, SkillResolutionAmbiguous)
        assert result.candidates == ()

    def test_same_level_ambiguity_no_guess(self):
        """同等级歧义（同 scope 同 dialect、不同来源）→ 不激活。"""
        a = _candidate("cp2k", scope="user", dialect="agents")
        b = replace(a, skill_id="user:agents:cp2k-alt")
        catalog = _catalog(a, b)
        result = SkillResolver(catalog).resolve_implicit("cp2k")
        assert isinstance(result, SkillResolutionAmbiguous)
        assert len(result.candidates) == 2

    def test_dialect_tiebreak_within_scope(self):
        """同一 scope 内按方言顺序破平局：agents 压过 claude。"""
        agents = _candidate("cp2k", scope="user", dialect="agents")
        claude = _candidate("cp2k", scope="user", dialect="claude")
        catalog = _catalog(agents, claude)
        result = SkillResolver(catalog).resolve_implicit("cp2k")
        assert isinstance(result, ResolvedSkill)
        assert result.candidate is agents

    def test_higher_priority_visible_wins(self):
        """不同等级（不同 scope priority）→ 唯一最高候选允许激活。"""
        user = _candidate("cp2k", scope="user", dialect="agents")
        proj = _candidate("cp2k", scope="project", project_dir="repo")
        catalog = _catalog(user, proj)
        result = SkillResolver(catalog).resolve_implicit("cp2k")
        # user scope outranks project scope → unique top candidate
        assert isinstance(result, ResolvedSkill)
        assert result.candidate is user

    def test_capability_filter_applies(self):
        a = _candidate("cp2k", compatibility=("ssh",))
        catalog = _catalog(a)
        result = SkillResolver(catalog).resolve_implicit(
            "cp2k", capabilities=("local",)
        )
        assert isinstance(result, SkillResolutionAmbiguous)


# ---------------------------------------------------------------------------
# Picker
# ---------------------------------------------------------------------------


class TestPicker:
    def test_picker_shows_everything(self):
        """Picker 展示全部候选：含 shadowed/manual-only/disabled/untrusted。"""
        a = _candidate("cp2k", scope="user", dialect="agents")
        b = _candidate("cp2k", scope="project", project_dir="repo", enabled="off")
        c = _candidate("other", enabled="manual_only", trust="untrusted")
        catalog = _catalog(a, b, c)
        picked = SkillResolver(catalog).picker_candidates()
        assert len(picked) == 3


# ---------------------------------------------------------------------------
# Catalog budget
# ---------------------------------------------------------------------------


class TestCatalogBudget:
    def test_manual_only_excluded(self):
        a = _candidate("a", enabled="manual_only")
        b = _candidate("b")
        result = build_model_catalog(_catalog(a, b))
        names = [e.name for e in result.entries]
        assert "a" not in names
        assert "b" in names

    def test_shadowed_excluded(self):
        a = _candidate("cp2k", scope="user", dialect="agents")
        b = _candidate("cp2k", scope="project", project_dir="repo")
        result = build_model_catalog(_catalog(a, b))
        assert len(result.entries) == 1
        assert result.entries[0].name == "cp2k"

    def test_name_only_keeps_name_only(self):
        a = _candidate("a", enabled="name_only")
        result = build_model_catalog(_catalog(a))
        assert result.entries[0].description == ""
        assert result.entries[0].name == "a"

    def test_off_excluded(self):
        """off Skill 不得进入模型 Catalog（也不会遮蔽可用候选）。"""
        off = _candidate("a", enabled="off")
        usable = _candidate("a", scope="user", dialect="agents")
        result = build_model_catalog(_catalog(off, usable))
        names = [e.name for e in result.entries]
        assert "a" in names
        # The usable candidate (not the off one) entered
        assert result.entries[0].skill_id == usable.skill_id

    def test_off_alone_excluded(self):
        off = _candidate("a", enabled="off")
        result = build_model_catalog(_catalog(off))
        assert result.entries == ()
        assert len(result.diagnostics) == 0

    def test_tight_budget_omits_with_diagnostic(self):
        a = _candidate("aaa", description="x" * 500)
        b = _candidate("bbb", description="y" * 500)
        result = build_model_catalog(_catalog(a, b), budget=100)
        assert result.total_chars <= 100
        assert len(result.diagnostics) >= 1
        assert "omitted" in result.diagnostics[0]


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


class TestOverrides:
    def test_state_override_applied(self):
        a = _candidate("cp2k")
        updated, resolution, diags = apply_overrides(
            (a,),
            {"project:repo:agents:cp2k": {"state": "manual_only"}},
        )
        assert updated[0].enabled_state == "manual_only"
        assert diags == []

    def test_resolution_pin_validated(self):
        a = _candidate("cp2k")
        _updated, resolution, diags = apply_overrides(
            (a,), {}, {"cp2k": "project:repo:agents:cp2k"}
        )
        assert resolution["cp2k"] == "project:repo:agents:cp2k"
        assert diags == []

    def test_resolution_pin_unknown_diagnostic(self):
        a = _candidate("cp2k")
        _updated, _resolution, diags = apply_overrides(
            (a,), {}, {"cp2k": "user:agents:ghost"}
        )
        assert len(diags) == 1
        assert "does not match any candidate" in diags[0]

    def test_invalid_state_diagnostic(self):
        a = _candidate("cp2k")
        updated, _res, diags = apply_overrides(
            (a,), {"project:repo:agents:cp2k": {"state": "bogus"}}
        )
        assert updated[0].enabled_state == "on"  # untouched
        assert len(diags) == 1


# ---------------------------------------------------------------------------
# Generation snapshot persistence
# ---------------------------------------------------------------------------


class TestSnapshotPersistence:
    def test_round_trip_preserves_metadata(self, tmp_path):
        a = _candidate("cp2k", scope="user", dialect="agents")
        b = _candidate("cp2k", scope="project", project_dir="repo", enabled="off")
        catalog = _catalog(a, b, generation=7)

        path = tmp_path / "catalog.json"
        save_catalog_snapshot(catalog, path)
        restored = load_catalog_snapshot(path)

        assert restored.generation == 7
        assert restored.catalog_digest == catalog.catalog_digest
        assert restored.names() == ["cp2k"]
        restored_idx = restored.by_qualified_id()
        assert "user:agents:cp2k" in restored_idx
        assert restored_idx["project:repo:agents:cp2k"].enabled_state == "off"
        # No private bodies are stored
        text = path.read_text(encoding="utf-8")
        assert "instructions" not in text

    def test_snapshot_never_contains_body(self, tmp_path):
        a = _candidate("cp2k")
        path = tmp_path / "snap.json"
        save_catalog_snapshot(_catalog(a), path)
        raw = path.read_text(encoding="utf-8")
        assert "body" not in raw.lower()
        assert "SKILL.md" not in raw


# ---------------------------------------------------------------------------
# Resolution pins in the resolver (FIX-9)
# ---------------------------------------------------------------------------


class TestResolutionPins:
    def test_pin_overrides_ambiguity(self):
        """resolution pin 消除歧义：name → 指定 qualified id。"""
        a = _candidate("cp2k", scope="user", dialect="agents")
        b = _candidate("cp2k", scope="project", project_dir="repo")
        catalog = _catalog(a, b)
        resolver = SkillResolver(
            catalog, resolution={"cp2k": "project:repo:agents:cp2k"}
        )
        resolved = resolver.resolve_unqualified("cp2k", interactive=False)
        assert resolved.candidate is b

    def test_pin_applies_to_implicit(self):
        a = _candidate("cp2k", scope="user", dialect="agents")
        b = _candidate("cp2k", scope="project", project_dir="repo")
        catalog = _catalog(a, b)
        resolver = SkillResolver(
            catalog, resolution={"cp2k": "project:repo:agents:cp2k"}
        )
        result = resolver.resolve_implicit("cp2k")
        assert isinstance(result, ResolvedSkill)
        assert result.candidate is b

    def test_pin_untrusted_raises(self):
        a = _candidate("cp2k", trust="untrusted")
        catalog = _catalog(a)
        resolver = SkillResolver(
            catalog, resolution={"cp2k": "project:repo:agents:cp2k"}
        )
        with pytest.raises(SkillResolutionError):
            resolver.resolve_unqualified("cp2k", interactive=False)


# ---------------------------------------------------------------------------
# P1 regressions: frontmatter policy fields (SKILL-FIX round 2)
# ---------------------------------------------------------------------------


class TestDisableModelInvocation:
    """P1: disable-model-invocation 排除出模型 Catalog 且不可隐式激活。"""

    def test_disabled_for_model_excluded_from_catalog(self):
        a = _candidate("secret", description="s")
        from dataclasses import replace as _r

        a = _r(
            a,
            descriptor=_r(a.descriptor, disable_model_invocation=True),
        )
        result = build_model_catalog(_catalog(a))
        assert result.entries == ()

    def test_disabled_for_model_not_implicitly_resolvable(self):
        a = _candidate("secret")
        from dataclasses import replace as _r

        a = _r(a, descriptor=_r(a.descriptor, disable_model_invocation=True))
        catalog = _catalog(a)
        result = SkillResolver(catalog).resolve_implicit("secret")
        assert isinstance(result, SkillResolutionAmbiguous)
        assert result.candidates == ()

    def test_disabled_for_model_still_user_invocable(self):
        """用户显式调用不受 disable-model-invocation 限制。"""
        a = _candidate("secret")
        from dataclasses import replace as _r

        a = _r(a, descriptor=_r(a.descriptor, disable_model_invocation=True))
        catalog = _catalog(a)
        resolved = SkillResolver(catalog).resolve_qualified(
            "project:repo:agents:secret"
        )
        assert resolved.candidate is a


class TestCompatibilityInDescriptor:
    """P1: frontmatter compatibility 写入 descriptor 并参与能力校验。"""

    def test_compatibility_parsed_from_frontmatter(self):
        from electromind.skills.scopes import _parse_compatibility

        assert _parse_compatibility({"compatibility": "ssh"}) == ("ssh",)
        assert _parse_compatibility({"compatibility": ["ssh", "local"]}) == (
            "ssh",
            "local",
        )
        assert _parse_compatibility({}) == ()

    def test_ssh_only_skill_not_resolvable_locally(self):
        """声明 compatibility: ssh 的 Skill 在 local capability 下不可解析。"""

        a = _candidate("cp2k", compatibility=("ssh",))
        catalog = _catalog(a)
        with pytest.raises(SkillResolutionError, match="no usable skill"):
            SkillResolver(catalog).resolve_unqualified(
                "cp2k", interactive=False, capabilities=("local",)
            )
        # 无 capability 声明时不限制
        resolved = SkillResolver(catalog).resolve_unqualified("cp2k", interactive=False)
        assert resolved.candidate is a


class TestSnapshotRoundTripPolicy:
    """P1: round-trip 保留 resolution/compatibility/disable_model_invocation，
    且恢复后 digest 与内容一致。"""

    def _policy_catalog(self):
        from dataclasses import replace as _r

        a = _candidate("cp2k", compatibility=("ssh",))
        a = _r(
            a,
            descriptor=_r(
                a.descriptor,
                disable_model_invocation=True,
            ),
        )
        b = _candidate("cp2k", scope="user", dialect="agents")
        return build_catalog(
            (a, b),
            generation=5,
            cwd="/w",
            repo_root="/r",
            resolution={"cp2k": "user:agents:cp2k"},
        )

    def test_round_trip_preserves_policy_metadata(self, tmp_path):
        catalog = self._policy_catalog()
        path = tmp_path / "policy.json"
        save_catalog_snapshot(catalog, path)
        restored = load_catalog_snapshot(path)

        # resolution 保留
        assert restored.resolution == {"cp2k": "user:agents:cp2k"}
        # compatibility / disable_model_invocation 保留
        proj = restored.by_qualified_id()["project:repo:agents:cp2k"]
        assert proj.descriptor.compatibility == ("ssh",)
        assert proj.descriptor.disable_model_invocation is True
        user = restored.by_qualified_id()["user:agents:cp2k"]
        assert user.descriptor.compatibility == ()
        assert user.descriptor.disable_model_invocation is False

    def test_round_trip_digest_consistent(self, tmp_path):
        """恢复后重新计算的 digest 必须等于持久化的 digest。"""
        catalog = self._policy_catalog()
        path = tmp_path / "policy.json"
        save_catalog_snapshot(catalog, path)
        restored = load_catalog_snapshot(path)

        assert restored.catalog_digest == catalog.catalog_digest
        # 恢复对象的候选语义与 digest 一致：重新计算也相同
        from electromind.skills.catalog import _catalog_digest

        recomputed = _catalog_digest(restored.candidates)
        assert recomputed == restored.catalog_digest

    def test_restored_catalog_behaves_like_original(self, tmp_path):
        """SSH-only 限制与 disable-model-invocation 恢复后仍生效。"""

        catalog = self._policy_catalog()
        path = tmp_path / "policy.json"
        save_catalog_snapshot(catalog, path)
        restored = load_catalog_snapshot(path)

        resolver = SkillResolver(restored)
        # SSH-only 候选（project:repo:agents:cp2k）在 local 下不可解析
        with pytest.raises(SkillResolutionError, match="no usable skill"):
            resolver.resolve_unqualified(
                "project:repo:agents:cp2k", interactive=False, capabilities=("local",)
            )
        # resolution pin 在恢复后仍生效（指向无限制的 user 候选）
        resolved = resolver.resolve_unqualified(
            "cp2k", interactive=False, capabilities=("local",)
        )
        assert resolved.candidate.skill_id == "user:agents:cp2k"
        # 恢复的 pin 目标（user:agents:cp2k）非 disable-model-invocation
        result = resolver.resolve_implicit("cp2k", capabilities=("local",))
        assert isinstance(result, ResolvedSkill)


class TestSnapshotSchemaVersion:
    """schema_version：显式化 digest 算法版本；旧格式缺省 v1。"""

    def test_new_snapshot_is_v2(self, tmp_path):
        a = _candidate("cp2k", compatibility=("ssh",))
        catalog = build_catalog(
            (a,),
            generation=1,
            cwd="/w",
            repo_root="/r",
            resolution={"cp2k": "user:agents:cp2k"},
        )
        path = tmp_path / "v2.json"
        save_catalog_snapshot(catalog, path)
        raw = path.read_text(encoding="utf-8")
        assert '"schema_version": 2' in raw
        restored = load_catalog_snapshot(path)
        assert restored.schema_version == 2

    def test_legacy_snapshot_loads_as_v1(self, tmp_path):
        """旧格式（无 schema_version）→ v1 + 安全默认值。"""
        import json

        a = _candidate("cp2k")
        catalog = build_catalog((a,), generation=1, cwd="/w", repo_root="/r")
        path = tmp_path / "v1.json"
        save_catalog_snapshot(catalog, path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        del payload["schema_version"]  # 模拟旧格式
        del payload["resolution"]
        for item in payload["candidates"]:
            item.pop("compatibility", None)
            item.pop("disable_model_invocation", None)
        path.write_text(json.dumps(payload), encoding="utf-8")

        restored = load_catalog_snapshot(path)
        assert restored.schema_version == 1
        # 安全默认值：无策略元数据
        cand = restored.by_qualified_id()["project:repo:agents:cp2k"]
        assert cand.descriptor.compatibility == ()
        assert cand.descriptor.disable_model_invocation is False
        assert restored.resolution == {}
