#!/usr/bin/env bash
# ElectroMind standalone binary（PyInstaller）。
#
# 产出 dist/electromind-<version>-<platform> 单文件可执行，无需 Python 环境。
# tiktoken 需要打包其数据文件；prompt_toolkit/asyncssh 为纯 Python，随 bundle。
#
# 用法：
#   scripts/build-standalone.sh            # 当前平台
#   scripts/build-standalone.sh --venv     # 在临时 venv 安装依赖后构建（推荐）
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(python3 -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
PLATFORM=$(python3 -c "import sysconfig;print(sysconfig.get_platform().replace('-','_'))")
OUT="dist/electromind-${VERSION}-${PLATFORM}"

if ! python3 -c "import PyInstaller" 2>/dev/null; then
  echo "缺少 PyInstaller：pip install pyinstaller"
  exit 2
fi

echo "==> 构建 standalone: $OUT"
python3 -m PyInstaller --noconfirm --clean \
  --onefile \
  --name "electromind" \
  --collect-data tiktoken \
  --collect-data electromind \
  --hidden-import app.cli \
  src/app/__main__.py

mkdir -p dist
mv dist/electromind "$OUT" 2>/dev/null || true
chmod +x "$OUT"

echo "==> 冒烟：首次启动能物化默认配置（bundled default-config.toml 可读）"
SMOKE_HOME="$(mktemp -d)"
SMOKE_CONFIG="$SMOKE_HOME/.electromind/config.toml"
# doctor 的退出码受本机环境（缺 Key、docker 等）影响，不能作为冒烟依据；
# 无论成败，最终都以「文件存在且可解析」为准。
set +e
HOME="$SMOKE_HOME" DEEPSEEK_API_KEY=sk-smoke "$OUT" doctor >/dev/null 2>&1
set -e
if [ ! -f "$SMOKE_CONFIG" ]; then
  echo "FAIL: 首次运行未物化 ~/.electromind/config.toml（resources/default-config.toml 未进 bundle？）" >&2
  rm -rf "$SMOKE_HOME"
  exit 1
fi
if ! HOME="$SMOKE_HOME" "$OUT" config validate >/dev/null 2>&1; then
  echo "FAIL: 物化的 config.toml 无法解析" >&2
  rm -rf "$SMOKE_HOME"
  exit 1
fi
rm -rf "$SMOKE_HOME"
echo "==> 冒烟通过"

echo "==> 校验和"
shasum -a 256 "$OUT" | tee dist/SHA256SUMS-standalone.txt
echo "==> 完成：$OUT"
