#!/usr/bin/env bash
# Mirror push CI: .github/workflows/ruff.yml, coverage.yml, docs.yml
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

step() { printf '\n==> %s\n' "$*"; }

step "uv sync --group dev --extra search --frozen"
uv sync --group dev --extra search --frozen

step "ruff check"
uv run ruff check .

step "ruff format --check"
uv run ruff format --check .

step "pytest + coverage"
uv run pytest tests/ --cov=src --cov-report=xml --cov-report=term -q

step "docs build"
(
  cd docs
  npm ci
  npm run build
)

printf '\n✓ CI checks passed (ruff, pytest, coverage, docs)\n'
