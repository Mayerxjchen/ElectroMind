#!/usr/bin/env bash
# Print one version section from CHANGELOG.md for GitHub Release body.
# Usage: ./scripts/release-notes.sh 0.7.7
set -euo pipefail

VER="${1#v}"
if [[ -z "$VER" ]]; then
  echo "usage: $0 <version>   e.g. 0.7.7" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHANGELOG="$ROOT/CHANGELOG.md"

if [[ ! -f "$CHANGELOG" ]]; then
  echo "missing $CHANGELOG" >&2
  exit 1
fi

awk -v ver="$VER" '
  $0 ~ "^## " ver " " {
    found = 1
    print "# electromind v" ver
    print ""
    next
  }
  found && /^## / { exit }
  found { print }
' "$CHANGELOG"
