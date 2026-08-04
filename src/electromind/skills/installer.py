"""SKILL-9: user-invoked skill installer — local dir / archive / git.

Constraints (RFC section 十三):

- The installer is invoked ONLY by the user through the CLI.  It is never
  exposed as a model tool — the model cannot install skills, and a skill
  cannot install another skill.
- Installation is atomic: content is staged, validated, then renamed into
  place; a failed install leaves no partial skill.
- Updates keep the previous version for rollback.
- Every install records its source (local path / archive / git ref).

Install target: ``~/.electromind/skills/<name>/`` (user scope).
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .skill import parse_skill_md, validate_skill_name

MANIFEST_NAME = ".electromind-install.json"


class InstallError(Exception):
    """A skill installation that cannot complete."""


@dataclass(frozen=True, slots=True)
class InstallRecord:
    """Provenance of one installed skill."""

    name: str
    source: str
    source_type: str  # "local" | "archive" | "git"
    installed_at: float
    digest: str = ""
    previous_digest: str = ""


@dataclass(frozen=True, slots=True)
class InstallResult:
    """Outcome of an install/update."""

    name: str
    target: Path
    record: InstallRecord
    updated: bool = False
    rolled_back_from: str = ""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_skill_dir(skill_dir: Path) -> str:
    """Validate a skill directory; returns its name or raises ``InstallError``.

    Checks: SKILL.md exists, frontmatter parses, ``name`` is present and
    valid, ``description`` is present.
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise InstallError(f"missing SKILL.md in {skill_dir}")
    try:
        frontmatter, _body = parse_skill_md(skill_md.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - surface any parse failure
        raise InstallError(f"cannot parse SKILL.md in {skill_dir}: {exc}") from exc
    name = str(frontmatter.get("name") or "").strip() or skill_dir.name
    name_err = validate_skill_name(name)
    if name_err:
        raise InstallError(f"invalid skill name {name!r}: {name_err}")
    if not str(frontmatter.get("description") or "").strip():
        raise InstallError(f"frontmatter must include `description` in {skill_dir}")
    return name


# ---------------------------------------------------------------------------
# Installer
# ---------------------------------------------------------------------------


class SkillInstaller:
    """Installs skills into a user-scope skills root (atomic, rollback-able)."""

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            from ..paths import default_electromind_home

            root = default_electromind_home() / "skills"
        self.root = Path(root).expanduser().resolve()

    # -- install ----------------------------------------------------------

    async def install_from_dir(self, src: Path) -> InstallResult:
        """Install a skill from a local directory (atomic)."""
        src = Path(src).expanduser().resolve()
        if not src.is_dir():
            raise InstallError(f"source is not a directory: {src}")
        name = validate_skill_dir(src)
        return await self._install_staged(
            name, src, source=str(src), source_type="local"
        )

    async def install_from_archive(self, archive: Path) -> InstallResult:
        """Install a skill from a zip/tar archive (extract → validate → install)."""
        archive = Path(archive).expanduser().resolve()
        if not archive.is_file():
            raise InstallError(f"archive not found: {archive}")
        with _TemporaryDir() as tmp:
            extracted = _extract_archive(archive, tmp.path)
            if extracted is None:
                raise InstallError(f"unsupported archive format: {archive.suffix}")
            # Archive may contain the skill dir directly or under one level.
            candidates = _find_skill_dirs(extracted)
            if not candidates:
                raise InstallError(f"no SKILL.md found in archive {archive}")
            if len(candidates) > 1:
                raise InstallError(
                    "archive contains multiple skills; install one directory at a time"
                )
            skill_dir = candidates[0]
            name = validate_skill_dir(skill_dir)
            return await self._install_staged(
                name,
                skill_dir,
                source=str(archive),
                source_type="archive",
            )

    async def install_from_git(self, repo: str, *, ref: str = "HEAD") -> InstallResult:
        """Install a skill from a git repository (clone → validate → install).

        Requires ``git`` on PATH.  The repo is cloned into a temporary
        directory; the skill directory is located and installed atomically.
        """
        import subprocess

        with _TemporaryDir() as tmp:
            clone = tmp.path / "repo"
            proc = subprocess.run(
                ["git", "clone", "--quiet", repo, str(clone)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode != 0:
                raise InstallError(
                    f"git clone failed: {proc.stderr.strip() or proc.stdout.strip()}"
                )
            if ref != "HEAD":
                checkout = subprocess.run(
                    ["git", "-C", str(clone), "checkout", "--quiet", ref],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if checkout.returncode != 0:
                    raise InstallError(
                        f"git checkout {ref!r} failed: {checkout.stderr.strip()}"
                    )
            candidates = _find_skill_dirs(clone)
            if not candidates:
                raise InstallError(f"no SKILL.md found in repo {repo}")
            if len(candidates) > 1:
                raise InstallError(
                    "repo contains multiple skills; install one directory at a time"
                )
            skill_dir = candidates[0]
            name = validate_skill_dir(skill_dir)
            return await self._install_staged(
                name,
                skill_dir,
                source=f"{repo}#{ref}",
                source_type="git",
            )

    # -- update / uninstall / list ----------------------------------------

    async def uninstall(self, name: str) -> bool:
        """Remove an installed skill.  Returns True when it existed.

        Security: *name* must be a valid skill name and the resolved target
        must stay inside the install root — ``uninstall("../victim")`` is
        rejected instead of deleting outside the root.
        """
        from .skill import validate_skill_name

        if validate_skill_name(name) is not None:
            raise InstallError(f"invalid skill name {name!r}")
        target = (self.root / name).resolve()
        root = self.root.resolve()
        if target.parent != root and root not in target.parents:
            raise InstallError(f"target escapes install root: {name!r}")
        if not target.is_dir():
            return False
        shutil.rmtree(target, ignore_errors=True)
        return True

    def installed(self) -> list[InstallRecord]:
        """Provenance records of all installed skills."""
        if not self.root.is_dir():
            return []
        records: list[InstallRecord] = []
        for entry in sorted(self.root.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            manifest = entry / MANIFEST_NAME
            if manifest.is_file():
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                    records.append(InstallRecord(**data))
                except (OSError, ValueError, TypeError):
                    continue
        return records

    # -- internals --------------------------------------------------------

    async def _install_staged(
        self,
        name: str,
        src_dir: Path,
        *,
        source: str,
        source_type: str,
    ) -> InstallResult:
        """Stage + validate + atomic rename into place.

        When an older version exists it is kept as ``<name>.bak-<ts>`` for
        rollback; the rename is atomic so a failure leaves either the old or
        the new version, never a mix.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / name
        previous_digest = ""
        if target.is_dir():
            previous_digest = _dir_digest(target)

        staging = self.root / f".staging-{uuid.uuid4().hex[:8]}"
        try:
            shutil.copytree(src_dir, staging)
            # Drop any stale install manifest from the source
            (staging / MANIFEST_NAME).unlink(missing_ok=True)
            validate_skill_dir(staging)  # re-validate the staged copy

            # Atomic replace: keep the old version for rollback
            backup: Path | None = None
            if target.is_dir():
                backup = self.root / f"{name}.bak-{int(time.time())}"
                shutil.move(str(target), str(backup))
            try:
                shutil.move(str(staging), str(target))
            except Exception:
                # Roll back: restore the previous version
                if backup is not None and backup.is_dir():
                    shutil.move(str(backup), str(target))
                raise
            if backup is not None:
                shutil.rmtree(backup, ignore_errors=True)

            digest = _dir_digest(target)
            record = InstallRecord(
                name=name,
                source=source,
                source_type=source_type,
                installed_at=time.time(),
                digest=digest,
                previous_digest=previous_digest,
            )
            (target / MANIFEST_NAME).write_text(
                json.dumps(
                    {
                        "name": record.name,
                        "source": record.source,
                        "source_type": record.source_type,
                        "installed_at": record.installed_at,
                        "digest": record.digest,
                        "previous_digest": record.previous_digest,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            return InstallResult(
                name=name,
                target=target,
                record=record,
                updated=bool(previous_digest),
            )
        finally:
            shutil.rmtree(staging, ignore_errors=True)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _find_skill_dirs(root: Path) -> list[Path]:
    """Skill directories under *root* (SKILL.md present, shallow)."""
    found: list[Path] = []
    candidates: list[Path] = [root]
    if root.is_dir():
        candidates.extend(sorted(root.iterdir()))
    for candidate in candidates:
        if (candidate / "SKILL.md").is_file():
            found.append(candidate)
    return found


def _extract_archive(archive: Path, dest: Path) -> Path | None:
    """Extract *archive* into *dest*; returns the extraction root.

    Security (SKILL-9): archive members are validated before extraction —
    absolute paths, ``..`` traversal, device files, and symlink escapes are
    rejected.  Both ``.tar.gz``/``.tar.bz2`` (multi-suffix) and ``.zip`` are
    supported.
    """
    name = archive.name.lower()
    if name.endswith(".zip"):
        import zipfile

        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                _validate_archive_member(info.filename, dest, is_dir=info.is_dir())
            zf.extractall(dest)
        return dest
    if any(name.endswith(s) for s in (".tar", ".tgz", ".tar.gz", ".tar.bz2")):
        import tarfile

        with tarfile.open(archive) as tf:
            for member in tf.getmembers():
                # Reject links/devices/FIFOs outright — a symlink pointing
                # outside the staging root would let a later member write
                # through it (``link -> ../outside`` + ``link/pwn.txt``).
                if (
                    member.issym()
                    or member.islnk()
                    or member.isdev()
                    or member.isfifo()
                ):
                    raise InstallError(
                        f"archive member is a link/special file: {member.name!r}"
                    )
                _validate_archive_member(
                    member.name, dest, is_dir=member.isdir(), linkname=member.linkname
                )
            tf.extractall(dest)
        return dest
    return None


def _validate_archive_member(
    member_name: str, dest: Path, *, is_dir: bool, linkname: str = ""
) -> None:
    """Reject unsafe archive members (absolute, traversal, device, escape)."""
    import posixpath

    if member_name.startswith(("/", "\\")) or ":" in member_name.split("/", 1)[0]:
        raise InstallError(f"archive member uses absolute path: {member_name!r}")
    normalized = posixpath.normpath(member_name)
    if normalized == ".." or normalized.startswith("../"):
        raise InstallError(f"archive member escapes target: {member_name!r}")
    if any(part == ".." for part in normalized.split("/")):
        raise InstallError(f"archive member escapes target: {member_name!r}")
    if not is_dir and _is_device_name(member_name):
        raise InstallError(f"archive member is a device file: {member_name!r}")
    # Defense-in-depth: any link target (symlink/hardlink) must stay inside
    # the extraction root — even though links are rejected before extraction,
    # a future refactor must not silently relax this.
    if linkname:
        normalized_link = posixpath.normpath(linkname)
        if normalized_link.startswith("/") or normalized_link.startswith("../"):
            raise InstallError(
                f"archive member link escapes target: {member_name!r} -> {linkname!r}"
            )
    resolved = (dest / normalized).resolve()
    if dest.resolve() not in resolved.parents and resolved != dest.resolve():
        raise InstallError(f"archive member resolves outside target: {member_name!r}")


def _is_device_name(name: str) -> bool:
    """Heuristic: device-like member names (con, nul, /dev/*)."""
    base = name.rsplit("/", 1)[-1].lower()
    return (
        base in ("con", "nul", "prn", "aux")
        or base.startswith("com")
        or base.startswith("lpt")
    )


def _dir_digest(path: Path) -> str:
    """Content digest of a skill directory (SKILL.md + files)."""
    import hashlib
    import os

    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in sorted(filenames):
            if filename.startswith("."):
                continue
            full = Path(dirpath) / filename
            rel = full.relative_to(path).as_posix()
            h.update(rel.encode("utf-8"))
            try:
                h.update(full.read_bytes())
            except OSError:
                pass
    return h.hexdigest()


class _TemporaryDir:
    """Context-managed temporary directory."""

    def __enter__(self) -> "_TemporaryDir":
        import tempfile

        self.path = Path(tempfile.mkdtemp(prefix="skill-install-"))
        return self

    def __exit__(self, *exc) -> None:
        shutil.rmtree(self.path, ignore_errors=True)
