"""``electromind config`` 子命令：get | set | unset | edit | path | validate | sources | trust | untrust。

多 scope（CLI-5）：Default（包内默认）→ User ~/.electromind →
Project <root>/.electromind → Local <root>/.electromind/config.local.toml → CLI。
Project 权限规则首次启用前需 Workspace Trust（untrusted → 跳过，fail-closed）。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tomllib

from app.config import (
    RUN_OPTIONS_FIELD_KEYS,
    SETTINGS_FIELD_KEYS,
    find_project_root,
    is_project_trusted,
    load_settings_sources,
    load_toml,
    merge_settings,
    parse_settings,
    trust_project,
    untrust_project,
)
from app.exitcodes import EXIT_CLI, EXIT_OK

# 可安全回显的键；api_key 一律脱敏。
_SECRET_KEYS = ("provider.api_key", "api_key")

SCOPES = ("user", "project", "local")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="electromind config", description="读写、校验与诊断配置（多 scope）"
    )
    parser.add_argument(
        "--scope",
        choices=SCOPES,
        default=None,
        help="目标作用域（set/unset/edit/path 默认 user）",
    )
    sub = parser.add_subparsers(dest="action")
    path_p = sub.add_parser(
        "path", help="打印配置路径（--scope 指定作用域，默认 user）"
    )
    path_p.add_argument("--scope", choices=SCOPES, default=None)
    get = sub.add_parser("get", help="读取生效配置键（点分路径，如 provider.model）")
    get.add_argument("key")
    set_ = sub.add_parser("set", help="写入配置键（默认 user 作用域）")
    set_.add_argument("key")
    set_.add_argument("value")
    set_.add_argument("--scope", choices=SCOPES, default=None)
    unset = sub.add_parser("unset", help="删除配置键（默认 user 作用域）")
    unset.add_argument("key")
    unset.add_argument("--scope", choices=SCOPES, default=None)
    edit = sub.add_parser("edit", help="用 $EDITOR 打开配置文件（默认 user 作用域）")
    edit.add_argument("--scope", choices=SCOPES, default=None)
    sub.add_parser("validate", help="校验所有存在的 scope 文件")
    sub.add_parser("sources", help="打印每个生效键来自哪个作用域")
    sub.add_parser("trust", help="信任当前项目（启用其 Project 配置）")
    sub.add_parser("untrust", help="撤销对当前项目的信任")
    return parser


def run(argv: list[str], *, options=None) -> int:
    args = build_parser().parse_args(argv)
    action = args.action

    if action in (None, "path"):
        return _path(args)
    if action == "get":
        return _get(args.key)
    if action == "set":
        return _set(args)
    if action == "unset":
        return _unset(args)
    if action == "edit":
        return _edit(args)
    if action == "validate":
        return _validate()
    if action == "sources":
        return _sources(options)
    if action == "trust":
        return _trust()
    if action == "untrust":
        return _untrust()
    return EXIT_CLI


def _scope_path(scope: str, *, create_dir: bool = False):
    from electromind.paths import HOME_CONFIG_NAME, LOCAL_CONFIG_NAME, home_config_path

    if scope == "user":
        return home_config_path()
    root = find_project_root()
    if root is None:
        return None
    path = (
        root
        / ".electromind"
        / (LOCAL_CONFIG_NAME if scope == "local" else HOME_CONFIG_NAME)
    )
    if create_dir:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _path(args) -> int:
    if args.scope:
        path = _scope_path(args.scope)
        if path is None:
            print(
                "未找到项目根（当前目录不在 git/.electromind 项目中）", file=sys.stderr
            )
            return EXIT_CLI
        print(path)
        return EXIT_OK
    from electromind.paths import home_config_path

    print(home_config_path())
    return EXIT_OK


def _find_value(data: dict, key: str):
    node = data
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _display_value(key: str, value) -> str:
    if key in _SECRET_KEYS and isinstance(value, str) and value:
        return f"***{value[-4:]}"
    if isinstance(value, str):
        return value
    import json

    return json.dumps(value, ensure_ascii=False)


def _get(key: str) -> int:
    """读取生效值（含作用域来源标注）。"""
    sources = load_settings_sources(
        include_project=is_project_trusted(find_project_root())
    )
    merged, provenance = merge_settings(sources)
    field = _key_to_field(key)
    if field is not None and getattr(merged, field, None) is not None:
        print(_display_value(key, getattr(merged, field)))
        return EXIT_OK
    # 回退：直接查文件栈
    for source in reversed(sources):
        value = _find_value(load_toml(source.path), key)
        if value is not None:
            print(_display_value(key, value))
            return EXIT_OK
    print(f"未找到键: {key}", file=sys.stderr)
    return EXIT_CLI


def _key_to_field(key: str) -> str | None:
    for field, dotted in SETTINGS_FIELD_KEYS.items():
        if dotted == key:
            return field
    return None


def _write_back(path, data: dict) -> None:
    path = os.fspath(path)
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as fp:
        import tomli_w

        tomli_w.dump(data, fp)
    os.replace(tmp, path)


def _coerce(value: str):
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("none", "null"):
        return None
    try:
        return int(value)
    except ValueError:
        pass
    return value


def _target_path(args) -> tuple[str, int]:
    scope = args.scope or "user"
    path = _scope_path(scope, create_dir=True)
    if path is None:
        print("未找到项目根；--scope project/local 需要项目目录", file=sys.stderr)
        return "", EXIT_CLI
    return str(path), EXIT_OK


def _set(args) -> int:
    path, code = _target_path(args)
    if code != EXIT_OK:
        return code
    data = load_toml(path) if os.path.isfile(path) else {}
    parts = args.key.split(".")
    node = data
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = _coerce(args.value)
    try:
        _write_back(path, data)
    except (OSError, ValueError) as exc:
        print(f"写入失败: {exc}", file=sys.stderr)
        return EXIT_CLI
    print(
        f"{args.key} = {_display_value(args.key, node[parts[-1]])}  ({args.scope or 'user'})"
    )
    return EXIT_OK


def _unset(args) -> int:
    path, code = _target_path(args)
    if code != EXIT_OK:
        return code
    if not os.path.isfile(path):
        print(f"配置文件不存在: {path}", file=sys.stderr)
        return EXIT_CLI
    data = load_toml(path)
    parts = args.key.split(".")
    node = data
    for part in parts[:-1]:
        if not isinstance(node.get(part), dict):
            print(f"未找到键: {args.key}", file=sys.stderr)
            return EXIT_CLI
        node = node[part]
    if parts[-1] not in node:
        print(f"未找到键: {args.key}", file=sys.stderr)
        return EXIT_CLI
    del node[parts[-1]]
    _write_back(path, data)
    print(f"已删除: {args.key}  ({args.scope or 'user'})")
    return EXIT_OK


def _edit(args) -> int:
    path = _scope_path(args.scope or "user")
    if path is None or not path.is_file():
        print(f"配置文件不存在: {path}", file=sys.stderr)
        return EXIT_CLI
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vim"
    code = subprocess.call([editor, os.fspath(path)])
    return EXIT_OK if code == 0 else EXIT_CLI


def _validate() -> int:
    """逐个校验每个存在的 scope 文件（坏文件不阻断其他 scope 的校验）。"""
    from electromind.paths import HOME_CONFIG_NAME, LOCAL_CONFIG_NAME, home_config_path

    user_path = home_config_path()
    scopes: list[tuple[str, object]] = [("user", user_path)]
    root = find_project_root()
    if root is not None and root.resolve() != user_path.parent.resolve():
        for scope, name in (
            ("project", HOME_CONFIG_NAME),
            ("local", LOCAL_CONFIG_NAME),
        ):
            path = root / ".electromind" / name
            if path.is_file():
                scopes.append((scope, path))
    problems: list[str] = []
    for scope, path in scopes:
        try:
            parse_settings(load_toml(path))
        except (tomllib.TOMLDecodeError, ValueError) as exc:
            problems.append(f"{scope} ({path}): {exc}")
    if problems:
        for problem in problems:
            print(f"✗ {problem}", file=sys.stderr)
        return EXIT_CLI
    print(f"配置有效（{len(scopes)} 个作用域）")
    return EXIT_OK


def _sources(options) -> int:
    """每个生效键 → 来源作用域（与运行时一致：未信任项目不参与合并）。

    未信任项目的配置文件单独列出为「已跳过」，与 ``load_config`` 的 fail-closed
    语义一致，避免诊断显示的值与实际运行不一致。
    """
    from electromind.paths import (
        HOME_CONFIG_NAME,
        LOCAL_CONFIG_NAME,
        default_electromind_home,
    )

    home = default_electromind_home()
    root = find_project_root()
    trusted = is_project_trusted(root, home)

    sources = load_settings_sources(include_project=trusted)
    merged, provenance = merge_settings(sources)

    rows: list[tuple[str, str]] = []
    for field, dotted in SETTINGS_FIELD_KEYS.items():
        if getattr(merged, field, None) is None:
            continue
        rows.append((dotted, provenance.get(field, "built-in")))
    # CLI 覆盖（同一键只显示一次，CLI 优先）
    if options is not None:
        for field, dotted in RUN_OPTIONS_FIELD_KEYS.items():
            if getattr(options, field, None) not in (None, False, (), ""):
                rows = [(k, sc) for k, sc in rows if k != dotted]
                rows.append((dotted, "cli"))

    if not rows:
        print("(全部为内置默认)")
        return EXIT_OK
    width = max(len(key) for key, _ in rows)
    for key, scope in sorted(rows):
        print(f"{key:<{width}}  {scope}")
    # 未信任项目的配置文件：未参与合并，明确列出（与运行语义一致）。
    if root is not None and not trusted:
        ignored = [
            name
            for name in (HOME_CONFIG_NAME, LOCAL_CONFIG_NAME)
            if (root / ".electromind" / name).is_file()
        ]
        if ignored:
            print(
                f"（项目 {root} 未信任：{', '.join(ignored)} 已跳过，未参与合并；"
                "electromind config trust 启用）",
                file=sys.stderr,
            )
    return EXIT_OK


def _trust() -> int:
    root = find_project_root()
    if root is None:
        print("未找到项目根", file=sys.stderr)
        return EXIT_CLI
    trust_project(root)
    print(f"已信任项目: {root}")
    return EXIT_OK


def _untrust() -> int:
    root = find_project_root()
    if root is None:
        print("未找到项目根", file=sys.stderr)
        return EXIT_CLI
    untrust_project(root)
    print(f"已撤销信任: {root}")
    return EXIT_OK
