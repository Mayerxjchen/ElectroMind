#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="$(node -p "require('./package.json').version")"
OUT="release/pagent Desktop-darwin-arm64/pagent Desktop.app"
ZIP="release/pagent-Desktop-${VERSION}-arm64.zip"

npm run compile

npx @electron/packager . "pagent Desktop" \
  --platform=darwin \
  --arch=arm64 \
  --out=release \
  --overwrite \
  --icon=assets/icon \
  --app-version="$VERSION"

rm -f "$ZIP"
ditto -c -k --sequesterRsrc --keepParent "$OUT" "$ZIP"
printf 'wrote %s\n' "$ZIP"
