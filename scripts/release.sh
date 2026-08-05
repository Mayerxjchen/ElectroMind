#!/usr/bin/env bash
# ElectroMind 发布脚本：构建 wheel/sdist、生成校验和、（可选）GitHub Release。
#
# 用法：
#   scripts/release.sh                 # 构建 + 校验和
#   scripts/release.sh --publish       # 构建 + 校验和 + gh release（需 gh 已认证）
#   scripts/release.sh --tag v0.8.0    # 指定版本 tag（默认读取 pyproject 版本）
#
# 产物：dist/electromind-<version>*.whl / *.tar.gz + SHA256SUMS.txt
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(python3 -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
TAG="${TAG:-v$VERSION}"
PUBLISH=false
for arg in "$@"; do
  case "$arg" in
    --publish) PUBLISH=true ;;
    --tag=*) TAG="${arg#--tag=}" ;;
    *) echo "未知参数: $arg" >&2; exit 2 ;;
  esac
done

# 注意：全角括号紧贴 $VAR 会被 macOS 系统 bash 3.2 吞进变量名，必须用 ${VAR}。
# P0-8 发布门禁：完整 CI + Golden Tasks + 关键模块分支覆盖 + 验收报告。
# 任一失败即中止发布（set -e 保证）。
echo "==> 发布门禁 1/4：完整 CI（ruff + 测试 + 覆盖率 + 产物完整性）"
bash scripts/ci-check.sh

echo "==> 发布门禁 2/4：Golden Tasks（66 项全部通过）"
ELECTROMIND_TEST_CONTAINER_IMAGE="${ELECTROMIND_TEST_CONTAINER_IMAGE:-}" \
  uv run python -m evals run 2>&1 | tail -20 | grep -qE '"passed": 6[0-9]' || {
    echo "Golden Tasks 未全通过，中止发布" >&2
    exit 1
  }

echo "==> 发布门禁 3/4：关键模块纯分支覆盖率 >= 90%"
uv run python - <<'PY'
import json
import subprocess
import sys

subprocess.run(
    [
        sys.executable, "-m", "pytest", "-q", "--no-header",
        "--cov=src/electromind/engine", "--cov=src/electromind/execution",
        "--cov=src/electromind/context", "--cov=src/electromind/artifacts",
        "--cov=src/electromind/core/budget.py", "--cov=src/electromind/core/capabilities.py",
        "--cov=src/electromind/core/retry.py", "--cov=src/electromind/tools/delegate.py",
        "--cov-report=json", "-o", "addopts=",
    ],
    check=True,
    capture_output=True,
    text=True,
    timeout=900,
)
cov = json.load(open("coverage.json"))
targets = [
    "engine/run_engine.py", "execution/plan.py", "execution/permissions.py",
    "execution/idempotency.py", "execution/effects.py", "execution/tool_scheduler.py",
    "execution/intent_log.py", "context/budget.py", "context/compactor.py",
    "context/manager.py", "context/memory.py", "artifacts/manifest.py",
    "artifacts/registry.py", "artifacts/provenance.py",
    "core/budget.py", "core/capabilities.py", "core/retry.py",
    "tools/delegate.py",
]
files = cov["files"]
below = []
total_b = covered_b = 0
for name in targets:
    f = files.get("src/electromind/" + name)
    if f is None:
        below.append((name, 0.0))
        continue
    b_total = len(f["executed_branches"]) + len(f["missing_branches"])
    b_covered = len(f["executed_branches"])
    total_b += b_total
    covered_b += b_covered
    rate = b_covered / b_total * 100 if b_total else 100.0
    if rate < 90.0:
        below.append((name, rate))
overall = covered_b / total_b * 100 if total_b else 0.0
print(f"critical branch coverage: {overall:.2f}%")
if below:
    print(f"below 90%: {below}", file=sys.stderr)
    raise SystemExit(1)
PY

echo "==> 发布门禁 4/4：验收报告存在性"
test -f artifacts/acceptance/m1-m7-runengine/acceptance-report.json || {
  echo "缺少 m1-m7 验收报告，中止发布" >&2
  exit 1
}

echo "==> 构建 ${VERSION}（tag ${TAG}）"
rm -rf dist build
uv build

echo "==> 产物完整性门禁（default-config.toml 必须进两种 archive）"
python3 - <<'PY' dist/*.whl dist/*.tar.gz
import sys
import tarfile
import zipfile

wheel, sdist = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(wheel) as zf:
    names = set(zf.namelist())
    assert "electromind/resources/default-config.toml" in names, (
        f"wheel 缺少默认配置: {wheel}"
    )
with tarfile.open(sdist) as tf:
    names = tf.getnames()
    assert any(
        name.endswith("src/electromind/resources/default-config.toml")
        for name in names
    ), f"sdist 缺少默认配置（模块目录未收集？）: {sdist}"
print("OK: wheel / sdist 均含 default-config.toml")
PY

echo "==> 校验和"
(cd dist && shasum -a 256 *.whl *.tar.gz > SHA256SUMS.txt && cat SHA256SUMS.txt)

if $PUBLISH; then
  echo "==> gh release $TAG"
  gh release create "$TAG" dist/*.whl dist/*.tar.gz dist/SHA256SUMS.txt \
    --title "ElectroMind $VERSION" \
    --generate-notes
  echo "==> 发布完成：https://github.com/Mayerxjchen/ElectroMind/releases/tag/$TAG"
else
  echo "==> 完成（未发布；加 --publish 创建 GitHub Release）"
fi
