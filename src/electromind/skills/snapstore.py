"""SKILL-4: private snapshot store — content-addressed, privacy-safe.

Snapshots live outside any project-exportable record:

    ~/.electromind/snapshots/skills/<sha256>/
    ├── SKILL.md          (substituted activation body)
    ├── manifest.json
    └── resources/        (copied resource files)

- Same digest is stored once (content-addressed dedup).
- Permissions default to owner-only (``0o700``).
- ``gc(referenced)`` removes snapshots that no Thread/Run references and that
  are older than the retention window.

The store never writes into project records; exports must explicitly request
private snapshots (RFC section 七).
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .snapshot import hash_content

StoreKind = Literal["builtin", "project", "private"]
ExportPolicy = Literal["reference_only", "exportable", "private"]


@dataclass(frozen=True, slots=True)
class SkillSnapshotRef:
    """A content-addressed reference to a stored Skill snapshot.

    Attributes:
        digest: SHA-256 of the snapshot content (body + resources).
        store: Which store holds it (``"private"`` for the private store).
        locator: Path or identifier inside the store.
        export_policy: Whether project exports may embed the full body
            (``"private"`` = never without ``--include-private-skill-snapshots``).
    """

    digest: str
    store: StoreKind
    locator: str
    export_policy: ExportPolicy = "private"


class PrivateSnapshotStore:
    """Content-addressed storage of skill snapshots under the electromind home."""

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            from ..paths import default_electromind_home

            root = default_electromind_home() / "snapshots" / "skills"
        self.root = Path(root).expanduser().resolve()

    # -- save / load ------------------------------------------------------

    def save(
        self,
        *,
        name: str,
        body: str,
        resources_dir: Path | None = None,
    ) -> SkillSnapshotRef:
        """Store a snapshot content-addressed on *body* + resource contents.

        Same digest → single copy (existing snapshot is reused).
        Returns a ``SkillSnapshotRef`` into the private store.
        """
        resource_paths = self._resource_paths(resources_dir)
        digest = self._snapshot_digest(body, resource_paths)

        target = self.root / digest
        if target.is_dir():
            return SkillSnapshotRef(
                digest=digest,
                store="private",
                locator=str(target),
                export_policy="private",
            )

        target.mkdir(parents=True, exist_ok=True)
        try:
            os_chmod_private(target)
            (target / "SKILL.md").write_text(body, encoding="utf-8")

            if resources_dir is not None and resource_paths:
                res_target = target / "resources"
                res_target.mkdir(exist_ok=True)
                for rel, src in resource_paths:
                    dst = res_target / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)

            manifest = {
                "name": name,
                "digest": digest,
                "created_at": _now_iso(),
                "resources": sorted(rel for rel, _ in resource_paths),
                "export_policy": "private",
            }
            (target / "manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise

        return SkillSnapshotRef(
            digest=digest, store="private", locator=str(target), export_policy="private"
        )

    def path_for(self, ref: SkillSnapshotRef) -> Path | None:
        """Return the snapshot directory for *ref*, or ``None`` when missing."""
        if ref.store != "private":
            return None
        candidate = self.root / ref.digest
        return candidate if candidate.is_dir() else None

    def read_body(self, ref: SkillSnapshotRef) -> str | None:
        """Return the stored ``SKILL.md`` body, or ``None`` when missing."""
        target = self.path_for(ref)
        if target is None:
            return None
        md = target / "SKILL.md"
        return md.read_text(encoding="utf-8") if md.is_file() else None

    # -- GC ---------------------------------------------------------------

    def gc(
        self,
        referenced: set[str] | frozenset[str],
        *,
        retention_days: int = 30,
        now: float | None = None,
    ) -> int:
        """Remove snapshots with no references older than *retention_days*.

        Args:
            referenced: Digests currently referenced by Thread/Run records.
            retention_days: Minimum age (in days) before an unreferenced
                snapshot may be deleted.
            now: Epoch seconds for age computation (tests inject a fixed time).

        Returns:
            Number of snapshots removed.
        """
        current = now if now is not None else time.time()
        removed = 0
        if not self.root.is_dir():
            return 0
        for entry in self.root.iterdir():
            if not entry.is_dir() or entry.name in referenced:
                continue
            manifest = entry / "manifest.json"
            age_days = self._age_days(manifest, current)
            if age_days is not None and age_days >= retention_days:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
        return removed

    # -- helpers ----------------------------------------------------------

    def _resource_paths(self, resources_dir: Path | None) -> list[tuple[str, Path]]:
        """Return ``[(rel_path, abs_path)]`` for every file under *resources_dir*."""
        if resources_dir is None or not resources_dir.is_dir():
            return []
        pairs: list[tuple[str, Path]] = []
        import os

        for dirpath, dirnames, filenames in os.walk(resources_dir):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for filename in sorted(filenames):
                full = Path(dirpath) / filename
                rel = full.relative_to(resources_dir).as_posix()
                pairs.append((rel, full))
        return pairs

    def _snapshot_digest(
        self, body: str, resource_paths: list[tuple[str, Path]]
    ) -> str:
        parts = [body]
        for rel, full in sorted(resource_paths):
            parts.append(rel)
            try:
                parts.append(
                    hash_content(*(full.read_bytes().decode("utf-8", "replace"),))
                )
            except OSError:
                parts.append("unreadable")
        return hash_content(*parts)

    def _age_days(self, manifest: Path, now: float) -> float | None:
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            created = data.get("created_at", "")
        except (OSError, ValueError):
            return None
        return _days_since(created, now)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _days_since(iso: str, now: float) -> float | None:
    from datetime import datetime, timezone

    try:
        created = datetime.fromisoformat(iso)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return max(0.0, (now - created.timestamp()) / 86400)
    except (ValueError, TypeError):
        return None


def os_chmod_private(path: Path) -> None:
    """Restrict a path to the current user (owner-only, no group/other)."""
    try:
        path.chmod(0o700)
    except OSError:
        pass
