# Skill Refactor PR-0 Baseline Inventory

日期：2026-08-07（MLIP-first Skill 重构开始前）
分支：desktop-stability-v2 → skills-mlip-refactor（本基线在切分支后、任何 PR 改动前采集）

## Skills（17 个）

procedures/（4）：
- comp-chem-workflow
- literature-to-calculation
- research-orchestrator
- review-response

tools/（13）：
- cp2k
- deepmd
- hpc-submit
- lammps
- lobster
- mlp
- multiwfn
- packmol
- report
- rsess
- structure-prep
- vasp
- vaspkit

## Knowledge sync

- skills/knowledge/sync-map.toml：17 个 `[[references]]` 条目
- skills/knowledge/sync-manifest.json：290 行，entries 覆盖 17 个知识文档 → 各 skill 的 references/knowledge/ 副本（快照见 sync-manifest-snapshot.json）
- `uv run scripts/sync-skill-references.py --check` → check passed（exit 0）
- `uv run scripts/check-skill-isolation.py` → clean (17 skills)（exit 0）

## Catalog

- `electromind skills doctor`：34 candidates, 17 issues，exit 2 —— 17 issues 为 workspace trust 未授权（非交互环境下项目 Skill 被信任门禁挡住），属预期，不代表技能内容问题。candidate 数与 Skill 数一致。

## Tests

- `uv run pytest -q`：1869 passed, 4 skipped, 1 failed, 1 warning，67s
- 唯一失败：tests/test_skill_mount_parity.py::TestMountParity::test_container_mount_parity（容器挂载 parity，与 skill 重构无关的环境性失败）

## 备注

- 本基线后执行：PR-1 remove mlp → PR-2 slim core → PR-3 ai2kit → PR-4 tesla-mlp-training → PR-5 knowledge cleanup → PR-6 visibility → PR-7 TESLA golden-path fixture（V2 冻结顺序，见 docs/superpowers/specs/2026-08-07-skill-mlip-refactor.md §9）。
