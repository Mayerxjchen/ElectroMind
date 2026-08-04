"""W2: skill isolation checker + markdown reference closure (A+ design).

Verifies that every skill is self-contained: nothing it ships may depend on
the surrounding collection (``skills/knowledge/``, ``skills/tools/``,
``skills/procedures/``, a mounted ``{skills_root}``, sibling skills, or
absolute user paths), and every local Markdown link it contains must resolve
to a file inside the skill itself (reference closure).

Scan surface per skill:
    SKILL.md
    references/**/*.md        (markdown: links + code spans + prose)
    references/**             (data: path-literal tokens)
    scripts/**/*.py           (AST string literals, f-strings, imports)
    scripts/**/*.sh           (shell tokens, comments stripped)
    examples/**               (markdown or data)

Contexts are checked differently, so prose never false-positives:
    - Markdown links    → resolved against the file location; must stay
                          inside the skill root and exist (closure).
    - Code path literals → ``../`` escapes, ``{skills_root}``, ``file://``,
                          ``/Users/...``, ``/home/...``, and root-relative
                          collection references (``knowledge/``, ``tools/``,
                          ``procedures/``, ``skills/``, ``/skills/``...).
    - Shell args        → same token rules as code path literals.
    - Template vars     → ``{skills_root}`` flagged everywhere.
    - Prose             → only unambiguous patterns ({skills_root},
                          file://, /Users/, /home/, ../).

``../`` escapes are judged against the file's own depth inside the skill:
a token may go up at most to the skill root, never above it.  This keeps
legitimate user-project relative paths (``../00.data/...``, ``../is/CONTCAR``)
clean while still rejecting true escapes.

Usage:
    uv run scripts/check-skill-isolation.py                 # all repo skills
    uv run scripts/check-skill-isolation.py <skill-dir>...  # specific skills
    uv run scripts/check-skill-isolation.py --repo ROOT     # repo override

Exit codes: 0 = clean, 1 = violations found, 2 = usage error.

Design: docs/superpowers/specs/2026-08-04-skill-aplus-self-contained-design.md
"""

from __future__ import annotations

import argparse
import ast
import re
import shlex
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
COLLECTION_ROOTS = ("knowledge/", "tools/", "procedures/", "skills/")
URL_SCHEMES = ("http://", "https://", "mailto:", "ftp://", "sftp://")

INLINE_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
REF_DEF = re.compile(r"^\s*\[([^\]]+)\]:\s*(\S+)")
CODE_SPAN = re.compile(r"`[^`]*`")
SHELL_COMMENT = re.compile(r"(?<![\w:])#.*$")

# Unambiguous patterns flagged even in natural-language prose.
PROSE_PATTERNS = (
    ("{skills_root}", "template variable {skills_root}"),
    ("file://", "file:// URI"),
    ("/Users/", "absolute user path"),
    ("/home/", "absolute user path"),
)

# Braces are meaningful ({skills_root}) and must survive stripping.
TOKEN_STRIP = "[]()'\",;:"


COLLECTION_FRAGMENT = re.compile(
    r"(?<![A-Za-z0-9_/])(?:knowledge|tools|procedures|skills)/"
)

# P1-3: skill-internal root templates.  A token starting with one of these is
# resolved relative to the skill root — so any ``../`` or collection-root
# path AFTER the placeholder escapes the skill.
PLACEHOLDER_PREFIXES = (
    "{repo_root}",
    "{project_root}",
    "{skill_root}",
    "{baseDir}",
    "<skill-root>",
)


def _token_violation(token: str, dir_depth: int) -> str | None:
    """Is *token* an escaping path literal? Returns a message or None."""
    token = token.strip(TOKEN_STRIP)
    if not token or token.startswith(URL_SCHEMES):
        return None
    if "/" not in token and "{" not in token and "<" not in token:
        return None  # not path-like → skip (prose-safe)
    if "{skills_root}" in token:
        return "template variable {skills_root}"
    if "file://" in token:
        return "file:// URI"
    if "/Users/" in token or "/home/" in token:
        return "absolute user path"
    # P1-3: strip root placeholders first — ``{repo_root}/tools/...`` and
    # ``{repo_root}/../scripts/...`` are collection/escape references even
    # though the raw token does not start with a collection root.
    has_placeholder = any(ph in token for ph in PLACEHOLDER_PREFIXES)
    stripped = token
    for ph in PLACEHOLDER_PREFIXES:
        stripped = stripped.replace(ph, "")
    if has_placeholder:
        if "../" in stripped:
            return "escapes the skill root via placeholder"
        if stripped.startswith(
            tuple("/" + r for r in COLLECTION_ROOTS)
        ) or stripped.startswith(COLLECTION_ROOTS):
            return "root-relative collection reference"
        if COLLECTION_FRAGMENT.search(stripped):
            return "root-relative collection reference"
        return None  # placeholder is a legitimate in-skill template
    if token.startswith(tuple("/" + r for r in COLLECTION_ROOTS)) or token.startswith(
        COLLECTION_ROOTS
    ):
        return "root-relative collection reference"
    if COLLECTION_FRAGMENT.search(token):
        return "root-relative collection reference"
    escapes = token.count("../")
    if escapes > dir_depth:
        return f"{escapes}x '../' escapes the skill root"
    return None


