"""SKILL-5: single-skill lazy mounting — only the activated Skill reaches the
execution environment.

The old flow installed every discovered Skill when a Runner opened
(``Sandbox.install_skill_catalog``).  The new flow installs exactly one
content-addressed snapshot at activation time:

    discover 100 skills → activate 1 → the environment receives 1

``LazySkillMounter`` implements the ``SkillMounter`` protocol (SKILL-4) on top
of the existing staging / atomic-rename machinery in
``Sandbox.install_skill_snapshot``.  The snapshot dir comes from the private
snapshot store, so the mounted content is exactly the frozen, substituted
activation body — never a live re-read of possibly-changed source files.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .activation import SkillMounter
from .snapstore import PrivateSnapshotStore, SkillSnapshotRef

if TYPE_CHECKING:
    from ..sandbox.sandbox import Sandbox


class LazySkillMounter(SkillMounter):
    """Mount one snapshot into a sandbox at activation time.

    Args:
        sandbox: The target execution environment (Local/Container backends).
        store: The private snapshot store holding the frozen snapshot.
    """

    def __init__(
        self,
        sandbox: "Sandbox",
        store: PrivateSnapshotStore | None = None,
    ) -> None:
        self.sandbox = sandbox
        self.store = store or PrivateSnapshotStore()

    async def mount(self, ref: SkillSnapshotRef) -> str:
        """Mount *ref* into the sandbox; returns the agent-visible root.

        The snapshot must exist in the private store; a missing snapshot
        (e.g. after GC) fails the mount rather than re-reading source files.
        """
        snapshot_dir = self.store.path_for(ref)
        if snapshot_dir is None:
            raise FileNotFoundError(f"snapshot {ref.digest} not found in private store")
        return await self.sandbox.install_skill_snapshot(snapshot_dir, ref.digest)

    async def rollback(self, mounted_root: str) -> None:
        """Remove a mounted root left behind by a failed transaction."""
        from ..sandbox.base import SandboxLimits

        try:
            resolved = self.sandbox.resolve(mounted_root)
            await self.sandbox.backend.exec(
                ["rm", "-rf", resolved],
                cwd=self.sandbox.workdir,
                limits=SandboxLimits(timeout=30),
            )
        except Exception:
            pass


class SshLazySkillMounter(LazySkillMounter):
    """SSH variant of the single-skill lazy mount (SKILL-5 PR C).

    Adds the SSH-specific guarantees on top of the shared staging /
    atomic-rename machinery:

    - **Remote digest cache**: an already-mounted digest path is reused
      without re-uploading.
    - **Staging upload**: content is written to a staging dir first.
    - **Digest verification**: after the atomic rename, the mounted
      ``SKILL.md`` is read back and its hash must match the snapshot's —
      a corrupted or truncated upload fails the mount.
    - **Failure rollback**: a verification failure removes the mounted root
      and raises (no half-mounted state).
    """

    async def mount(self, ref: SkillSnapshotRef) -> str:
        mounted_root = await super().mount(ref)
        await self._verify_remote(ref, mounted_root)
        return mounted_root

    async def _verify_remote(self, ref: SkillSnapshotRef, mounted_root: str) -> None:
        """Verify the FULL mounted snapshot against the store.

        Covers ``SKILL.md`` AND every resource file (``resources/**``):
        each remote file's short content hash must match the store's copy.
        A corrupted or truncated upload of ANY file fails the mount and
        rolls back (no half-mounted state).
        """

        snapshot_dir = self.store.path_for(ref)
        if snapshot_dir is None:
            raise FileNotFoundError(f"snapshot {ref.digest} not found in private store")

        remote_files = _relative_files(snapshot_dir)
        for rel in remote_files:
            expected = _short_hash((snapshot_dir / rel).read_bytes())
            try:
                raw = await self.sandbox.files.read(f"{mounted_root}/{rel}")
            except Exception as exc:
                await self.rollback(mounted_root)
                raise RuntimeError(
                    f"ssh mount verification could not read remote {rel}: {exc}"
                ) from exc
            actual = _short_hash(raw if isinstance(raw, bytes) else raw.encode("utf-8"))
            if actual != expected:
                await self.rollback(mounted_root)
                raise RuntimeError(
                    f"ssh mount digest mismatch on {rel}: "
                    f"expected {expected}, got {actual}"
                )


def _relative_files(root: Path) -> list[str]:
    """All regular file paths under *root* as POSIX rel paths (shallow)."""
    import os as _os

    files: list[str] = []
    for dirpath, dirnames, filenames in _os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in sorted(filenames):
            if filename.startswith("."):
                continue
            full = Path(dirpath) / filename
            files.append(full.relative_to(root).as_posix())
    return sorted(files)


def _short_hash(data: bytes) -> str:
    """First 16 hex chars of SHA-256 (content fingerprint for verification)."""
    import hashlib

    return hashlib.sha256(data).hexdigest()[:16]
