"""SKILL-8: built-in scientific skill delivery.

The repo's AICC bundle lives at ``<repo>/skills/`` (procedures/ + tools/ +
knowledge/ + AGENTS.md).  For installed artifacts (wheel, ``uv tool``,
Desktop bundle) the same bundle must be discoverable WITHOUT the repo source.

Delivery paths, in probe order:

1. ``<sys.prefix>/skills`` — installed by ``[tool.uv.build-backend.data]``
   (``data = "skills"`` in pyproject.toml) into the virtualenv root.
2. ``electromind/skills_data`` — package-internal mirror (bundle scripts /
   PyInstaller ``--collect-data``).
3. ``<repo-root>/skills`` — source-tree fallback during development.

The discovery scope is ``builtin``: read-only, dialect ``builtin``, trusted
by default (RFC section 五).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Fixed subdirectories of a builtin root that contain skills.
BUILTIN_SKILL_DIRS = ("procedures", "tools")
# Never treated as skills inside a builtin root.
BUILTIN_SKIP_DIRS = ("knowledge",)


def _is_bundle_dir(root: Path) -> bool:
    """Whether *root* is a builtin bundle (AGENTS.md + procedures/ + tools/).

    Also accepts the venv-root layout produced by uv_build's ``data`` scheme,
    where the bundle *contents* are installed directly at ``<sys.prefix>``
    (``<sys.prefix>/AGENTS.md``, ``<sys.prefix>/procedures/``, …).
    """
    return (
        (root / "AGENTS.md").is_file()
        and (root / "procedures").is_dir()
        and (root / "tools").is_dir()
    )


def _candidate_builtin_roots() -> list[Path]:
    """Ordered candidate roots (existence-checked by the caller)."""
    roots: list[Path] = []

    # 1. installed data directory — `<sys.prefix>/skills` (explicit subdir)
    roots.append(Path(sys.prefix) / "skills")

    # 2. venv-root layout — uv_build `data = "skills"` installs the bundle
    #    contents directly at `<sys.prefix>` (AGENTS.md, procedures/, tools/)
    roots.append(Path(sys.prefix))

    # 3. package-internal mirror
    try:
        import importlib.resources

        package_dir = importlib.resources.files("electromind")  # type: ignore[attr-defined]
        roots.append(Path(str(package_dir)) / "skills_data")
    except (ImportError, TypeError, ValueError):
        pass

    # 4. repo source-tree fallback (walk up from this file)
    here = Path(__file__).resolve()
    for parent in (here.parents[3], here.parents[4], here.parents[5]):
        repo_skills = parent / "skills"
        if _is_bundle_dir(repo_skills):
            roots.append(repo_skills)
            break

    return roots


def builtin_roots() -> tuple[Path, ...]:
    """Return the builtin skill roots that actually exist on disk.

    A root qualifies when it carries the builtin bundle shape (AGENTS.md +
    procedures/ + tools/).  Returns an empty tuple when no builtin bundle is
    available (empty-environment discovery test).
    """
    found: list[Path] = []
    for root in _candidate_builtin_roots():
        if _is_bundle_dir(root):
            found.append(root.resolve())
    return tuple(found)


def builtin_kind_for(root: Path, skill_dir: Path) -> str:
    """Return ``"procedure"`` or ``"tool"`` for *skill_dir* under *root*."""
    try:
        rel = skill_dir.resolve().relative_to(root.resolve())
        first = rel.parts[0]
        if first in BUILTIN_SKILL_DIRS:
            return "procedure" if first == "procedures" else "tool"
    except ValueError:
        pass
    return "standard"
