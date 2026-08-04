"""FileMutationInterceptor — built-in before/after snapshot tests.

Verifies: snapshot capture, exact/inexact deltas, unified-diff rendering
with REAL text (create/update/delete), and turn-level net aggregation.
"""

from __future__ import annotations

from electromind.harness.mutations import (
    FileMutationDelta,
    FileSnapshot,
    MutationTracker,
    render_unified_diff,
)


def _snap(path, content: str | None = None):
    if content is None:
        return FileSnapshot(exists=False, size=0, sha256="", content=None)
    (path / "f").write_text(content)
    return FileSnapshot.capture(path / "f")


def test_snapshot_capture_text(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("line1\nline2\n")
    snap = FileSnapshot.capture(f)
    assert snap.exists
    assert snap.content == "line1\nline2\n"
    assert snap.sha256  # content-addressed by hash
    assert snap.size == 12


def test_snapshot_missing_file(tmp_path):
    snap = FileSnapshot.capture(tmp_path / "nope")
    assert not snap.exists
    assert snap.content is None


def test_snapshot_binary_no_content(tmp_path):
    f = tmp_path / "b.bin"
    f.write_bytes(b"\x00\x01\x02")
    snap = FileSnapshot.capture(f)
    assert snap.exists
    assert snap.content is None  # binary → hash ref only
    assert snap.sha256


def test_render_diff_update_real_text(tmp_path):
    before = _snap(tmp_path, "old line")
    after_path = tmp_path / "f"
    after_path.write_text("new line 1\nnew line 2\n")
    after = FileSnapshot.capture(after_path)
    hunks = render_unified_diff(before, after, "f")
    assert len(hunks) == 1
    lines = hunks[0]["lines"]
    deletions = [ln for ln in lines if ln["kind"] == "deletion"]
    additions = [ln for ln in lines if ln["kind"] == "addition"]
    assert deletions[0]["content"] == "old line"
    assert additions[0]["content"] == "new line 1"
    assert additions[1]["content"] == "new line 2"
    assert hunks[0]["header"] == "@@ -1,1 +1,2 @@"


def test_render_diff_create_all_additions(tmp_path):
    f = tmp_path / "new.txt"
    f.write_text("created\n")
    after = FileSnapshot.capture(f)
    before = FileSnapshot(exists=False, size=0, sha256="", content=None)
    hunks = render_unified_diff(before, after, "new.txt")
    assert len(hunks) == 1
    assert all(ln["kind"] == "addition" for ln in hunks[0]["lines"])
    assert hunks[0]["lines"][0]["content"] == "created"


def test_render_diff_delete_all_deletions(tmp_path):
    before = _snap(tmp_path, "gone\n")
    after = FileSnapshot(exists=False, size=0, sha256="", content=None)
    hunks = render_unified_diff(before, after, "f")
    assert len(hunks) == 1
    assert all(ln["kind"] == "deletion" for ln in hunks[0]["lines"])
    assert hunks[0]["lines"][0]["content"] == "gone"


def test_tracker_net_change_aggregates(tmp_path):
    """Three writes to one file → ONE net diff (baseline → final)."""
    tracker = MutationTracker()
    f = tmp_path / "f"
    f.write_text("v1")
    b1 = FileSnapshot.capture(f)

    f.write_text("v2")
    a1 = FileSnapshot.capture(f)
    tracker.track(
        FileMutationDelta("sandbox", "tc-1", "f", "update", b1, a1, exact=True)
    )

    f.write_text("v3")
    a2 = FileSnapshot.capture(f)
    tracker.track(
        FileMutationDelta("sandbox", "tc-2", "f", "update", a1, a2, exact=True)
    )

    f.write_text("v3 final")
    a3 = FileSnapshot.capture(f)
    tracker.track(
        FileMutationDelta("sandbox", "tc-3", "f", "update", a2, a3, exact=True)
    )

    net = tracker.net_change("sandbox", "f", "tc-3")
    assert net is not None
    # Net diff is v1 → "v3 final" (baseline preserved, not chained)
    addition_texts = [
        ln["content"]
        for h in net["hunks"]
        for ln in h["lines"]
        if ln["kind"] == "addition"
    ]
    assert "v3 final" in addition_texts
    deletion_texts = [
        ln["content"]
        for h in net["hunks"]
        for ln in h["lines"]
        if ln["kind"] == "deletion"
    ]
    assert "v1" in deletion_texts
    assert net["exact"] is True


def test_tracker_inexact_invalidates_diff(tmp_path):
    tracker = MutationTracker()
    f = tmp_path / "f"
    f.write_text("before")
    b = FileSnapshot.capture(f)
    f.write_text("after")
    a = FileSnapshot.capture(f)
    tracker.track(
        FileMutationDelta("sandbox", "tc-1", "f", "update", b, a, exact=False)
    )

    net = tracker.net_change("sandbox", "f", "tc-1")
    assert net is not None
    assert net["exact"] is False
    assert net["hunks"] == []  # not trusted → no fabricated diff


def test_tracker_separates_host_and_sandbox_namespaces(tmp_path):
    """host:artifacts/x and sandbox:artifacts/x must NOT aggregate together."""
    tracker = MutationTracker()
    f = tmp_path / "f"
    f.write_text("sandbox version")
    sb = FileSnapshot.capture(f)
    f.write_text("sandbox v2")
    sa = FileSnapshot.capture(f)
    tracker.track(
        FileMutationDelta(
            "sandbox", "tc-1", "artifacts/x", "update", sb, sa, exact=True
        )
    )

    g = tmp_path / "g"
    g.write_text("host version")
    hb = FileSnapshot.capture(g)
    g.write_text("host v2")
    ha = FileSnapshot.capture(g)
    tracker.track(
        FileMutationDelta("host", "tc-2", "artifacts/x", "update", hb, ha, exact=True)
    )

    # Two independent keys — neither pollutes the other
    sandbox_net = tracker.net_change("sandbox", "artifacts/x", "tc-1")
    host_net = tracker.net_change("host", "artifacts/x", "tc-2")
    assert sandbox_net is not None
    assert host_net is not None
    assert sandbox_net["source"] == "sandbox"
    assert host_net["source"] == "host"
    sandbox_texts = "".join(
        ln["content"] for h in sandbox_net["hunks"] for ln in h["lines"]
    )
    host_texts = "".join(ln["content"] for h in host_net["hunks"] for ln in h["lines"])
    assert "sandbox" in sandbox_texts and "host" not in sandbox_texts
    assert "host" in host_texts and "sandbox" not in host_texts
