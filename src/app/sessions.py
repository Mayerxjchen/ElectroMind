"""Session management: list, find, resume — shared by CLI, REPL, and wire protocol.

A "session" is a user-facing alias for a thread. Threads live under
``{electromind_home}/threads/<thread_id>/``, each containing ``thread.toml``
(config) and ``metainfo.json`` (user-visible metadata).

This module is the single source of truth for session scanning and formatting.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from electromind.ithread import SPEC_FILENAME, ThreadSpec
from electromind.paths import default_electromind_home

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class SessionInfo:
    """Lightweight snapshot of a thread's user-facing metadata."""

    id: str
    title: str = ""
    project_path: str = ""
    project_name: str = ""
    message_count: int = 0
    created_at: str = ""  # ISO datetime
    updated_at: str = ""  # ISO datetime
    backend: str = "local"
    status: str = (
        ""  # 最近一次 Run 状态：completed | cancelled | failed（来自 metainfo）
    )
    deleted: bool = False

    # Filled after parsing
    _raw_meta: dict = field(default_factory=dict, repr=False)


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def _iter_thread_dirs(root: Path) -> list[Path]:
    """Return thread directories (those containing a spec file)."""
    if not root.is_dir():
        return []
    return sorted(
        (
            child
            for child in root.iterdir()
            if child.is_dir() and (child / SPEC_FILENAME).is_file()
        ),
        key=lambda p: p.name,
        reverse=True,
    )


def _load_metainfo(thread_dir: Path) -> dict:
    """Read metainfo.json; return empty dict on any failure.

    P1.3: 主文件损坏 → 尝试 .bak 恢复。
    """
    meta_path = thread_dir / "metainfo.json"
    if not meta_path.is_file():
        return {}
    from electromind.atomicfile import load_json_recover

    loaded = load_json_recover(meta_path, default={})
    return loaded if isinstance(loaded, dict) else {}


def _load_thread_spec(thread_dir: Path) -> ThreadSpec | None:
    """Read thread.toml into a ThreadSpec; return None on failure.

    P1.3: 主文件损坏 → 尝试 .bak 恢复。
    """
    spec_path = thread_dir / SPEC_FILENAME
    if not spec_path.is_file():
        return None
    from electromind.atomicfile import load_toml_recover

    data = load_toml_recover(spec_path)
    if not isinstance(data, dict):
        return None
    try:
        return ThreadSpec.from_dict(data)
    except (OSError, ValueError, TypeError):
        return None


def _is_deleted(meta: dict) -> bool:
    """Check whether metainfo marks the thread as soft-deleted."""
    value = meta.get("deleted_at")
    return isinstance(value, str) and bool(value.strip())


