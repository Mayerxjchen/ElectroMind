"""File mutation tracking — built-in before/after snapshots for write tools.

This is the "FileMutationInterceptor" pattern (cf. Codex's apply_patch delta
executor): the tool dispatch boundary captures the file state BEFORE the
mutation and verifies it AFTER, producing an exact ``FileMutationDelta``.
The diff is a rendering of (before, after) — the snapshots are the authority.

- ``exact=False`` when the write failed but the disk may have changed.
- Content is captured only up to a size cap; larger files carry
  sha256/size references only (content-addressed by hash).
- A per-thread ``MutationTracker`` aggregates the NET change per path
  (baseline → current), so N writes to one file render as one diff.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

# Content captured inline up to this size; larger files → hash refs only.
SNAPSHOT_CONTENT_LIMIT = 256 * 1024

WRITE_TOOLS = frozenset(
    {"write_file", "str_replace", "delete_file", "copy_to_host", "copy_from_host"}
)


class MutationBlobStore:
    """Content-addressed store for oversized/binary file content.

    ``FileSnapshot`` keeps only sha256/size refs for such files; the blob
    store holds the actual bytes so before/after content stays complete
    and recoverable (deduplicated by content hash).

    Per-Run scope: each thread's store is cleared when the next Run
    starts, and the store is instance-owned (never shared across threads
    or runs).
    """

    # Bounded by BOTH entry count and total bytes (oldest evicted) so a
    # run touching many large files cannot grow without limit.
    MAX_BLOBS = 512
    MAX_TOTAL_BYTES = 64 * 1024 * 1024

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}
        self._total_bytes = 0

    def put(self, data: bytes) -> str:
        """Store raw bytes, returning their content-addressed sha256.

        Evicts oldest entries when the entry count or total byte budget
        is exceeded.  Re-storing an existing digest is a no-op (the bytes
        are already accounted).
        """
        digest = hashlib.sha256(data).hexdigest()
        if digest in self._blobs:
            return digest
        self._blobs[digest] = data
        self._total_bytes += len(data)
        while (
            len(self._blobs) > self.MAX_BLOBS
            or self._total_bytes > self.MAX_TOTAL_BYTES
        ):
            # Evict the oldest (dict preserves insertion order)
            oldest = next(iter(self._blobs))
            self._total_bytes -= len(self._blobs.pop(oldest))
        return digest

    def get(self, sha256: str) -> bytes | None:
        """Return stored bytes for a content hash, or None."""
        return self._blobs.get(sha256)

    def clear(self) -> None:
        self._blobs.clear()
        self._total_bytes = 0


# Content inlined into unified-diff hunks up to this size (blob-backed
# diffs stay bounded); the snapshots themselves remain complete.
DIFF_RENDER_LIMIT = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    """Immutable state of a file at one point in time."""

    exists: bool
    size: int
    sha256: str
    content: str | None  # None when absent, binary, or over the size cap
    truncated: bool = False

    @classmethod
    def capture(
        cls, path: Path, blob_store: MutationBlobStore | None = None
    ) -> FileSnapshot:
        if not path.is_file():
            return FileSnapshot(exists=False, size=0, sha256="", content=None)
        return cls.from_bytes(path.read_bytes(), str(path), blob_store=blob_store)

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        path: str,
        blob_store: MutationBlobStore | None = None,
    ) -> FileSnapshot:
        """Build a snapshot from raw bytes (backend-aware reads).

        Oversized/binary content is stored in the blob store (when one is
        provided) so the before/after stays complete — ``sha256`` is the
        content-addressed key.
        """
        digest = hashlib.sha256(data).hexdigest()
        if len(data) > SNAPSHOT_CONTENT_LIMIT:
            if blob_store is not None:
                blob_store.put(data)
            return FileSnapshot(
                exists=True,
                size=len(data),
                sha256=digest,
                content=None,
                truncated=True,
            )
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            if blob_store is not None:
                blob_store.put(data)
            return FileSnapshot(
                exists=True, size=len(data), sha256=digest, content=None
            )
        if "\x00" in text:
            # NUL bytes decode as valid UTF-8 — treat as binary (hash ref only)
            if blob_store is not None:
                blob_store.put(data)
            return FileSnapshot(
                exists=True, size=len(data), sha256=digest, content=None
            )
        return FileSnapshot(exists=True, size=len(data), sha256=digest, content=text)


@dataclass(frozen=True, slots=True)
class FileMutationDelta:
    """Result of one tracked file mutation.

    ``source`` is ``"sandbox"`` or ``"host"`` — the tracker keys on
    (source, path) so host and sandbox namespaces never mix.
    """

    source: str
    tool_call_id: str
    path: str
    kind: str  # "create" | "update" | "delete"
    before: FileSnapshot
    after: FileSnapshot
    exact: bool


def _snapshot_text(
    snap: FileSnapshot, blob_store: MutationBlobStore | None
) -> str | None:
    """Return inline text for a snapshot, resolving blob-backed content.

    Blob content is decoded for diffing only when bounded by
    ``DIFF_RENDER_LIMIT`` — the snapshot itself (blob store) stays
    complete regardless.
    """
    if snap.content is not None:
        return snap.content
    if blob_store is None or not snap.sha256:
        return None
    data = blob_store.get(snap.sha256)
    if data is None or len(data) > DIFF_RENDER_LIMIT:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def render_unified_diff(
    before: FileSnapshot,
    after: FileSnapshot,
    path: str,
    blob_store: MutationBlobStore | None = None,
) -> list[dict]:
    """Render (before, after) as unified-diff hunks with REAL text.

    - create (before missing): all lines are additions.
    - delete (after missing): all lines are deletions.
    - update: deletions then additions from actual content.
    Returns an empty list when the surviving side has no inline content
    (binary / oversized) or when the snapshots are identical.
    """
    if not before.exists:
        after_text = _snapshot_text(after, blob_store)
        if after_text is None:
            return []
        old_lines: list[str] = []
        new_lines = after_text.splitlines()
    elif not after.exists:
        before_text = _snapshot_text(before, blob_store)
        if before_text is None:
            return []
        old_lines = before_text.splitlines()
        new_lines = []
    else:
        before_text = _snapshot_text(before, blob_store)
        after_text = _snapshot_text(after, blob_store)
        if before_text is None or after_text is None:
            return []
        if before_text == after_text:
            return []
        old_lines = before_text.splitlines()
        new_lines = after_text.splitlines()

    # Simple LCS-free diff: emit a single hunk containing all deletions
    # then all additions (correct, if not minimal).
    hunk_lines: list[dict] = [
        {"kind": "deletion", "content": line} for line in old_lines
    ] + [{"kind": "addition", "content": line} for line in new_lines]
    old_count = len(old_lines) or 1
    new_count = len(new_lines) or 1
    return [
        {
            "header": f"@@ -1,{old_count} +1,{new_count} @@",
            "lines": hunk_lines,
        }
    ]


def delta_to_file_change(
    delta: FileMutationDelta,
    *,
    thread_id: str,
    run_id: str,
) -> dict:
    """Convert a delta into the wire FileChange payload."""
    before = delta.before
    after = delta.after
    additions = 0
    deletions = 0
    hunks: list[dict] = []
    if before.content is not None and after.content is not None:
        hunks = render_unified_diff(before, after, delta.path)
        deletions = max(
            0,
            len(before.content.split("\n"))
            - (1 if before.content.endswith("\n") else 0),
        )
        additions = max(
            0,
            len(after.content.split("\n")) - (1 if after.content.endswith("\n") else 0),
        )
    return {
        "thread_id": thread_id,
        "run_id": run_id,
        "tool_call_id": delta.tool_call_id,
        "path": delta.path,
        "status": "added"
        if delta.kind == "create"
        else "deleted"
        if delta.kind == "delete"
        else "modified",
        "additions": additions,
        "deletions": deletions,
        "exact": delta.exact,
        "before": {
            "exists": before.exists,
            "size": before.size,
            "sha256": before.sha256,
        },
        "after": {
            "exists": after.exists,
            "size": after.size,
            "sha256": after.sha256,
        },
        "hunks": hunks,
    }


@dataclass(slots=True)
class MutationTracker:
    """Per-thread net-change aggregator (baseline → current per path)."""

    _baseline: dict[tuple[str, str], FileSnapshot] = field(default_factory=dict)
    _current: dict[tuple[str, str], FileSnapshot] = field(default_factory=dict)
    _invalid: set[tuple[str, str]] = field(default_factory=set)
    _last_call: dict[tuple[str, str], str] = field(default_factory=dict)
    # Content-addressed store for oversized/binary before/after content.
    blob_store: MutationBlobStore | None = None

    def _key(self, source: str, path: str) -> tuple[str, str]:
        return (source, path)

    def track(self, delta: FileMutationDelta) -> None:
        """Record a delta; the (source, path) baseline is set on FIRST mutation."""
        key = self._key(delta.source, delta.path)
        if not delta.exact:
            self._invalid.add(key)
        if key not in self._baseline:
            self._baseline[key] = delta.before
        self._current[key] = delta.after
        if delta.tool_call_id:
            self._last_call[key] = delta.tool_call_id

    def net_change(self, source: str, path: str, tool_call_id: str) -> dict | None:
        """Return the net FileChange payload for (source, path), or None.

        ``tool_call_id`` is the last mutating call for the path (a net diff
        may span several calls — the last one is the attribution anchor).
        """
        key = self._key(source, path)
        if key not in self._baseline or key not in self._current:
            return None
        if key in self._invalid:
            baseline = self._baseline[key]
            current = self._current[key]
            return {
                "path": path,
                "source": source,
                "status": "modified",
                "additions": 0,
                "deletions": 0,
                "exact": False,
                "tool_call_id": self._last_call.get(key, tool_call_id),
                "hunks": [],
                # before/after remain available even when inexact — the
                # mutation (possibly partial) is fully accounted.
                "before": {
                    "exists": baseline.exists,
                    "size": baseline.size,
                    "sha256": baseline.sha256,
                },
                "after": {
                    "exists": current.exists,
                    "size": current.size,
                    "sha256": current.sha256,
                },
            }
        baseline = self._baseline[key]
        current = self._current[key]
        hunks = render_unified_diff(baseline, current, path, self.blob_store)

        def _blob_missing(snap: FileSnapshot) -> bool:
            """True when the snapshot's content-addressed content was
            evicted/cleared and can no longer be resolved — the sha256
            reference would dangle."""
            return (
                snap.content is None
                and bool(snap.sha256)
                and self.blob_store is not None
                and self.blob_store.get(snap.sha256) is None
            )

        if _blob_missing(baseline) or _blob_missing(current):
            # Content references no longer resolvable → the before/after
            # is NOT complete.  Degrade to inexact rather than presenting
            # an empty-but-exact diff over dangling hashes.
            return {
                "path": path,
                "source": source,
                "status": "modified",
                "additions": 0,
                "deletions": 0,
                "exact": False,
                "tool_call_id": self._last_call.get(key, tool_call_id),
                "hunks": [],
                "before": {
                    "exists": baseline.exists,
                    "size": baseline.size,
                    "sha256": baseline.sha256,
                },
                "after": {
                    "exists": current.exists,
                    "size": current.size,
                    "sha256": current.sha256,
                },
            }
        return {
            "path": path,
            "source": source,
            "status": "added"
            if not baseline.exists
            else "deleted"
            if not current.exists
            else "modified",
            "additions": sum(
                1 for h in hunks for ln in h["lines"] if ln["kind"] == "addition"
            ),
            "deletions": sum(
                1 for h in hunks for ln in h["lines"] if ln["kind"] == "deletion"
            ),
            "exact": True,
            "tool_call_id": self._last_call.get(key, tool_call_id),
            "before": {
                "exists": baseline.exists,
                "size": baseline.size,
                "sha256": baseline.sha256,
            },
            "after": {
                "exists": current.exists,
                "size": current.size,
                "sha256": current.sha256,
            },
            "hunks": hunks,
        }

    def clear(self) -> None:
        self._baseline.clear()
        self._current.clear()
        self._invalid.clear()
