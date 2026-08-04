"""``electromind skills`` 子命令：list | show NAME | validate [NAME] | paths | reload | doctor。

复用 electromind.skills 的发现/校验能力；不打开 Runner。

SKILL-6 起 list/show 走共享 ``SkillCatalogService``（CLI/Desktop/Service 同一
Catalog Generation）；旧默认输出格式不变。新增 flags：

- ``list --all``      展示全部候选（含 shadowed/disabled/untrusted/manual-only）
- ``list --qualified``按 qualified id 展示
- ``list --source``   显示 scope/dialect 来源
- ``list --status``   显示 enabled/trust 状态
- ``list --json``     JSON 输出
- ``paths``           列出发现的 source roots
- ``reload``          重新发现并打印新 generation
- ``doctor``          校验全部候选并给出诊断摘要
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from app.exitcodes import EXIT_CLI, EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="electromind skills", description="列出、查看与校验 Skills"
    )
    sub = parser.add_subparsers(dest="action")

    list_p = sub.add_parser("list", help="列出发现到的全部 Skills（含来源）")
    list_p.add_argument(
        "--all", action="store_true", help="展示全部候选（含遮蔽/禁用/未信任）"
    )
    list_p.add_argument("--qualified", action="store_true", help="按 qualified id 展示")
    list_p.add_argument("--source", action="store_true", help="显示 scope/dialect 来源")
    list_p.add_argument("--status", action="store_true", help="显示 enabled/trust 状态")
    list_p.add_argument("--json", action="store_true", help="JSON 输出")

    show = sub.add_parser("show", help="显示单个 Skill 的元数据与说明")
    show.add_argument("name")

    validate = sub.add_parser("validate", help="校验 Skill 目录结构（全部或指定）")
    validate.add_argument("name", nargs="?", default=None)

    sub.add_parser("paths", help="列出发现的 source roots")
    sub.add_parser("reload", help="重新发现并打印新 generation")
    sub.add_parser("doctor", help="校验全部候选并给出诊断摘要")

    install = sub.add_parser("install", help="安装 Skill（用户显式调用，模型不可触发）")
    install_src = install.add_mutually_exclusive_group(required=True)
    install_src.add_argument("--dir", help="本地 skill 目录")
    install_src.add_argument("--archive", help="zip/tar 归档")
    install_src.add_argument("--git", help="git 仓库 URL/路径")
    install.add_argument("--ref", default="HEAD", help="git ref（默认 HEAD）")

    uninstall = sub.add_parser("uninstall", help="卸载已安装的 Skill")
    uninstall.add_argument("name")

    sub.add_parser("installed", help="列出已安装 Skill 及其来源记录")
    return parser


def run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    action = args.action or "list"

    if action == "list":
        return _list(args)
    if action == "show":
        return _show(args.name)
    if action == "validate":
        return _validate(args.name)
    if action == "paths":
        return _paths()
    if action == "reload":
        return _reload()
    if action == "doctor":
        return _doctor()
    if action == "install":
        return _install(args)
    if action == "uninstall":
        return _uninstall(args.name)
    if action == "installed":
        return _installed()
    return EXIT_CLI


def _catalog():
    """Legacy catalog (default output format unchanged)."""
    from electromind.skills import discover_skill_sources, load_skill_catalog

    return load_skill_catalog(discover_skill_sources(os.getcwd(), configured_roots=()))


def _shared_catalog():
    """Shared candidate catalog via the process-wide service (SKILL-6).

    Uses the process-wide singleton (``get_shared_catalog_service``) so CLI,
    Desktop, and the HTTP service read from ONE catalog instance — the RFC
    section 六 completion condition.  The service is configured with the
    current working directory and the existing Workspace Trust evaluator.
    """
    return _catalog_service().list()


def _list(args) -> int:
    if args.json:
        return _list_json(args)
    catalog = _shared_catalog()
    candidates = list(catalog.candidates)

    if args.all:
        shown = candidates
    else:
        # Default: only model-visible top candidates (name-unique, on/name_only)
        from electromind.skills.catalog import build_model_catalog

        budget = build_model_catalog(catalog)
        top_ids = {e.skill_id for e in budget.entries}
        shown = [c for c in candidates if c.skill_id in top_ids]

    if not shown:
        print("(no skills discovered)")
        return EXIT_OK

    for c in shown:
        name = c.descriptor.name
        if args.qualified:
            name = c.skill_id
        line = f"  {name}: {c.descriptor.description}"
        if args.source:
            line += f" [{c.source.scope}/{c.source.dialect}]"
        if args.status:
            line += f" ({c.enabled_state}/{c.trust_state})"
        print(line)
    return EXIT_OK


def _list_json(args) -> int:
    import json as _json

    catalog = _shared_catalog()
    print(
        _json.dumps(
            {
                "generation": catalog.generation,
                "catalog_digest": catalog.catalog_digest,
                "candidates": [
                    {
                        "skill_id": c.skill_id,
                        "name": c.descriptor.name,
                        "description": c.descriptor.description,
                        "scope": c.source.scope,
                        "dialect": c.source.dialect,
                        "enabled_state": c.enabled_state,
                        "trust_state": c.trust_state,
                        "content_digest": c.descriptor.content_digest,
                    }
                    for c in catalog.candidates
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return EXIT_OK


def _show(name: str) -> int:

    service = _catalog_service()
    catalog = service.list()
    # Prefer exact qualified id; fall back to any candidate by name.
    # `show` is a diagnostics surface — untrusted candidates may be viewed
    # (RFC section 五: 允许查看 SKILL.md), so no trust gate here.
    candidate = catalog.by_qualified_id().get(name)
    if candidate is None:
        by_name = catalog.by_name().get(name)
        candidate = by_name[0] if by_name else None
    if candidate is None:
        print(f"未找到 Skill: {name}", file=sys.stderr)
        return EXIT_CLI
    print(f"name:        {candidate.descriptor.name}")
    print(f"skill_id:    {candidate.skill_id}")
    print(f"description: {candidate.descriptor.description}")
    print(f"source:      {candidate.source.source_id}")
    print(f"scope:       {candidate.source.scope}")
    print(f"dialect:     {candidate.source.dialect}")
    print(f"root:        {candidate.descriptor.root_path}")
    print(f"sha256:      {candidate.descriptor.content_digest}")
    print("---")
    try:
        from electromind.skills.skill import parse_skill_md

        md = candidate.descriptor.entry_path
        if md.is_file():
            _fm, body = parse_skill_md(md.read_text(encoding="utf-8"))
            print(body.strip())
    except OSError:
        pass
    return EXIT_OK


def _validate(name: str | None) -> int:
    from electromind.skills import validate_skill_name

    catalog = _catalog()
    problems: list[str] = []
    for diagnostic in catalog.diagnostics:
        if diagnostic.severity == "error" and (
            name is None or diagnostic.path and name in str(diagnostic.path)
        ):
            problems.append(str(diagnostic))
    if name is not None:
        error = validate_skill_name(name)
        if error:
            problems.append(f"{name}: {error}")
        elif catalog.registry.get(name) is None:
            problems.append(f"{name}: 未发现该 Skill")
    for problem in problems:
        print(f"✗ {problem}", file=sys.stderr)
    if problems:
        return EXIT_CLI
    target = name or "全部 Skill"
    print(f"{target} 校验通过")
    return EXIT_OK


def _paths() -> int:
    """List discovered source roots (unique, sorted)."""
    service = _catalog_service()
    sources = service.sources()
    if not sources:
        print("(no skill sources)")
        return EXIT_OK
    for src in sources:
        print(f"  {src.scope}/{src.dialect}  {src.root}")
    return EXIT_OK


def _catalog_service():
    """The process-wide shared catalog service (SKILL-6).

    Returns the singleton so CLI commands share one catalog instance with
    Desktop and the HTTP service.  The singleton is configured once with the
    current working directory and the existing Workspace Trust evaluator;
    reconfiguration is a no-op when the cwd is unchanged.
    """
    from app.config import find_project_root, is_project_trusted
    from electromind.skills.catalog_service import (
        SkillCatalogService,
        get_shared_catalog_service,
        set_shared_catalog_service,
    )

    service = get_shared_catalog_service()
    cwd = os.getcwd()
    # 进程级单例：cwd 变化 或 仍是未配置的默认单例时重建。注入的实例
    # （无 _unconfigured_default 标记）原样复用 —— 同一进程内 CLI/Desktop/
    # Service 共享同一 catalog 实例（RFC 第 14 项）。
    if service.cwd != Path(cwd).resolve() or getattr(
        service, "_unconfigured_default", False
    ):
        configured = SkillCatalogService(
            project_path=cwd,
            cwd=cwd,
            is_project_trusted=lambda project_root: is_project_trusted(
                project_root or find_project_root(cwd)
            ),
        )
        set_shared_catalog_service(configured)
        service = configured
    return service


def _reload() -> int:
    """Re-discover and print the new generation."""
    service = _catalog_service()
    catalog = service.reload()
    print(f"generation: {catalog.generation}")
    print(f"candidates: {len(catalog.candidates)}")
    print(f"digest:     {catalog.catalog_digest}")
    return EXIT_OK


def _doctor() -> int:
    """Validate every candidate and summarize diagnostics."""
    service = _catalog_service()
    catalog = service.list()
    problems = 0
    for c in catalog.candidates:
        if c.trust_state == "untrusted":
            problems += 1
            print(f"✗ {c.skill_id}: untrusted workspace", file=sys.stderr)
        if c.enabled_state == "off":
            problems += 1
            print(f"✗ {c.skill_id}: disabled", file=sys.stderr)
    print(
        f"{len(catalog.candidates)} candidates, {problems} issues, "
        f"generation {catalog.generation}"
    )
    return EXIT_CLI if problems else EXIT_OK


def _installer():
    from electromind.skills.installer import SkillInstaller

    return SkillInstaller()


def _install(args) -> int:
    """SKILL-9: 用户显式安装 Skill（模型不可触发 — CLI-only）。"""
    import asyncio

    from electromind.skills.installer import InstallError

    installer = _installer()
    try:
        if args.dir:
            result = asyncio.run(installer.install_from_dir(Path(args.dir)))
        elif args.archive:
            result = asyncio.run(installer.install_from_archive(Path(args.archive)))
        else:
            result = asyncio.run(installer.install_from_git(args.git, ref=args.ref))
    except InstallError as exc:
        print(f"✗ 安装失败: {exc}", file=sys.stderr)
        return EXIT_CLI

    verb = "更新" if result.updated else "安装"
    print(f"✓ {verb} {result.name} → {result.target}")
    print(f"  来源: {result.record.source}")
    print(f"  摘要: {result.record.digest[:12]}…")
    return EXIT_OK


def _uninstall(name: str) -> int:
    """SKILL-9: 卸载已安装 Skill。"""
    import asyncio

    removed = asyncio.run(_installer().uninstall(name))
    if not removed:
        print(f"未找到已安装的 Skill: {name}", file=sys.stderr)
        return EXIT_CLI
    print(f"✓ 已卸载 {name}")
    return EXIT_OK


def _installed() -> int:
    """列出已安装 Skill 及其来源记录。"""
    records = _installer().installed()
    if not records:
        print("(no installed skills)")
        return EXIT_OK
    for record in records:
        print(
            f"  {record.name}: {record.source_type} · {record.source} · "
            f"{record.digest[:12]}…"
        )
    return EXIT_OK
