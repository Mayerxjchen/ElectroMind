#!/usr/bin/env bash
# A+ self-contained skills 迁移统一验收入口（v1.0 附件第十五节）。
#
# 覆盖全部 MUST 并生成 artifacts/skill-migration/*.json。任一 MUST 失败 →
# 非零退出（不可签署）。环境要求：docker 或 podman（container MUST）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ART=artifacts/skill-migration
mkdir -p "$ART"

step() { printf '\n==> %s\n' "$*"; }
fail() { echo "✗ $*" >&2; exit 1; }

COVERAGE_MIN="${COVERAGE_MIN:-78}"
INSTALL_RESULT=unknown
MOUNT_LOCAL=unknown
MOUNT_SSH=unknown
MOUNT_CONTAINER=unknown

step "uv sync --group dev --frozen"
uv sync --group dev --frozen

step "ruff check + format + git diff --check"
uv run ruff check .
uv run ruff format --check .
git diff --check || fail "git diff --check 失败（空白错误）"

step "SYNC: 知识副本一致性（字节级 + 路径安全）"
uv run scripts/sync-skill-references.py --check || fail "SYNC check failed"

step "ISO: skill 隔离检查（闭包 + placeholder + symlink + 裸 .md）"
uv run scripts/check-skill-isolation.py || fail "isolation check failed"

step "TESTS: 全量 pytest（RuntimeWarning 视为错误）+ 覆盖率门禁（>= ${COVERAGE_MIN}%）"
WARNINGS=0
uv run pytest tests/ --cov=src --cov-report=json --cov-report=term \
  -W error::RuntimeWarning -q 2>&1 | tee /tmp/accept-pytest.log || fail "pytest failed"
PASSED=$(grep -oE "^[0-9]+ passed" /tmp/accept-pytest.log | grep -oE "[0-9]+" | tail -1)
SKIPPED=$(grep -oE "[0-9]+ skipped" /tmp/accept-pytest.log | grep -oE "[0-9]+" | tail -1 || echo 0)
FAILED=$(grep -oE "[0-9]+ failed" /tmp/accept-pytest.log | grep -oE "[0-9]+" | tail -1 || echo 0)
COLLECTED=$((PASSED + SKIPPED + FAILED))
# 读原始浮点值（percent_covered），不用四舍五入的 display —— 77.6469 不得当 78 放行。
COVERAGE=$(COVERAGE_MIN="$COVERAGE_MIN" uv run python - "$COVERAGE_MIN" <<'PY'
import json
import sys

cov = float(json.load(open("coverage.json"))["totals"]["percent_covered"])
minimum = float(sys.argv[1])
print(f"{cov:.4f}")
if cov < minimum:
    raise SystemExit(f"coverage {cov:.4f}% < {minimum}%")
PY
)
[ -n "$PASSED" ] || PASSED=0
echo "TESTS: ${PASSED} passed / ${SKIPPED} skipped / ${FAILED} failed / coverage ${COVERAGE}%"

step "PKG: wheel 无顶层 knowledge/ + 全 skill/resource inventory 核对 + sdist 完整"
DIST_CHECK="$(mktemp -d)"
uv build --out-dir "$DIST_CHECK" >/dev/null
uv run python - "$DIST_CHECK" "$ROOT" <<'PY'
import glob
import hashlib
import sys
import tarfile
import zipfile
from pathlib import Path

dist, repo = sys.argv[1], Path(sys.argv[2])
wheel = glob.glob(f"{dist}/*.whl")[0]
sdist = glob.glob(f"{dist}/*.tar.gz")[0]

with zipfile.ZipFile(wheel) as zf:
    names = zf.namelist()
    data = [n for n in names if ".data/data/" in n]
    assert not any(
        ".data/data/knowledge/" in n or ".data/data/skills/knowledge/" in n
        for n in names
    ), f"wheel 携带顶层 knowledge/: {names}"
    # 全 skill inventory 核对：wheel 中每个 skill 的 SKILL.md + 资源
    # 与源码逐字节一致（排除顶层 knowledge/ 与作者文档）
    checked = 0
    for kind in ("procedures", "tools"):
        base = repo / "skills" / kind
        for skill_dir in sorted(base.iterdir()):
            if not (skill_dir / "SKILL.md").is_file():
                continue
            skill_name = skill_dir.name
            # wheel 散装布局：.data/data/{procedures,tools}/<skill>/...
            prefix_candidates = [
                f".data/data/{kind}/{skill_name}/",
                f".data/data/skills/{kind}/{skill_name}/",
            ]
            prefix = next(
                (p for p in prefix_candidates if any(p in n for n in names)), None
            )
            assert prefix, f"wheel 缺少 skill {skill_name}"
            for src_file in skill_dir.rglob("*"):
                if not src_file.is_file():
                    continue
                if "__pycache__" in src_file.parts or src_file.suffix == ".pyc":
                    continue  # 运行时字节码不进 wheel
                rel = src_file.relative_to(skill_dir).as_posix()
                marker = f"/{kind}/{skill_name}/{rel}"
                member = next((n for n in names if marker in n), None)
                assert member, f"wheel 缺少 {skill_name}/{rel}"
                assert zf.read(member) == src_file.read_bytes(), (
                    f"wheel 内容与源码不一致: {skill_name}/{rel}"
                )
                checked += 1
    assert checked > 0
    print(f"PKG: {checked} 个 skill 文件与源码逐字节一致")

with tarfile.open(sdist) as tf:
    names = tf.getnames()
    assert any(
        n.endswith("skills/knowledge/sync-map.toml") for n in names
    ), "sdist 缺少作者事实源"
print("OK: wheel/sdist 内容符合 A+ 契约")
PY
rm -rf "$DIST_CHECK"

step "INSTALL: 真实 uv tool install 验收（INSTALL-001~010，离线）"
if bash scripts/test-uv-tool-install.sh; then
  INSTALL_RESULT=pass
else
  INSTALL_RESULT=fail
  fail "uv tool install 验收失败"
fi

step "MOUNT: 三后端 parity（loopback SSH 真 sshd；container 用预构建镜像）"
MOUNT_LOCAL=pass
MOUNT_SSH=pass
MOUNT_CONTAINER=pass
if [ -z "${ELECTROMIND_TEST_CONTAINER_IMAGE:-}" ]; then
  MOUNT_CONTAINER=skip
  fail "缺少 ELECTROMIND_TEST_CONTAINER_IMAGE（本地预构建镜像，CI 预加载；测试不自动 pull）"
fi
ELECTROMIND_TEST_CONTAINER_IMAGE="$ELECTROMIND_TEST_CONTAINER_IMAGE" \
  uv run pytest tests/test_skill_mount_parity.py -q \
  || { MOUNT_CONTAINER=fail; MOUNT_SSH=fail; MOUNT_LOCAL=fail; fail "mount parity 失败"; }

step "生成 artifacts/skill-migration/*.json"
uv run python scripts/generate-migration-artifacts.py \
  --collected "$COLLECTED" --passed "$PASSED" --skipped "$SKIPPED" --failed "$FAILED" \
  --coverage "$COVERAGE" --warnings "$WARNINGS" \
  --install-result "$INSTALL_RESULT" \
  --mount-local "$MOUNT_LOCAL" --mount-ssh "$MOUNT_SSH" --mount-container "$MOUNT_CONTAINER"

printf '\n✓ A+ self-contained skills 统一验收通过（coverage >= %s%%）\n' "$COVERAGE_MIN"