def _relative_time(iso_string: str) -> str:
    """Convert an ISO datetime string to a human-readable relative time (Chinese locale)."""
    if not iso_string:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_string)
    except ValueError:
        return iso_string
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        # Assume local time if no tz info
        delta = now.replace(tzinfo=None) - dt
    else:
        delta = now - dt
    seconds = int(delta.total_seconds())

    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{seconds // 60} 分钟前"
    if seconds < 86400:
        return f"{seconds // 3600} 小时前"
    if seconds < 172800:
        return "昨天"
    if seconds < 604800:
        return f"{seconds // 86400} 天前"
    return dt.strftime("%m 月 %d 日")


def _project_basename(project_path: str) -> str:
    """Extract a short project name from an absolute path."""
    if not project_path:
        return "—"
    p = Path(project_path)
    return p.name or str(p)


def list_sessions(*, home: Path | None = None) -> list[SessionInfo]:
    """List all non-deleted sessions in the electromind home, newest first.

    Args:
        home: Electromind home directory. Defaults to the currently active home
              (``default_electromind_home()``).

    Returns:
        List of SessionInfo, sorted by updated_at (most recent first), then by
        thread id descending for sessions without timestamps.
    """
    root = (home or default_electromind_home()) / "threads"
    sessions: list[SessionInfo] = []

    for thread_dir in _iter_thread_dirs(root):
        meta = _load_metainfo(thread_dir)
        if _is_deleted(meta):
            continue

        spec = _load_thread_spec(thread_dir)

        raw_title = meta.get("title", "")
        title = raw_title if isinstance(raw_title, str) else ""

        project_path = spec.project_path if (spec and spec.project_path) else ""

        sessions.append(
            SessionInfo(
                id=thread_dir.name,
                title=title,
                project_path=project_path,
                project_name=_project_basename(project_path),
                message_count=meta.get("message_count", 0)
                if isinstance(meta.get("message_count"), int)
                else 0,
                created_at=meta.get("created_at", "")
                if isinstance(meta.get("created_at"), str)
                else "",
                updated_at=meta.get("updated_at", "")
                if isinstance(meta.get("updated_at"), str)
                else "",
                backend=spec.backend if spec else "local",
                status=(
                    meta.get("last_run_status")
                    if isinstance(meta.get("last_run_status"), str)
                    else ""
                ),
                _raw_meta=meta,
            )
        )

    # Sort by updated_at descending, then by id descending as fallback
    sessions.sort(key=lambda s: (s.updated_at or "", s.id), reverse=True)
    return sessions


def find_latest_session(project_path: str | None = None) -> SessionInfo | None:
    """Find the most recent session for a given project.

    Args:
        project_path: Absolute project path to match against. If None, uses
                      ``os.getcwd()``. Threads with no project_path set are
                      skipped.

    Returns:
        The most recent SessionInfo, or None if no sessions exist for this project.
    """
    resolved = (
        os.path.abspath(project_path) if project_path else os.path.abspath(os.getcwd())
    )
    sessions = list_sessions()
    matching = [
        s
        for s in sessions
        if s.project_path and os.path.abspath(s.project_path) == resolved
    ]
    return matching[0] if matching else None


def find_session_by_id(thread_id: str) -> SessionInfo | None:
    """Look up a session by its thread id.

    Returns None if not found or the thread is soft-deleted.
    """
    for s in list_sessions():
        if s.id == thread_id:
            return s
    return None


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_session_table(sessions: list[SessionInfo]) -> str:
    """Render a terminal-friendly session table.

    Example output::

          ID         最近更新        标题                  项目         消息
        thread-9    5 分钟前        配置 SSH sandbox       electromind   32
        thread-2    昨天            测试 DeepSeek provider  —             10
    """
    if not sessions:
        return "(no sessions)"

    # Compute column widths
    id_width = max(max(len(s.id) for s in sessions), 2)
    time_width = max(max(len(_relative_time(s.updated_at)) for s in sessions), 6)
    title_width = max(max(len(s.title or "(无标题)") for s in sessions), 4)
    proj_width = max(max(len(s.project_name) for s in sessions), 4)
    status_width = max(max(len(s.status or "—") for s in sessions), 4)
    msg_width = max(max(len(str(s.message_count)) for s in sessions), 4)

    lines = [
        f"  {'ID':<{id_width}}  {'最近更新':<{time_width}}  {'标题':<{title_width}}  {'项目':<{proj_width}}  {'状态':<{status_width}}  {'消息':>{msg_width}}",
    ]

    for s in sessions:
        time_str = _relative_time(s.updated_at)
        title_str = s.title or "(无标题)"
        status_str = s.status or "—"
        lines.append(
            f"  {s.id:<{id_width}}  {time_str:<{time_width}}  {title_str:<{title_width}}  {s.project_name:<{proj_width}}  {status_str:<{status_width}}  {s.message_count:>{msg_width}}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Interactive picker
# ---------------------------------------------------------------------------


def interactive_session_picker(
    sessions: list[SessionInfo],
    *,
    current_id: str | None = None,
) -> str | None:
    """Simple interactive session picker for terminal use.

    Displays sessions with keyboard navigation:
      - ↑/↓ or j/k: move selection
      - Enter: confirm selection
      - d: delete selected session
      - /: enter search/filter mode
      - Esc / q: cancel

    Args:
        sessions: List of sessions to choose from.
        current_id: If set, highlight this session as "current".

    Returns:
        Selected thread_id, or None if cancelled.
    """
    if not sessions:
        print("(no sessions)")
        return None

    idx = 0
    query = ""

    def _filtered() -> list[SessionInfo]:
        if not query:
            return sessions
        q = query.lower()
        return [
            s
            for s in sessions
            if q in s.title.lower() or q in s.project_name.lower() or q in s.id.lower()
        ]

    def _read_key() -> str:
        """Read a single keypress from the terminal (arrow keys, enter, esc, etc.)."""
        import sys
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                # ESC received — read remaining bytes of escape sequence.
                # Set VMIN=0, VTIME=1 (0.1s timeout) so read() returns
                # immediately if no more bytes are available.
                attrs = termios.tcgetattr(fd)
                attrs[6][termios.VMIN] = 0
                attrs[6][termios.VTIME] = 1
                termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
                seq = sys.stdin.read(2)
                if seq == "[A":
                    return "up"
                elif seq == "[B":
                    return "down"
                elif seq == "[C":
                    return "right"
                elif seq == "[D":
                    return "left"
                elif seq == "[H":
                    return "home"
                elif seq == "[F":
                    return "end"
                return "esc"
            elif ch == "\x7f":
                return "backspace"
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    filtered = _filtered()
    if not filtered:
        return None

    try:
        while True:
            filtered = _filtered()
            if not filtered:
                idx = 0
            else:
                idx = max(0, min(idx, len(filtered) - 1))

            # Re-render using newlines (no ANSI escape codes)
            import sys

            sys.stdout.write("\n  === 会话选择器 ===\n")
            if query:
                sys.stdout.write(f"  搜索: {query}\n")
            sys.stdout.write(
                f"  {'最近更新':<10} {'标题':<30} {'项目':<15} {'消息':>6}\n"
            )
            sys.stdout.write(f"  {'-' * 10} {'-' * 30} {'-' * 15} {'-' * 6}\n")

            if not filtered:
                sys.stdout.write("\n  (无匹配会话)\n")
            else:
                clamped = max(0, min(idx, len(filtered) - 1))
                for i, s in enumerate(filtered):
                    marker = ">" if i == clamped else " "
                    current_mark = " *" if s.id == current_id else "  "
                    time_str = _relative_time(s.updated_at)
                    title_str = (s.title or "(无标题)")[:28]
                    proj_str = s.project_name[:13]
                    msg_str = str(s.message_count)
                    sys.stdout.write(
                        f"{marker}{current_mark} {time_str:<10} {title_str:<30} {proj_str:<15} {msg_str:>6}\n"
                    )

            sys.stdout.write("\n  ↑↓ 选择  Enter 恢复  d 删除  / 搜索  Esc 取消\n")
            sys.stdout.flush()

            key = _read_key()

            if key in ("up", "k"):
                idx = max(0, idx - 1)
            elif key in ("down", "j"):
                filtered_now = _filtered()
                if filtered_now:
                    idx = min(idx + 1, len(filtered_now) - 1)
            elif key == "\r" or key == "\n":  # Enter
                filtered_now = _filtered()
                if filtered_now:
                    print(
                        f"\n  已选择: {filtered_now[idx].title or filtered_now[idx].id}"
                    )
                    return filtered_now[idx].id
            elif key.lower() == "d":
                filtered_now = _filtered()
                if filtered_now:
                    target = filtered_now[idx]
                    print(
                        f"\n  确认删除 '{target.title or target.id}'? (y/N): ",
                        end="",
                        flush=True,
                    )
                    confirm = input()
                    if confirm.lower() == "y":
                        from app.wire import soft_delete_thread

                        soft_delete_thread(target.id)
                        sessions[:] = [s for s in sessions if s.id != target.id]
                        idx = min(idx, len(_filtered()) - 1)
            elif key == "/":
                print("\n  搜索: ", end="", flush=True)
                query = input()
                idx = 0
            elif key in ("esc", "q", "\x03"):  # Esc, q, Ctrl-C
                print("\n  已取消")
                return None
    finally:
        # Ensure terminal is restored in case of unexpected exit
        import sys as _sys
        import termios

        try:
            termios.tcflush(_sys.stdin.fileno(), termios.TCIOFLUSH)
        except Exception:
            pass
