#!/usr/bin/env bash
# 生成拖拽安装式 .dmg（App + Applications 快捷方式）。
#
# 用法：
#   scripts/build-dmg.sh            # 打包 release/ 下最新 .app
# 产物：release/electromind-Desktop-<version>-arm64.dmg
set -euo pipefail
cd "$(dirname "$0")/.."

APP_NAME="electromind Desktop"
VERSION=$(node -p "require('./editors/desktop/package.json').version")
APP_DIR="editors/desktop/release/electromind-Desktop-${VERSION}-arm64"
APP="$APP_DIR/$APP_NAME.app"
if [ ! -d "$APP" ]; then
  echo "缺少 $APP —— 请先 node editors/desktop/scripts/package.js --agent-bin ..." >&2
  exit 2
fi

VOLNAME="ElectroMind"
OUT="editors/desktop/release/electromind-Desktop-${VERSION}-arm64.dmg"
STAGE="$(mktemp -d)"
RW="$STAGE/electromind-rw.dmg"
trap 'rm -rf "$STAGE"' EXIT

echo "==> 暂存：$STAGE"
mkdir -p "$STAGE/source"
cp -R "$APP" "$STAGE/source/"
ln -s /Applications "$STAGE/source/Applications"

# 卷图标：把 .app 的 icns 放到卷根（Icon\r 命名是 macOS 约定）
ICNS="editors/desktop/assets/icon.icns"
if [ -f "$ICNS" ]; then
  cp "$ICNS" "$STAGE/source/Icon"$'\r'
fi

echo "==> 生成可写 dmg"
hdiutil create -volname "$VOLNAME" -srcfolder "$STAGE/source" \
  -ov -format UDRW "$RW" >/dev/null

echo "==> 挂载并排版"
MOUNT="/Volumes/$VOLNAME"
hdiutil attach "$RW" -mountpoint "$MOUNT" -nobrowse >/dev/null
if command -v SetFile >/dev/null 2>&1; then
  SetFile -a C "$MOUNT" 2>/dev/null || true
fi
# Finder 布局（失败不阻塞——纯功能性 dmg 也可用）
osascript <<EOF 2>/dev/null || true
tell application "Finder"
  tell disk "$VOLNAME"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {100, 100, 560, 420}
    set arrangement of icon view options of container window to not arranged
    set icon size of icon view options of container window to 110
    set text size of icon view options of container window to 13
    set position of item "$APP_NAME.app" of container window to {120, 200}
    set position of item "Applications" of container window to {380, 200}
    close
  end tell
end tell
EOF
sleep 2

echo "==> 卸载并压缩为只读 UDZO"
hdiutil detach "$MOUNT" >/dev/null
hdiutil convert "$RW" -format UDZO -ov -o "$OUT" >/dev/null

echo "==> 完成：$OUT"
hdiutil verify "$OUT" | tail -1
ls -lh "$OUT"
