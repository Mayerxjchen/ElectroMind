#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="$(node -p "require('./package.json').version")"
PACKAGED="release/pagent Desktop-darwin-arm64/pagent Desktop.app"
STAGE="release/pagent-Desktop-${VERSION}-arm64"
ZIP="release/pagent-Desktop-${VERSION}-arm64.zip"

npm run compile

npx @electron/packager . "pagent Desktop" \
  --platform=darwin \
  --arch=arm64 \
  --out=release \
  --overwrite \
  --icon=assets/icon.icns \
  --app-version="$VERSION"

rm -rf "$STAGE" "$ZIP"
mkdir -p "$STAGE"
cp -R "$PACKAGED" "$STAGE/"
cp scripts/mac-open-hint.txt "$STAGE/打开说明.txt"

# 未购买 Apple 开发者证书时只能 ad-hoc 签名；下载后仍可能需要 xattr -cr 去掉隔离标记。
codesign --force --deep --sign - "$STAGE/pagent Desktop.app"

ditto -c -k --sequesterRsrc --keepParent "$STAGE" "$ZIP"
printf 'wrote %s\n' "$ZIP"
