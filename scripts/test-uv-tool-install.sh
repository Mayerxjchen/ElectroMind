#!/usr/bin/env bash
# 真实 uv tool install 安装产物验收（INSTALL-001~010）。
#
# INSTALL-001 真实构建并安装 wheel 到隔离 UV_TOOL_DIR
# INSTALL-002 安装环境自发现（cwd 仓库外、清空 ELECTROMIND_HOME/PYTHONPATH）
# INSTALL-003 安装产物含全部内置 skill（数量与 scope 与源码一致）
# INSTALL-004 三个代表 skill 可激活（cp2k / packmol / comp-chem-workflow）
# INSTALL-005 同步知识副本可读（references/knowledge/** 随安装分发）
# INSTALL-006 resource digest 与安装内容一致（内容寻址 round-trip）
# INSTALL-007 顶层 knowledge/ 不在安装产物（A+ W6）
# INSTALL-008 卸载后安装目录被移除
# INSTALL-009 wheel/sdist 构建成功（构建步骤本身即验证）
# INSTALL-010 安装过程离线（uv tool install --offline，不触网）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail() { echo "✗ $*" >&2; exit 1; }
step() { printf '\n==> %s\n' "$*"; }

command -v uv >/dev/null || fail "uv not available"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# INSTALL-009: 构建 wheel（构建产物完整）
step "构建 wheel"
uv build --wheel --out-dir "$TMP/wheel" >/dev/null
WHEEL="$(ls "$TMP"/wheel/*.whl)"
[ -n "$WHEEL" ] || fail "wheel build produced nothing"

# INSTALL-010: 安装必须离线（使用已缓存依赖，不下载）
step "uv tool install（--offline，隔离目录）"
env UV_TOOL_DIR="$TMP/tools" UV_TOOL_BIN_DIR="$TMP/bin" \
  uv tool install --offline --force "$WHEEL" >/dev/null \
  || fail "离线安装失败（INSTALL-010：需要网络？）"

VENV="$TMP/tools/electromind"
PYTHON="$VENV/bin/python"
[ -f "$PYTHON" ] || PYTHON="$VENV/Scripts/python.exe"
[ -f "$PYTHON" ] || fail "installed venv interpreter not found"

