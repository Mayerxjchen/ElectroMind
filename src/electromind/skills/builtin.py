"""SKILL-8 + A+ W5: built-in scientific skill delivery via plain flat roots.

The repo's AICC bundle lives at ``<repo>/skills/`` (procedures/ + tools/ +
knowledge/).  For installed artifacts (wheel, ``uv tool``, Desktop bundle) the
same bundle must be discoverable WITHOUT the repo source.

A+ design (§4): discovery has exactly one model — a plain flat skill root
``<skill-root>/<skill-name>/SKILL.md``.  Builtin skills provide two such roots:

    ``builtin_skill_roots(package_root)`` → (procedures, tools)

There is no AGENTS.md marker, no structured-root bundle, and no collection
manifest.  ``knowledge/`` is the canonical authoring source and is never a
runtime dependency.

Delivery bases, in probe order:

1. ``<sys.prefix>/skills`` — installed by ``[tool.uv.build-backend.data]``
   (``data = "skills"`` in pyproject.toml) into the virtualenv root.
2. ``<sys.prefix>`` itself — venv-root layout (bundle contents installed
   directly at the prefix: ``procedures/``, ``tools/``).
3. ``electromind/skills_data`` — package-internal mirror (bundle scripts /
   PyInstaller ``--collect-data``).
4. ``<repo-root>/skills`` — source-tree fallback during development.

The discovery scope is ``builtin``: read-only, dialect ``builtin``, trusted
by default (RFC section 五).
"""

from __future__ import annotations

import sys
from pathlib import Path


def builtin_skill_roots(package_root: Path) -> tuple[Path, ...]:
    """The two plain flat skill roots of a builtin bundle (A+ design §4).

    No marker is required: each returned root is a flat directory whose
    children with ``SKILL.md`` are skills.
    """
    return (
        package_root / "skills" / "procedures",
        package_root / "skills" / "tools",
    )


def _candidate_builtin_bases() -> list[Path]:
    """Ordered candidate bundle bases (existence-checked by the caller)."""
    bases: list[Path] = []

    # 1. installed data directory — `<sys.prefix>/skills` (explicit subdir)
    bases.append(Path(sys.prefix) / "skills")

    # 2. venv-root layout — uv_build `data = "skills"` installs the bundle
    #    contents directly at `<sys.prefix>` (procedures/, tools/)
    bases.append(Path(sys.prefix))

    # 3. package-internal mirror
    try:
        import importlib.resources

        package_dir = importlib.resources.files("electromind")  # type: ignore[attr-defined]
        bases.append(Path(str(package_dir)) / "skills_data")
    except (ImportError, TypeError, ValueError):
        pass

    # 4. repo source-tree fallback (walk up from this file)
    here = Path(__file__).resolve()
    for parent in (here.parents[3], here.parents[4], here.parents[5]):
        repo_skills = parent / "skills"
        if (repo_skills / "procedures").is_dir() and (repo_skills / "tools").is_dir():
            bases.append(repo_skills)
            break

    return bases


def builtin_roots() -> tuple[Path, ...]:
    """Return the builtin flat skill roots that actually exist on disk.

    A root qualifies when it is a directory; the flat discovery model needs
    no AGENTS.md marker.  Two layouts per candidate base are probed:

    - ``<base>/skills/{procedures,tools}`` — ``builtin_skill_roots(base)``
      (explicit bundle subdir);
    - ``<base>/{procedures,tools}`` — venv-root layout, where uv_build's
      ``data`` scheme installs the bundle contents directly.

    Returns an empty tuple when no builtin bundle is available
    (empty-environment discovery test).
    """
    found: list[Path] = []
    for base in _candidate_builtin_bases():
        for root in builtin_skill_roots(base):
            if root.is_dir():
                found.append(root.resolve())
        for sub in ("procedures", "tools"):
            direct = base / sub
            if direct.is_dir():
                found.append(direct.resolve())
    # Deduplicate (repo probe may overlap with sys.prefix in dev installs).
    unique: list[Path] = []
    for root in found:
        if root not in unique:
            unique.append(root)
    return tuple(unique)


def builtin_kind_for(root: Path, skill_dir: Path) -> str:
    """Return ``"procedure"`` or ``"tool"`` for *skill_dir* under *root*.

    With plain flat roots the kind is the root's own name; the per-skill
    directory no longer carries it.
    """
    if root.name == "procedures":
        return "procedure"
    if root.name == "tools":
        return "tool"
    return "standard"