# 闭包扩展（复审 P1）: code span 中的裸 `.md` 文件名必须存在于 skill 内。
# 生成物/约定名（expected-*, output-*, generated-*, workflow.md, README.md,
# 同步与任务协议名）跳过 —— 它们是运行时产物或命名约定，不是静态引用。
BARE_MD_SKIP_PREFIXES = (
    "expected",
    "output",
    "generated",
    "workflow",
    "README",
    "sync-",
    "task-",
    "follow-up-",
    "cluster-",
    "response-",
)


def _check_bare_md_reference(
    content: str,
    skill_root: Path,
    rel: Path,
    line: int,
    violations: list[str],
) -> None:
    """A bare ``name.md`` in a code span must exist somewhere in the skill.

    Catches references to deleted repo-root documents (e.g. ``STRUCTURE.md``)
    that survive in examples/references prose.
    """
    for token in shlex.split(content):
        clean = token.strip(TOKEN_STRIP)
        if not clean.endswith(".md") or "/" in clean:
            continue
        if clean.startswith(BARE_MD_SKIP_PREFIXES):
            continue
        if not any(p.name == clean for p in skill_root.rglob("*.md")):
            violations.append(f"{rel}:{line}: missing file reference: {clean}")


def _check_tokens(
    text: str,
    dir_depth: int,
    rel: Path,
    line: int,
    violations: list[str],
) -> None:
    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = text.split()
    for tok in tokens:
        violation = _token_violation(tok, dir_depth)
        if violation:
            violations.append(f"{rel}:{line}: {violation}: {tok}")


def _check_prose(
    text: str, dir_depth: int, rel: Path, line: int, violations: list[str]
) -> None:
    for pattern, message in PROSE_PATTERNS:
        if pattern in text:
            violations.append(f"{rel}:{line}: {message}")
            break
    escapes = text.count("../")
    if escapes > dir_depth:
        violations.append(f"{rel}:{line}: {escapes}x '../' escapes the skill root")


def _check_link(
    dest: str,
    path: Path,
    skill_root: Path,
    rel: Path,
    line: int,
    violations: list[str],
) -> None:
    dest = dest.split('"')[0].strip()
    if not dest or dest.startswith(URL_SCHEMES) or dest.startswith("#"):
        return
    if dest.startswith("/"):
        violations.append(f"{rel}:{line}: absolute path in link: {dest}")
        return
    if any(ch in dest for ch in "*?{"):
        return  # pattern/placeholder link — not a static file reference
    target = (path.parent / dest).resolve()
    root = skill_root.resolve()
    if not target.is_relative_to(root):
        violations.append(f"{rel}:{line}: link escapes the skill root: {dest}")
        return
    if not target.exists():
        violations.append(f"{rel}:{line}: link target not found: {dest}")


# ---------------------------------------------------------------------------
# per-file scanners
# ---------------------------------------------------------------------------


