"""Extra tools for the pagent ACP agent."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from pagent.defaults import readfile_workspace, resolve_readfile_path
from pagent.tool import ToolOutput, tool

GREP_MAX_MATCHES = 40
GREP_MAX_FILE_BYTES = 512_000
GLOB_MAX_RESULTS = 80


def _workspace_root() -> Path:
    return Path(readfile_workspace())


@tool()
def grep_code(
    pattern: str,
    path: str = ".",
    max_matches: int = 30,
    ignore_case: bool = False,
) -> str:
    """Search for a regex in UTF-8 text files under the workspace.

    Args:
        pattern: Python regex (e.g. ``def main``, ``class Foo``).
        path: File or directory under the workspace (default: whole workspace).
        max_matches: Cap on reported matches (1-40).
        ignore_case: Case-insensitive search when true.
    """
    pat = pattern.strip()
    if not pat:
        return ToolOutput.fail("grep_code error: empty pattern")

    try:
        flags = re.IGNORECASE if ignore_case else 0
        rx = re.compile(pat, flags)
    except re.error as e:
        return ToolOutput.fail(f"grep_code error: invalid regex: {e}")

    resolved, err = resolve_readfile_path(path)
    if err:
        return ToolOutput.fail(err.replace("readfile error:", "grep_code error:", 1))

    root = _workspace_root()
    limit = max(1, min(int(max_matches), GREP_MAX_MATCHES))
    target = Path(resolved)
    files: list[Path]
    if target.is_file():
        files = [target]
    elif target.is_dir():
        files = []
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = [
                d
                for d in dirnames
                if d not in {".git", ".venv", "node_modules", "__pycache__"}
            ]
            for name in filenames:
                files.append(Path(dirpath) / name)
    else:
        return ToolOutput.fail(f"grep_code error: not found: {path}")

    skip_suffixes = {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".zip",
        ".gz",
        ".tar",
        ".wasm",
        ".pyc",
        ".pyo",
        ".pdf",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
    }
    lines_out: list[str] = []
    matches = 0

    for fp in sorted(files):
        if fp.suffix.lower() in skip_suffixes:
            continue
        try:
            if fp.stat().st_size > GREP_MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = fp.relative_to(root)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if not rx.search(line):
                continue
            snippet = line.rstrip()
            if len(snippet) > 200:
                snippet = snippet[:199] + "…"
            lines_out.append(f"{rel}:{lineno}: {snippet}")
            matches += 1
            if matches >= limit:
                break
        if matches >= limit:
            break

    if not lines_out:
        return ToolOutput.succeed("No matches.")
    body = "\n".join(lines_out)
    if matches >= limit:
        body += f"\n… (stopped at {limit} matches)"
    return ToolOutput.succeed(body)


@tool()
def glob_paths(pattern: str, max_results: int = 50) -> str:
    """List files under the workspace matching a glob pattern.

    Args:
        pattern: Glob relative to workspace root (e.g. ``**/*.py``, ``src/**/*.md``).
        max_results: Maximum paths to return (1-80).
    """
    pat = pattern.strip()
    if not pat:
        return ToolOutput.fail("glob_paths error: empty pattern")

    root = _workspace_root()
    limit = max(1, min(int(max_results), GLOB_MAX_RESULTS))
    hits: list[str] = []

    if pat.startswith("**/"):
        iterator = root.rglob(pat[3:])
    else:
        iterator = root.glob(pat)

    for fp in iterator:
        if not fp.is_file():
            continue
        try:
            hits.append(str(fp.relative_to(root)))
        except ValueError:
            continue
        if len(hits) >= limit:
            break

    if not hits and "*" in pat and not pat.startswith("**/"):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d
                for d in dirnames
                if d not in {".git", ".venv", "node_modules", "__pycache__"}
            ]
            rel_dir = Path(dirpath).relative_to(root)
            for name in filenames:
                rel = str(rel_dir / name) if str(rel_dir) != "." else name
                if fnmatch.fnmatch(rel, pat):
                    hits.append(rel)
                    if len(hits) >= limit:
                        break
            if len(hits) >= limit:
                break

    hits = sorted(set(hits))[:limit]
    if not hits:
        return ToolOutput.succeed("No files matched.")
    body = "\n".join(hits)
    if len(hits) >= limit:
        body += f"\n… (stopped at {limit} paths)"
    return ToolOutput.succeed(body)


@tool()
def calc(expression: str) -> str:
    """Evaluate a safe math expression.

    Args:
        expression: Arithmetic using ``+ - * / // % ** ( )`` and numeric literals.
    """
    expr = expression.strip()
    if not expr:
        return ToolOutput.fail("calc error: empty expression")
    if not re.fullmatch(r"[\d\s+\-*/%.()]+", expr):
        return ToolOutput.fail("calc error: only arithmetic expressions are allowed")
    try:
        result = eval(expr, {"__builtins__": {}}, {})  # noqa: S307
    except Exception as e:
        return ToolOutput.fail(f"calc error: {e}")
    return ToolOutput.succeed(str(result))
