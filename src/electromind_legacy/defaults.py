"""Minimal built-in tools (optional)."""

import locale
import os
import re
import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from .tool import ToolOutput, tool

READFILE_MAX_CHARS = 500


def readfile_workspace():
    return os.path.realpath(os.getcwd())


def resolve_readfile_path(path):
    raw = path.strip()
    if not raw:
        return None, "readfile error: empty path"

    raw = os.path.expanduser(os.path.expandvars(raw))
    p = Path(raw)
    root = readfile_workspace()
    if not p.is_absolute():
        p = Path(root) / p
    resolved = os.path.realpath(p)

    try:
        if os.path.commonpath([root, resolved]) != root:
            return None, "readfile error: path outside workspace"
    except ValueError:
        return None, "readfile error: invalid path"

    return resolved, None


def read_utf8_window(path, offset: int, limit: int):
    """Return (text, truncated, error). ``offset`` / ``limit`` are Unicode code points."""
    off = max(0, offset)
    lim = max(1, limit)
    skipped = 0
    out: list[str] = []
    truncated = False

    with open(path, encoding="utf-8", errors="replace") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            for ch in chunk:
                if skipped < off:
                    skipped += 1
                    continue
                if len(out) < lim:
                    out.append(ch)
                else:
                    truncated = True
                    return "".join(out), truncated, None

    text = "".join(out)
    if off > 0 and not text and skipped < off:
        return None, False, f"readfile error: offset {off} past end of file"
    return text, truncated, None


@tool()
def clock(utc: bool = True) -> str:
    """Current time as ISO 8601.

    Args:
        utc: If true, use UTC; otherwise local timezone.
    """
    if utc:
        return datetime.now(UTC).isoformat()
    return datetime.now().isoformat(timespec="seconds")


@tool()
def region() -> str:
    """OS locale / timezone hint (no GPS).

    Typical output: spoken locale from ``locale.getlocale()``,
    preferred encoding, ``TZ`` env if set (Unix), local tz abbreviation.
    """
    now = datetime.now().astimezone()
    tz_abbr = now.strftime("%Z") or "?"
    tz_env = os.environ.get("TZ", "")
    lc = locale.getlocale()
    loc = (lc[0] or "?") if lc else "?"
    enc = (lc[1] or "?") if lc else "?"
    try:
        lc_all = locale.setlocale(locale.LC_ALL)
    except locale.Error:
        lc_all = "?"
    pref_enc = locale.getpreferredencoding(False)
    bits = [
        f"locale={loc}",
        f"encoding={enc}",
        f"preferred_encoding={pref_enc}",
        f"timezone_abbr={tz_abbr}",
        f"LC_ALL={lc_all}",
    ]
    if tz_env:
        bits.append(f"TZ={tz_env}")
    return "; ".join(bits)


@tool(description="Read a UTF-8 text file under the process cwd (workspace).")
def readfile(path: str, max_chars: int = 500, offset: int = 0) -> str:
    """Read a text file from the workspace.

    Args:
        path: Absolute path, or path relative to process ``cwd``. ``~`` and env vars are expanded. Must resolve under ``cwd``.
        max_chars: Maximum code points to return per call (1-500).
        offset: Code-point offset from the start of the file (0 = beginning). Use the next offset from a prior truncated read to continue.
    """
    resolved, err = resolve_readfile_path(path)
    if err:
        return ToolOutput.fail(err)

    limit = max(1, min(int(max_chars), READFILE_MAX_CHARS))
    off = max(0, int(offset))
    if not os.path.isfile(resolved):
        return ToolOutput.fail(f"readfile error: not a file: {path}")

    try:
        data, truncated, err = read_utf8_window(resolved, off, limit)
    except OSError as e:
        return ToolOutput.fail(f"readfile error: {e}")
    if err:
        return ToolOutput.fail(err)

    rel = os.path.relpath(resolved, readfile_workspace())
    end = off + len(data)
    header = f"--- {rel} (offset {off}, {len(data)} chars"
    if truncated:
        header += f", continues at offset {end}"
    header += ") ---\n"
    return ToolOutput.succeed(header + data)