def _scan_markdown(path: Path, skill_root: Path, violations: list[str]) -> None:
    rel = path.relative_to(skill_root)
    dir_depth = len(rel.parts) - 1
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return
    in_fence = False
    for i, line in enumerate(lines, start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            _check_tokens(line, dir_depth, rel, i, violations)
            continue
        for span in CODE_SPAN.finditer(line):
            content = span.group(0)[1:-1]
            _check_tokens(content, dir_depth, rel, i, violations)
            _check_bare_md_reference(content, skill_root, rel, i, violations)
        no_code = CODE_SPAN.sub("", line)
        for m in INLINE_LINK.finditer(no_code):
            _check_link(m.group(1), path, skill_root, rel, i, violations)
        m = REF_DEF.match(no_code)
        if m:
            _check_link(m.group(2), path, skill_root, rel, i, violations)
        prose = INLINE_LINK.sub("", no_code)
        _check_prose(prose, dir_depth, rel, i, violations)


def _docstring_ids(tree: ast.AST) -> set[int]:
    """ids of Constant nodes that are docstrings (prose-in-code)."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
            value = body[0].value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                ids.add(id(value))
    return ids


def _scan_python(path: Path, skill_root: Path, violations: list[str]) -> None:
    rel = path.relative_to(skill_root)
    dir_depth = len(rel.parts) - 1
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return  # not our concern: isolation, not syntax

    def check_string(value: str) -> None:
        """Whole-string + shlex-token checks (embedded collection paths)."""
        whole = _token_violation(value, dir_depth)
        if whole:
            violations.append(f"{rel}:{node.lineno}: {whole}: {value}")
            return
        try:
            tokens = shlex.split(value)
        except ValueError:
            return
        for token in tokens:
            violation = _token_violation(token, dir_depth)
            if violation:
                violations.append(f"{rel}:{node.lineno}: {violation}: {value}")
                return

    docstrings = _docstring_ids(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                check_string(node.value)
        elif isinstance(node, ast.JoinedStr):
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    check_string(value.value)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] + "/" in COLLECTION_ROOTS:
                    violations.append(
                        f"{rel}:{node.lineno}: import crosses the skill "
                        f"boundary: {alias.name}"
                    )
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module.split(".")[0] + "/" in COLLECTION_ROOTS:
                violations.append(
                    f"{rel}:{node.lineno}: import crosses the skill "
                    f"boundary: {node.module}"
                )


def _scan_shell(path: Path, skill_root: Path, violations: list[str]) -> None:
    rel = path.relative_to(skill_root)
    dir_depth = len(rel.parts) - 1
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return
    for i, line in enumerate(lines, start=1):
        code = SHELL_COMMENT.sub("", line)
        _check_tokens(code, dir_depth, rel, i, violations)


def _scan_data(path: Path, skill_root: Path, violations: list[str]) -> None:
    rel = path.relative_to(skill_root)
    dir_depth = len(rel.parts) - 1
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return
    for i, line in enumerate(lines, start=1):
        _check_tokens(line, dir_depth, rel, i, violations)


def _text_or_none(path: Path) -> list[str] | None:
    raw = path.read_bytes()
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None


def _scan_files(path: Path, skill_root: Path, violations: list[str]) -> None:
    if path.suffix == ".md":
        _scan_markdown(path, skill_root, violations)
    elif path.suffix == ".py":
        _scan_python(path, skill_root, violations)
    elif path.suffix == ".sh":
        _scan_shell(path, skill_root, violations)
    else:
        _scan_data(path, skill_root, violations)


def _walk_scan_files(skill_dir: Path) -> list[Path]:
    files: list[Path] = []
    for base in (
        skill_dir / "SKILL.md",
        skill_dir / "references",
        skill_dir / "scripts",
        skill_dir / "examples",
    ):
        if base.is_file():
            files.append(base)
        elif base.is_dir():
            for p in base.rglob("*"):
                if p.is_file() and not any(
                    part.startswith(".") or part == "__pycache__"
                    for part in p.relative_to(base).parts
                ):
                    files.append(p)
    return files


# ---------------------------------------------------------------------------
# skill / repo entry points
# ---------------------------------------------------------------------------


def _frontmatter_name(skill_md: Path) -> str | None:
    """Extract the ``name:`` value from SKILL.md frontmatter (quotes stripped)."""
    try:
        text = skill_md.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    for line in text[4:end].splitlines():
        if line.startswith("name:"):
            value = line.split(":", 1)[1].strip().strip("'\"")
            return value or None
    return None


def scan_skill(skill_dir: Path) -> list[str]:
    """Return isolation violations for one skill (relative file:line messages)."""
    if not skill_dir.is_dir():
        return [f"{skill_dir}: skill directory not found"]
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return [f"missing SKILL.md in {skill_dir}"]
    violations: list[str] = []
    # A+ W3: directory name must equal the frontmatter `name` (hard error).
    frontmatter_name = _frontmatter_name(skill_md)
    if frontmatter_name and frontmatter_name != skill_dir.name:
        violations.append(
            "SKILL.md: frontmatter name "
            f"{frontmatter_name!r} does not match directory {skill_dir.name!r}"
        )
    # P1-3: reject symlinks anywhere in the skill tree (escape vector).
    for path in skill_dir.rglob("*"):
        if path.is_symlink():
            rel = path.relative_to(skill_dir)
            violations.append(f"symlink not allowed in skill tree: {rel}")
    for path in _walk_scan_files(skill_dir):
        if _text_or_none(path) is None:
            continue  # binary / undecodable
        _scan_files(path, skill_dir, violations)
    return violations


def find_skill_dirs(repo_root: Path) -> list[Path]:
    """All flat skill dirs under <root>/skills/{procedures,tools} (A+ roots)."""
    dirs: list[Path] = []
    for kind in ("procedures", "tools"):
        base = repo_root / "skills" / kind
        if not base.is_dir():
            continue
        for skill_dir in sorted(base.iterdir()):
            if (skill_dir / "SKILL.md").is_file():
                dirs.append(skill_dir)
    return dirs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check-skill-isolation",
        description=(
            "Check that every skill is self-contained and its markdown "
            "references close inside the skill (A+ self-contained skills)."
        ),
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="repo root (default: parent of scripts/)",
    )
    parser.add_argument(
        "skills",
        nargs="*",
        type=Path,
        help="skill dirs to check (default: all under <repo>/skills/)",
    )
    args = parser.parse_args(argv)

    repo = (args.repo or SCRIPT_DIR.parent).resolve()
    skill_dirs = [s for s in args.skills] or find_skill_dirs(repo)
    if not skill_dirs:
        print("check-skill-isolation: no skills found", file=sys.stderr)
        return 1

    total = 0
    for skill_dir in skill_dirs:
        name = skill_dir.name
        for violation in scan_skill(skill_dir):
            print(f"{name}: {violation}")
            total += 1
    if total:
        print(
            f"check-skill-isolation: {total} violation(s) across "
            f"{len(skill_dirs)} skill(s)",
            file=sys.stderr,
        )
        return 1
    print(f"check-skill-isolation: clean ({len(skill_dirs)} skills)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
