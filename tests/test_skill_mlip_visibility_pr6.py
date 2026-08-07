"""PR-6: MLIP default visibility.

V2 冻结（docs/superpowers/specs/2026-08-07-skill-mlip-refactor.md §7/§9）：
默认 model-visible catalog 收敛为 9 个核心 Skill（tesla-mlp-training +
ai2kit + cp2k + deepmd + lammps + packmol + structure-prep + hpc-submit +
rsess），加上两个 fallback（comp-chem-workflow、vasp）；7 个非核心 Skill
（research-orchestrator / review-response / literature-to-calculation /
report / multiwfn / lobster / vaspkit）通过 frontmatter
`disable-model-invocation: true` 退出模型隐式发现（行为等价 manual_only：
模型不可发现，用户仍可显式调用）。

实现走 runtime 原生机制（scopes.py frontmatter flag → catalog.py
build_model_catalog 跳过），不改 Agent core loop，不引入 config plumbing。
"""

from __future__ import annotations

from pathlib import Path

from electromind.skills.catalog import build_catalog, build_model_catalog
from electromind.skills.scopes import discover_candidate_sources, load_candidates

REPO_ROOT = Path(__file__).resolve().parents[1]

# V2 冻结的默认可见性分档。
CORE_MLIP = {
    "tesla-mlp-training",
    "ai2kit",
    "cp2k",
    "deepmd",
    "lammps",
    "packmol",
    "structure-prep",
    "hpc-submit",
    "rsess",
}
FALLBACK_VISIBLE = {"comp-chem-workflow", "vasp"}
MANUAL_ONLY = {
    "research-orchestrator",
    "review-response",
    "literature-to-calculation",
    "report",
    "multiwfn",
    "lobster",
    "vaspkit",
}
EXPECTED_MODEL_VISIBLE = CORE_MLIP | FALLBACK_VISIBLE


def _trusted_catalog():
    """全信任 catalog：project + builtin 候选都视为 trusted（交互/已授权状态）。"""
    sources = discover_candidate_sources(REPO_ROOT)
    candidates = load_candidates(sources, is_project_trusted=lambda _root: True)
    return build_catalog(candidates, generation=1, cwd=str(REPO_ROOT))


def test_model_visible_set_matches_frozen_plan():
    catalog = _trusted_catalog()
    result = build_model_catalog(catalog, budget=2_000_000)  # 不触发预算裁剪
    actual = {e.name for e in result.entries}
    assert actual == EXPECTED_MODEL_VISIBLE, (
        f"missing={sorted(EXPECTED_MODEL_VISIBLE - actual)} "
        f"unexpected={sorted(actual - EXPECTED_MODEL_VISIBLE)}"
    )


def test_manual_only_skills_still_user_invocable():
    """disable-model-invocation 只挡模型隐式发现，用户显式调用不受影响。"""
    catalog = _trusted_catalog()
    by_name = {c.descriptor.name: c for c in catalog.candidates}
    for name in MANUAL_ONLY:
        cand = by_name[name]
        assert cand.enabled_state in ("on", "name_only", "manual_only"), name
        assert cand.descriptor.disable_model_invocation is True, name


def test_core_skills_fully_model_visible():
    """9 个核心 Skill 保持完整 description 可见（非 name_only 截断）。"""
    catalog = _trusted_catalog()
    result = build_model_catalog(catalog, budget=2_000_000)
    entries = {e.name: e for e in result.entries}
    for name in CORE_MLIP:
        assert name in entries, name
        assert entries[name].description, f"{name} description truncated"


def test_mlp_skill_no_longer_discoverable():
    """PR-1 删除的薄 mlp router 不在模型可见集合中（project 与 builtin 均无残留）。"""
    catalog = _trusted_catalog()
    assert not any(c.descriptor.name == "mlp" for c in catalog.candidates), (
        "stale mlp candidate still present (refresh the builtin bundle?)"
    )
    result = build_model_catalog(catalog, budget=2_000_000)
    assert "mlp" not in {e.name for e in result.entries}
