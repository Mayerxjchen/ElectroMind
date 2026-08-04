"""``electromind session`` 子命令：list | show ID | delete ID | export ID。

会话 = 用户视角的 thread 别名；数据在 ``{electromind_home}/threads/<id>/``。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from app.exitcodes import EXIT_CLI, EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="electromind session", description="管理会话（线程）"
    )
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("list", help="列出所有历史会话（默认）")
    show = sub.add_parser("show", help="显示单个会话详情")
    show.add_argument("thread_id")
    delete = sub.add_parser("delete", help="软删除会话")
    delete.add_argument("thread_id")
    export = sub.add_parser("export", help="导出会话为 JSON（写入当前目录）")
    export.add_argument("thread_id")
    return parser


def run(argv: list[str]) -> int:
    from app.sessions import find_session_by_id, format_session_table, list_sessions

    args = build_parser().parse_args(argv)
    action = args.action or "list"

    if action == "list":
        print(format_session_table(list_sessions()))
        return EXIT_OK

    session = find_session_by_id(args.thread_id)
    if session is None:
        print(f"会话不存在: {args.thread_id}", file=sys.stderr)
        return EXIT_CLI

    if action == "show":
        print(format_session_detail(session))
        return EXIT_OK
    if action == "delete":
        from app.wire import soft_delete_thread

        soft_delete_thread(session.id)
        print(f"已删除: {session.id}")
        return EXIT_OK
    if action == "export":
        return export_session(session.id)
    return EXIT_CLI


def format_session_detail(session) -> str:
    lines = [
        f"thread_id:  {session.id}",
        f"title:      {session.title or '(无标题)'}",
        f"project:    {session.project_path or '—'}",
        f"backend:    {session.backend}",
        f"messages:   {session.message_count}",
        f"created_at: {session.created_at or '—'}",
        f"updated_at: {session.updated_at or '—'}",
        f"directory:  {_thread_dir(session.id)}",
    ]
    return "\n".join(lines)


def _thread_dir(thread_id: str) -> str:
    from electromind.paths import default_electromind_home

    return str(default_electromind_home() / "threads" / thread_id)


def export_session(thread_id: str) -> int:
    """导出会话：thread.toml + metainfo + 消息列表 → ``{id}.json``（当前目录）。"""
    from electromind.ithread import SPEC_FILENAME
    from electromind.ithread.local import Thread

    thread_dir = _thread_dir(thread_id)
    payload: dict = {"thread_id": thread_id}

    spec_path = os.path.join(thread_dir, SPEC_FILENAME)
    if os.path.isfile(spec_path):
        payload["spec"] = _load_json_text(spec_path, raw=True)

    meta_path = os.path.join(thread_dir, "metainfo.json")
    if os.path.isfile(meta_path):
        payload["metainfo"] = _load_json_text(meta_path)

    try:
        thread = Thread.open(thread_id)
        messages = thread.load_messages()
        payload["messages"] = [
            {"role": message.role, "content": str(message.content)}
            for message in messages.data
        ]
    except Exception as exc:  # 消息读取失败不阻断导出
        payload["messages_error"] = f"{type(exc).__name__}: {exc}"

    target = f"{thread_id}.json"
    with open(target, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    print(
        f"已导出 {len(payload.get('messages', []))} 条消息 → {os.path.abspath(target)}"
    )
    return EXIT_OK


def _load_json_text(path: str, *, raw: bool = False):
    import tomllib

    with open(path, "rb" if raw else "r", encoding=None if raw else "utf-8") as fp:
        return tomllib.load(fp) if raw else json.load(fp)
