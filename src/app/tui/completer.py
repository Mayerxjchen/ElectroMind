"""Composer 补全：``/`` 命令+Skill、``@`` 项目文件路径。

- ``/`` 在输入开头 → 补全 slash 命令与 Skill 名
- ``@`` 出现在输入中 → 补全 @ 后的项目相对路径（有界深度，跳过隐藏/构建目录）
"""

from __future__ import annotations

import os
from pathlib import Path

from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
}
MAX_WALK_DEPTH = 4


class CliCompleter(Completer):
    def __init__(self, app) -> None:
        self.app = app
        self._project_root: str | None = None

    def get_completions(self, document: Document, complete_event: CompleteEvent):
        text = document.text_before_cursor

        if text.startswith("/"):
            prefix = text[1:]
            for name, summary in self.app.slash_entries:
                if name.startswith(prefix):
                    yield Completion(
                        f"/{name}",
                        start_position=-len(text),
                        display=f"/{name}",
                        display_meta=summary,
                    )
            return

        at = text.rfind("@")
        if at >= 0:
            partial = text[at + 1 :]
            for path in self._complete_paths(partial):
                yield Completion(
                    f"@{path}",
                    start_position=-(len(text) - at),
                    display=f"@{path}",
                )

    def _project_root(self) -> str | None:
        if self._project_root is not None:
            return self._project_root
        runner = self.app.runner
        root = None
        if runner is not None and getattr(runner, "thread", None) is not None:
            project = runner.thread.project_path
            if project:
                root = str(project)
        if root is None:
            root = os.getcwd()
        self._project_root = root
        return root

    def _complete_paths(self, partial: str) -> list[str]:
        root = self._project_root()
        if root is None:
            return []
        return list_project_files(root, partial=partial)


def list_project_files(root: str, *, partial: str = "", limit: int = 40) -> list[str]:
    """项目相对路径列表（跳过隐藏/构建目录；目录带 / 后缀；有界深度）。"""
    base = Path(root)
    parent = (base / partial).parent if partial else base
    prefix = (base / partial).name if partial else ""
    matches: list[str] = []
    depth = len(partial.split("/")) if partial else 0
    if depth > MAX_WALK_DEPTH:
        return []
    try:
        entries = sorted(parent.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        return []
    for entry in entries:
        if entry.name.startswith(".") and entry.name not in (".electromind",):
            continue
        if entry.is_dir() and entry.name in SKIP_DIRS:
            continue
        if entry.name.startswith(prefix):
            rel = str(entry.relative_to(base))
            if entry.is_dir():
                rel += "/"
            matches.append(rel)
    return matches[:limit]