@tool()
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web and return numbered title/link/snippet lines.

    Args:
        query: Search keywords.
        max_results: Maximum number of results (1-10).
    """
    try:
        from ddgs import DDGS
    except ImportError:
        return ToolOutput.fail(
            "web_search error: missing dependency; "
            "install with pip install 'electromind[search]' (or pip install ddgs)"
        )

    q = query.strip()
    if not q:
        return ToolOutput.fail("web_search error: empty query")

    n = max(1, min(int(max_results), 10))
    try:
        rows = list(DDGS().text(q, max_results=n))
    except Exception as e:
        return ToolOutput.fail(f"web_search error: {e}")

    if not rows:
        return ToolOutput.succeed("No results found.")

    lines = []
    for i, row in enumerate(rows, start=1):
        title = str(row.get("title", "")).strip() or "(no title)"
        href = str(row.get("href", row.get("link", ""))).strip()
        body = str(row.get("body", row.get("snippet", ""))).strip()
        lines.append(f"{i}. {title}")
        if href:
            lines.append(f"   {href}")
        if body:
            lines.append(f"   {body}")
    return ToolOutput.succeed("\n".join(lines))


BASH_ALLOWED_COMMANDS = frozenset({"ls"})
BASH_MAX_OUTPUT_CHARS = 8000
BASH_TIMEOUT_SEC = 30
LS_FLAG_CHARS = frozenset("lah1LR@")


def parse_bash_argv(command: str):
    raw = command.strip()
    if not raw:
        return None, "bash error: empty command"
    try:
        parts = shlex.split(raw)
    except ValueError as e:
        return None, f"bash error: {e}"
    if not parts:
        return None, "bash error: empty command"
    if parts[0] not in BASH_ALLOWED_COMMANDS:
        allowed = ", ".join(sorted(BASH_ALLOWED_COMMANDS))
        return None, f"bash error: command not allowed (whitelist: {allowed})"
    return parts, None


def validate_ls_argv(parts: list[str]):
    for arg in parts[1:]:
        if arg == "--":
            return "bash error: unsupported argument '--'"
        if arg.startswith("-"):
            if not re.fullmatch(r"-[a-zA-Z@]+", arg):
                return f"bash error: unsupported flag: {arg}"
            unknown = set(arg[1:]) - LS_FLAG_CHARS
            if unknown:
                return f"bash error: unsupported flag: {arg}"
            continue
        _, err = resolve_readfile_path(arg)
        if err:
            return err.replace("readfile error:", "bash error:", 1)
    return None


@tool(
    description=(
        "Run a whitelisted shell command in the process cwd (workspace). "
        "Currently only `ls` is allowed."
    )
)
def bash(command: str) -> str:
    """List or inspect files via a restricted shell.

    Args:
        command: Shell command string. Only ``ls`` is permitted (e.g. ``ls``, ``ls -la``, ``ls src``).
    """
    parts, err = parse_bash_argv(command)
    if err:
        return ToolOutput.fail(err)

    if parts[0] == "ls":
        err = validate_ls_argv(parts)
        if err:
            return ToolOutput.fail(err)

    workspace = readfile_workspace()
    try:
        completed = subprocess.run(
            parts,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=BASH_TIMEOUT_SEC,
            check=False,
        )
    except OSError as e:
        return ToolOutput.fail(f"bash error: {e}")
    except subprocess.TimeoutExpired:
        return ToolOutput.fail(f"bash error: timed out after {BASH_TIMEOUT_SEC}s")

    out = completed.stdout
    if completed.stderr:
        out = (out + completed.stderr) if out else completed.stderr
    if completed.returncode != 0 and not out.strip():
        return ToolOutput.fail(f"bash error: exit {completed.returncode}")

    truncated = False
    if len(out) > BASH_MAX_OUTPUT_CHARS:
        out = out[:BASH_MAX_OUTPUT_CHARS]
        truncated = True

    if completed.returncode != 0:
        prefix = f"exit {completed.returncode}\n"
        body = prefix + out
        if truncated:
            body += "\n… (output truncated)"
        return ToolOutput.fail(body)

    if truncated:
        out += "\n… (output truncated)"
    return ToolOutput.succeed(out)


DEFAULT_TOOLS = [
    clock,
    region,
]
