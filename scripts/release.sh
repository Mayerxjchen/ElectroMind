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
