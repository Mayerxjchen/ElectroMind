#!/usr/bin/env bash
# Local pre-commit gate: ruff + pytest + coverage (mirrors push CI).
# 文档站点已随 docs/ 收敛为 superpowers/ 设计文档仓库而拆除，不再有 docs build 步骤。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

step() { printf '\n==> %s\n' "$*"; }

step "uv sync --group dev --frozen"
uv sync --group dev --frozen

step "ruff check"
uv run ruff check .

step "ruff format --check"
uv run ruff format --check .

# W2 (A+ self-contained skills): 每个 skill 必须自包含（无 collection 依赖、
# 无跨 skill 路径引用、Markdown 引用闭包）。迁移完成前本步骤为红，内容迁移
# 完成后必须保持绿。
step "skill isolation check"
uv run scripts/check-skill-isolation.py

# A+ 验收（v1.0）: 覆盖率门禁 ≥ max(78%, baseline)。COVERAGE_MIN 可覆盖。
# 用 --cov-report=json 生成原始值，显式读 percent_covered（非四舍五入 display）
# 二次门禁；不足即非零退出（`set -e` 保证）。
step "pytest + coverage（>= ${COVERAGE_MIN:-78}%）"
uv run pytest tests/ --cov=src --cov-report=json --cov-report=term -q
COVERAGE_MIN="${COVERAGE_MIN:-78}" uv run python - "$COVERAGE_MIN" <<'PY'
import json
import sys

cov = float(json.load(open("coverage.json"))["totals"]["percent_covered"])
minimum = float(sys.argv[1])
print(f"coverage: {cov:.4f}% (min {minimum}%)")
if cov < minimum:
    raise SystemExit(f"coverage {cov:.4f}% < {minimum}%")
PY

# 发布产物完整性：wheel 与 sdist 都必须含 default-config.toml。
# 构建后端下限已锁 uv_build 0.9.0（0.8.x 的 sdist 收集缺陷：模块目录概率性
# 整体缺失，产物安装直接失败）；此门禁确保该缺陷不复发。release.sh 在发布
# 时以同款门禁把关。
step "产物完整性（wheel + sdist 均含 default-config.toml）"
DIST_CHECK="$(mktemp -d)"
uv build --out-dir "$DIST_CHECK" >/dev/null
python3 - "$DIST_CHECK" <<'PY'
import glob
import sys
import tarfile
import zipfile

dist = sys.argv[1]
wheel = glob.glob(f"{dist}/*.whl")[0]
sdist = glob.glob(f"{dist}/*.tar.gz")[0]
with zipfile.ZipFile(wheel) as zf:
    assert "electromind/resources/default-config.toml" in set(zf.namelist()), (
        f"wheel 缺少默认配置: {wheel}"
    )
with tarfile.open(sdist) as tf:
    assert any(
        name.endswith("src/electromind/resources/default-config.toml")
        for name in tf.getnames()
    ), f"sdist 缺少默认配置（模块目录未收集？）: {sdist}"
print("OK: wheel / sdist 均含 default-config.toml")
PY
rm -rf "$DIST_CHECK"

printf '\n✓ CI checks passed (ruff, pytest, coverage, artifacts)\n'
