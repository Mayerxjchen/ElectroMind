"""Shared skill-test helpers.

Importable by any test file without making ``tests`` a package: the helper
module lives at ``tests/skill_helpers.py`` and is picked up via pytest's
rootdir path insertion.
"""

from pathlib import Path


def write_skill_dir(root: Path, name: str, description: str, body: str) -> Path:
    """Create a minimal valid skill directory under *root*."""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}",
        encoding="utf-8",
    )
    return d


def make_skill_dirs(root: Path, count: int) -> None:
    """Create ``count`` skills named ``skill-000`` … ``skill-<count-1>``."""
    for i in range(count):
        write_skill_dir(root, f"skill-{i:03d}", "d", f"body {i}\n")