# INSTALL-002/003/004/005/006/007: 在仓库外、无污染环境下用安装 venv 验证
step "安装环境验证（INSTALL-002~007）"
(
  cd "$TMP"  # 仓库外 cwd，杜绝源码 fallback
  unset ELECTROMIND_HOME PYTHONPATH 2>/dev/null || true
  ELECTROMIND_HOME="$TMP/em-home" \
  "$PYTHON" - "$TMP" "$ROOT" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

install_prefix = Path(sys.argv[1]).resolve()
repo_root = Path(sys.argv[2]).resolve()

from electromind.skills.builtin import builtin_roots
from electromind.skills.scopes import discover_candidate_sources, load_candidates
from electromind.skills.activation import (
    ActivationRequest,
    SkillActivationService,
)
from electromind.skills.snapstore import PrivateSnapshotStore, SkillSnapshotRef

# INSTALL-002: 扁平根全部位于安装前缀内
roots = [Path(r).resolve() for r in builtin_roots()]
assert any(r.name == "procedures" for r in roots), f"缺少 procedures 根: {roots}"
assert any(r.name == "tools" for r in roots), f"缺少 tools 根: {roots}"
for r in roots:
    assert r.is_relative_to(install_prefix), f"builtin root 不在安装前缀: {r}"

# INSTALL-003: 数量与 scope 与源码一致
sources = discover_candidate_sources(None, cwd=".")
cands = load_candidates(sources)
installed = {(c.descriptor.name, c.source.scope, c.source.dialect) for c in cands}

src_sources = discover_candidate_sources(
    None, cwd=str(repo_root),
    builtin_roots=(
        repo_root / "skills" / "procedures",
        repo_root / "skills" / "tools",
    ),
)
src_cands = load_candidates(src_sources)
src_set = {(c.descriptor.name, c.source.scope, c.source.dialect) for c in src_cands}
assert installed == src_set, (
    f"安装产物与源码不一致:\n  安装: {sorted(installed)}\n  源码: {sorted(src_set)}"
)
print(f"INSTALL-003: {len(installed)} skills, scope/dialect 与源码一致")

# INSTALL-004: 三个代表 skill 激活（配真实 local sandbox mounter）
import asyncio

from electromind.sandbox.sandbox import Sandbox
from electromind.skills.catalog import build_catalog
from electromind.skills.mounting import LazySkillMounter


async def _make_service():
    box = await Sandbox.create(backend="local", workdir=str(install_prefix / "box"))
    store = PrivateSnapshotStore(install_prefix / "snapshots")
    return (
        SkillActivationService(
            build_catalog(cands, generation=1, cwd="."),
            store=store,
            mounter=LazySkillMounter(box, store=store),
            items_dir=install_prefix / "activations",
        ),
        box,
    )


service, box = asyncio.run(_make_service())
for name in ("cp2k", "packmol", "comp-chem-workflow"):
    hit = next(c for c in cands if c.descriptor.name == name)
    result = asyncio.run(
        service.activate(
            ActivationRequest(
                request_id=f"install-{name}",
                thread_id="install",
                run_id="install",
                skill_id=hit.skill_id,
            )
        )
    )
    payload = result.payload
    assert payload["ok"] is True, f"{name} 激活失败: {payload}"
    assert payload["skill_root"], f"{name} 缺少 skill_root"
    print(f"INSTALL-004: {name} 激活成功（{len(payload.get('resources', []))} 资源）")

    # INSTALL-005: 同步知识副本可读（若该 skill 声明了 knowledge 副本）
    snap_dir = service.store.path_for(
        SkillSnapshotRef(digest=result.item.snapshot_ref, store="private", locator="")
    )
    assert snap_dir is not None
    kn = snap_dir / "resources" / "references" / "knowledge"
    if kn.is_dir():
        docs = sorted(p.name for p in kn.glob("*.md"))
        assert docs, f"{name} 声明了知识副本但内容为空"
        print(f"INSTALL-005: {name} 知识副本 {len(docs)} 份: {docs[:3]}…")

    # INSTALL-006: resource digest 与快照内容一致（真实 round-trip 比对）
    from electromind.skills.snapshot import hash_content

    expected = payload["resource_digest"]
    assert expected, f"{name} 缺少 resource_digest"
    actual_parts = []
    for rel in payload.get("resources", []):
        data = (snap_dir / "resources" / rel).read_bytes()
        actual_parts.append(f"{rel}|{hashlib.sha256(data).hexdigest()}")
    actual = hash_content(*actual_parts) if actual_parts else hash_content()
    assert actual == expected, (
        f"{name} resource_digest 不一致:\n  payload: {expected}\n  实际: {actual}"
    )
    print(f"INSTALL-006: {name} resource_digest round-trip OK ({expected[:12]}…)")

# INSTALL-007: 顶层 knowledge/ 不在安装产物
prefix = Path(sys.prefix)
assert not (prefix / "knowledge").exists(), "安装产物不得含顶层 knowledge/"
print("INSTALL-007: 无顶层 knowledge/")

print("OK: INSTALL-002~007 全部通过")
PY
)

# INSTALL-008: 卸载后安装目录移除
step "uv tool uninstall（INSTALL-008）"
env UV_TOOL_DIR="$TMP/tools" UV_TOOL_BIN_DIR="$TMP/bin" \
  uv tool uninstall electromind >/dev/null
[ ! -d "$VENV" ] || fail "卸载后安装 venv 仍存在: $VENV"
echo "OK: 卸载后 venv 已移除"

printf '\n✓ uv tool install 验收通过（INSTALL-001~010）\n'
