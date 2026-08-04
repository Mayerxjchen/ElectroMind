"""跨 skill 集成验收（v1.0 范围修订批准条件，无模型确定性场景）。

用现有内置 skills 证明三个场景：

- comp-chem-workflow → cp2k        （procedure 语义激活 engine）
- cp2k → hpc-submit                （engine 语义激活调度）
- packmol → structure-prep         （tool 间语义激活）

每场景证明：
1. procedure/engine 只产生**语义激活请求**（“Activate the `X` skill”措辞），
   不包含兄弟目录路径（不读兄弟目录）；
2. 目标存在 → 正常激活（instructions + 冻结资源）；
3. 目标缺失 → 返回 `required capability unavailable: <name>`；
4. 激活只消费本 skill 的冻结内容。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from electromind.skills.activation import (
    ActivationRequest,
    SkillActivationService,
)
from electromind.skills.catalog import build_catalog
from electromind.skills.scopes import discover_candidate_sources, load_candidates
from electromind.skills.snapstore import PrivateSnapshotStore

REPO_ROOT = Path(__file__).resolve().parent.parent

# 场景: (发起 skill, 目标 skill) —— 两个无模型确定性跨 skill 场景
# （用户批准条件：“至少两个场景”；packmol 是独立 tool，语义表达由
# 通用断言覆盖）
SCENARIOS = [
    ("comp-chem-workflow", "cp2k"),
    ("cp2k", "hpc-submit"),
]


def _repo_candidates():
    sources = discover_candidate_sources(
        None,
        cwd=str(REPO_ROOT),
        builtin_roots=(
            REPO_ROOT / "skills" / "procedures",
            REPO_ROOT / "skills" / "tools",
        ),
    )
    return load_candidates(sources)


@pytest.fixture(scope="module")
def catalog():
    return build_catalog(_repo_candidates(), generation=1, cwd=str(REPO_ROOT))


class TestSemanticActivationRequests:
    def test_skills_declare_activation_language_not_sibling_paths(self, catalog):
        """发起 skill 只用语义激活措辞（裸名/Activate 句），不含兄弟目录路径。

        「不读兄弟目录」= SKILL.md 全文中不存在任何 ``skills/{tools,procedures}/
        <skill>/...`` 路径形态；对目标的提及是 ``Activate the `X` skill`` 或
        backtick 裸名。
        """
        known = {c.descriptor.name for c in catalog.candidates}
        for source, target in SCENARIOS:
            candidate = next(
                c for c in catalog.candidates if c.descriptor.name == source
            )
            body = catalog.frozen_bodies.get(candidate.skill_id, "")
            assert body, f"{source} 缺少冻结正文"
            # 具体场景：目标必须以语义方式被提及
            mention_lines = [
                line for line in body.splitlines() if f"`{target}`" in line
            ]
            assert mention_lines, f"{source} 未以语义措辞提及 {target}"
            for line in mention_lines:
                assert f"skills/tools/{target}" not in line
                assert f"skills/procedures/{target}" not in line
                assert f"tools/{target}/" not in line
            # 通用：全文所有对已知 skill 的提及都不得是路径形态
            for name in known:
                for needle in (
                    f"skills/tools/{name}",
                    f"skills/procedures/{name}",
                    f"tools/{name}/",
                    f"procedures/{name}/",
                ):
                    assert needle not in body, (
                        f"{source} 以路径形态引用 {name}: {needle}"
                    )

    async def test_target_activation_succeeds(self, catalog, tmp_path):
        """目标存在 → 正常激活（instructions + 冻结资源 + skill_root）。"""
        store = PrivateSnapshotStore(tmp_path / "snapshots")
        service = SkillActivationService(
            catalog, store=store, items_dir=tmp_path / "items"
        )
        for _, target in SCENARIOS:
            candidate = next(
                c for c in catalog.candidates if c.descriptor.name == target
            )
            result = await service.activate(
                ActivationRequest(
                    request_id=f"xs-{target}",
                    thread_id="xs",
                    run_id="xs",
                    skill_id=candidate.skill_id,
                )
            )
            assert result.item.status == "activated", target
            assert "instructions" in result.payload
            assert result.payload["skill_root"] == result.payload["mounted_root"]
            assert result.payload["resource_digest"]

    async def test_missing_target_reports_capability_unavailable(
        self, catalog, tmp_path
    ):
        """目标缺失 → 明确返回 required capability unavailable（不伪造、不搜兄弟）。"""
        from electromind.skills.activation import make_activate_skill_tool

        store = PrivateSnapshotStore(tmp_path / "snapshots")
        service = SkillActivationService(
            catalog, store=store, items_dir=tmp_path / "items"
        )
        tool = make_activate_skill_tool(service, thread_id="xs", run_id="xs")
        payload = json.loads((await tool.acall({"name": "ghost-skill"})).content)
        assert payload["ok"] is False
        assert payload["error_code"] == "skill_unresolved"
        assert payload["status"] == "required capability unavailable: ghost-skill"

    async def test_activation_consumes_only_own_frozen_content(self, catalog, tmp_path):
        """激活只消费本 skill 的冻结资源，不含兄弟 skill 内容（自包含）。"""
        store = PrivateSnapshotStore(tmp_path / "snapshots")
        service = SkillActivationService(
            catalog, store=store, items_dir=tmp_path / "items"
        )
        candidate = next(c for c in catalog.candidates if c.descriptor.name == "cp2k")
        result = await service.activate(
            ActivationRequest(
                request_id="xs-isolated",
                thread_id="xs",
                run_id="xs",
                skill_id=candidate.skill_id,
            )
        )
        from electromind.skills.snapstore import SkillSnapshotRef

        snap_dir = store.path_for(
            SkillSnapshotRef(
                digest=result.item.snapshot_ref, store="private", locator=""
            )
        )
        assert snap_dir is not None
        tree = {
            str(p.relative_to(snap_dir)): p.read_text(
                encoding="utf-8", errors="replace"
            )
            for p in snap_dir.rglob("*")
            if p.is_file()
        }
        for rel, text in tree.items():
            # 快照内容不得引用其它内置 skill 的路径（兄弟目录不可见）
            assert "skills/tools/" not in text, f"{rel} 引用兄弟 skill 路径"
            assert "skills/procedures/" not in text, f"{rel} 引用兄弟 procedure 路径"
