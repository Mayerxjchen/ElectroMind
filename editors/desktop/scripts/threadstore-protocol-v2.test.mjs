/** ThreadStore protocol v2 integration tests.
 *
 * Verifies: event dedup, input/state ACK handling, run lifecycle,
 * snapshot recovery, approval scoping, and per-thread isolation.
 *
 * Run with: node --test editors/desktop/scripts/threadstore-protocol-v2.test.mjs
 */

import { describe, it, beforeEach } from "node:test";
import assert from "node:assert/strict";

// ---------------------------------------------------------------------------
// Load the PRODUCTION ThreadStore (Node 25 type-strips .ts; DOM stubbed).
// ---------------------------------------------------------------------------

globalThis.window = {
  localStorage: {
    getItem: () => null,
    setItem: () => {},
  },
};

const { getThreadStore, resetThreadStore } = await import(
  new URL("../src/renderer/store/ThreadStore.ts", import.meta.url)
);

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ThreadStore protocol v2", () => {
  /** @type {TestThreadStore} */
  let store;

  beforeEach(() => {
    resetThreadStore();
    store = getThreadStore();
  });

  // ── Event dedup ──────────────────────────────────────────────────

  it("skips duplicate event_id", () => {
    const params = {
      thread_id: "t1",
      event_id: "evt-001",
      seq: 1,
    };
    assert.equal(store.applyWireEvent("input/state", { ...params, state: "queued" }), true);
    // Duplicate event_id → skipped
    assert.equal(store.applyWireEvent("input/state", { ...params, state: "applied" }), true);
    // Status should still be the first-applied value
    assert.equal(store.ensureThread("t1").status, "idle");
  });

  it("skips events with seq <= lastEventSeq", () => {
    store.applyWireEvent("input/state", { thread_id: "t1", seq: 5, state: "queued" });
    assert.equal(store.ensureThread("t1").lastEventSeq, 5);
    // seq 3 <= 5 → skipped
    store.applyWireEvent("input/state", { thread_id: "t1", seq: 3, state: "rejected" });
    assert.equal(store.ensureThread("t1").lastEventSeq, 5); // Unchanged
  });

  it("advances lastEventSeq on new events", () => {
    store.applyWireEvent("input/state", { thread_id: "t1", seq: 1 });
    store.applyWireEvent("input/state", { thread_id: "t1", seq: 2 });
    store.applyWireEvent("input/state", { thread_id: "t1", seq: 5 });
    assert.equal(store.ensureThread("t1").lastEventSeq, 5);
  });

  // ── Per-thread isolation ─────────────────────────────────────────

  it("events for thread A do not leak into thread B", () => {
    store.applyWireEvent("run/started", {
      thread_id: "a",
      run_id: "run-a1",
      seq: 1,
    });
    store.applyWireEvent("run/started", {
      thread_id: "b",
      run_id: "run-b1",
      seq: 1,
    });

    assert.equal(store.ensureThread("a").activeRun.runId, "run-a1");
    assert.equal(store.ensureThread("b").activeRun.runId, "run-b1");
    assert.equal(store.ensureThread("a").status, "running");
    assert.equal(store.ensureThread("b").status, "running");
  });

  it("seq counters are independent per thread", () => {
    store.applyWireEvent("input/state", { thread_id: "a", seq: 10 });
    store.applyWireEvent("input/state", { thread_id: "b", seq: 1 });
    assert.equal(store.ensureThread("a").lastEventSeq, 10);
    assert.equal(store.ensureThread("b").lastEventSeq, 1);
  });

  // ── input/state ──────────────────────────────────────────────────

  it("input/state: queued does not change status to running", () => {
    store.applyWireEvent("input/state", {
      thread_id: "t1",
      seq: 1,
      state: "queued",
      message_id: "msg-001",
    });
    assert.equal(store.ensureThread("t1").status, "idle");
  });

  it("input/state: applied sets status to running", () => {
    store.applyWireEvent("input/state", {
      thread_id: "t1",
      seq: 1,
      state: "applied",
    });
    assert.equal(store.ensureThread("t1").status, "running");
  });

  // ── run/* ────────────────────────────────────────────────────────

  it("run/started creates activeRun and sets status", () => {
    store.applyWireEvent("run/started", {
      thread_id: "t1",
      run_id: "run-abc",
      seq: 1,
    });
    const t = store.ensureThread("t1");
    assert.equal(t.status, "running");
    assert.equal(t.activeRun.runId, "run-abc");
    assert.equal(t.activeRun.phase, "running");
  });

  it("run/completed clears activeRun", () => {
    store.applyWireEvent("run/started", { thread_id: "t1", run_id: "run-1", seq: 1 });
    store.applyWireEvent("run/completed", { thread_id: "t1", seq: 2 });
    const t = store.ensureThread("t1");
    assert.equal(t.activeRun, null);
    assert.equal(t.status, "idle");
  });

  // ── Late events from an OLD run (Gate 1, 二-5) ───────────────────

  it("late delta from an OLD run does not split the NEW run's stream", () => {
    // Stream: new:A → old:OLD (late) → new:B.  The new run must stay ONE
    // continuous item "AB"; the old run's delta gets its OWN item and must
    // not steal the open slot of the new run.
    store.applyWireEvent("TextDelta", {
      thread_id: "t1", run_id: "run-new", seq: 1, text: "A",
    });
    store.applyWireEvent("TextDelta", {
      thread_id: "t1", run_id: "run-old", seq: 2, text: "OLD",
    });
    store.applyWireEvent("TextDelta", {
      thread_id: "t1", run_id: "run-new", seq: 3, text: "B",
    });

    const t = store.ensureThread("t1");
    const asst = t.items.filter((i) => i.kind === "assistant_message");
    assert.equal(asst.length, 2);
    const newItem = asst.find((i) => String(i.payload.text).includes("A"));
    assert.equal(String(newItem.payload.text), "AB"); // Continuous stream
    const oldItem = asst.find((i) => String(i.payload.text).includes("OLD"));
    assert.equal(String(oldItem.payload.text), "OLD"); // Own item, own text
  });

  it("interleaved text/reasoning deltas keep TWO continuous streams per run", () => {
    // Reasoning A → Text B → Reasoning C → Text D: each stream of the
    // SAME run must stay continuous (regression: one open slot per run
    // split the streams into separate items).
    store.applyWireEvent("ReasoningDelta", {
      thread_id: "t1", run_id: "run-1", seq: 1, text: "A",
    });
    store.applyWireEvent("TextDelta", {
      thread_id: "t1", run_id: "run-1", seq: 2, text: "B",
    });
    store.applyWireEvent("ReasoningDelta", {
      thread_id: "t1", run_id: "run-1", seq: 3, text: "C",
    });
    store.applyWireEvent("TextDelta", {
      thread_id: "t1", run_id: "run-1", seq: 4, text: "D",
    });

    const t = store.ensureThread("t1");
    const reas = t.items.filter((i) => i.kind === "reasoning");
    const asst = t.items.filter((i) => i.kind === "assistant_message");
    assert.equal(reas.length, 1);
    assert.equal(String(reas[0].payload.text), "AC"); // Continuous reasoning stream
    assert.equal(asst.length, 1);
    assert.equal(String(asst[0].payload.text), "BD"); // Continuous text stream
  });

  it("late RunEnd from an OLD run keeps the NEW run's active marker", () => {
    store.applyWireEvent("RunBegin", { thread_id: "t1", run_id: "run-new", seq: 1 });
    store.applyWireEvent("TextDelta", {
      thread_id: "t1", run_id: "run-new", seq: 2, text: "A",
    });
    // Old run's RunEnd arrives AFTER the new run began
    store.applyWireEvent("RunEnd", { thread_id: "t1", run_id: "run-old", seq: 3 });
    let t = store.ensureThread("t1");
    assert.equal(t.activeRun.runId, "run-new"); // Still the new run
    assert.equal(t.status, "running");

    store.applyWireEvent("TextDelta", {
      thread_id: "t1", run_id: "run-new", seq: 4, text: "B",
    });
    t = store.ensureThread("t1");
    const asst = t.items.filter((i) => i.kind === "assistant_message");
    assert.equal(asst.length, 1);
    assert.equal(String(asst[0].payload.text), "AB");
  });

  it("RunEnd for the CURRENT run clears the active marker and stream", () => {
    store.applyWireEvent("RunBegin", { thread_id: "t1", run_id: "run-1", seq: 1 });
    store.applyWireEvent("TextDelta", {
      thread_id: "t1", run_id: "run-1", seq: 2, text: "done",
    });
    store.applyWireEvent("RunEnd", { thread_id: "t1", run_id: "run-1", seq: 3 });
    const t = store.ensureThread("t1");
    assert.equal(t.activeRun, null);
    assert.equal(t.status, "idle");
  });

  // ── item/* ───────────────────────────────────────────────────────

  it("item/started appends to items", () => {
    store.applyWireEvent("item/started", {
      thread_id: "t1",
      item_id: "item-001",
      kind: "assistant_message",
      seq: 1,
    });
    const t = store.ensureThread("t1");
    assert.equal(t.items.length, 1);
    assert.equal(t.items[0].id, "item-001");
    assert.equal(t.items[0].kind, "assistant_message");
  });

  it("item/completed appends to items", () => {
    store.applyWireEvent("item/completed", {
      thread_id: "t1",
      item_id: "item-002",
      kind: "tool_result",
      seq: 1,
      payload: { content: "done" },
    });
    const t = store.ensureThread("t1");
    assert.equal(t.items.length, 1);
    assert.equal(t.items[0].payload.content, "done");
  });

  it("duplicate item event is not re-appended", () => {
    store.applyWireEvent("item/started", {
      thread_id: "t1",
      event_id: "evt-dup",
      item_id: "item-x",
      seq: 1,
    });
    store.applyWireEvent("item/started", {
      thread_id: "t1",
      event_id: "evt-dup",
      item_id: "item-x",
      seq: 1,
    });
    assert.equal(store.ensureThread("t1").items.length, 1);
  });

  // ── approval/* ───────────────────────────────────────────────────

  it("approval/requested adds to pendingPermits", () => {
    store.applyWireEvent("approval/requested", {
      thread_id: "t1",
      run_id: "run-1",
      tool_call_id: "tc-1",
      tool_name: "run_command",
      arguments: JSON.stringify({ cmd: "rm -rf /" }),
      seq: 1,
    });
    const t = store.ensureThread("t1");
    assert.equal(t.pendingPermits.length, 1);
    assert.equal(t.pendingPermits[0].toolCallId, "tc-1");
    assert.equal(t.pendingPermits[0].threadId, "t1");
    assert.equal(t.pendingPermits[0].runId, "run-1");
  });

  it("approval/resolved removes from pendingPermits", () => {
    store.applyWireEvent("approval/requested", {
      thread_id: "t1",
      tool_call_id: "tc-1",
      seq: 1,
    });
    // The real backend emits both approval_id and tool_call_id
    store.applyWireEvent("approval/resolved", {
      thread_id: "t1",
      approval_id: "apr-1",
      tool_call_id: "tc-1",
      seq: 2,
    });
    assert.equal(store.ensureThread("t1").pendingPermits.length, 0);
  });

  it("approval for thread A does not affect thread B", () => {
    store.applyWireEvent("approval/requested", {
      thread_id: "a",
      tool_call_id: "tc-a",
      seq: 1,
    });
    store.applyWireEvent("approval/requested", {
      thread_id: "b",
      tool_call_id: "tc-b",
      seq: 1,
    });
    store.applyWireEvent("approval/resolved", {
      thread_id: "a",
      approval_id: "apr-a",
      tool_call_id: "tc-a",
      seq: 2,
    });
    assert.equal(store.ensureThread("a").pendingPermits.length, 0);
    assert.equal(store.ensureThread("b").pendingPermits.length, 1);
  });

  // ── Snapshot recovery ────────────────────────────────────────────

  it("applySnapshot recovers active run", () => {
    store.applySnapshot({
      thread_id: "t1",
      active_run_id: "run-recover",
      active_run_phase: "running",
      status: "running",
      last_seq: 42,
    });
    const t = store.ensureThread("t1");
    assert.equal(t.lastEventSeq, 42);
    assert.equal(t.activeRun.runId, "run-recover");
    assert.equal(t.status, "running");
  });

  it("applySnapshot recovers idle state", () => {
    store.applySnapshot({
      thread_id: "t2",
      status: "idle",
      last_seq: 10,
    });
    const t = store.ensureThread("t2");
    assert.equal(t.status, "idle");
    assert.equal(t.activeRun, null);
  });

  // ── End-to-end: full run lifecycle ───────────────────────────────

  it("full run lifecycle: start → items → complete", () => {
    // Run starts
    store.applyWireEvent("run/started", {
      thread_id: "t1",
      run_id: "run-lifecycle",
      seq: 1,
    });
    assert.equal(store.ensureThread("t1").status, "running");

    // Items arrive
    store.applyWireEvent("item/started", {
      thread_id: "t1",
      item_id: "item-1",
      kind: "assistant_message",
      seq: 2,
    });
    store.applyWireEvent("item/completed", {
      thread_id: "t1",
      item_id: "item-2",
      kind: "tool_result",
      seq: 3,
    });

    // Run completes
    store.applyWireEvent("run/completed", { thread_id: "t1", seq: 4 });
    assert.equal(store.ensureThread("t1").status, "idle");
    assert.equal(store.ensureThread("t1").activeRun, null);
    // D3.3.1: run lifecycle persists as items (run_begin + run_end) so
    // terminal state survives snapshot restore.
    assert.equal(store.ensureThread("t1").items.length, 4);
    const kinds = store.ensureThread("t1").items.map((i) => i.kind);
    assert.deepEqual(kinds, ["run_begin", "assistant_message", "tool_result", "run_end"]);
  });
});

// ── Optimistic local input (single source of truth) ───────────────────

describe("optimistic input", () => {
  let store;

  beforeEach(() => {
    resetThreadStore();
    store = getThreadStore();
  });

  it("addOptimisticInput creates an accepted user item with request_id id", () => {
    store.addOptimisticInput("t1", "req-abc123", "hello");
    const t = store.ensureThread("t1");
    assert.equal(t.items.length, 1);
    assert.equal(t.items[0].id, "req-abc123");
    assert.equal(t.items[0].kind, "user_message");
    assert.equal(t.items[0].payload.state, "accepted");
  });

  it("addOptimisticInput upserts on retry (no duplicate)", () => {
    store.addOptimisticInput("t1", "req-abc123", "hello");
    store.addOptimisticInput("t1", "req-abc123", "hello");
    assert.equal(store.ensureThread("t1").items.length, 1);
  });

  it("reconcileInput re-keys request_id → message_id and sets state", () => {
    store.addOptimisticInput("t1", "req-abc123", "hello");
    store.reconcileInput("t1", "msg-real-1", "queued", "req-abc123");
    const t = store.ensureThread("t1");
    assert.equal(t.items.length, 1);
    assert.equal(t.items[0].id, "msg-real-1");
    assert.equal(t.items[0].payload.state, "queued");
  });

  it("reconcileInput updates state in place when ids match", () => {
    store.addOptimisticInput("t1", "msg-real-1", "hello");
    store.reconcileInput("t1", "msg-real-1", "applied");
    const t = store.ensureThread("t1");
    assert.equal(t.items.length, 1);
    assert.equal(t.items[0].payload.state, "applied");
  });

  it("reconcileInput never duplicates across ACKs", () => {
    store.addOptimisticInput("t1", "req-abc123", "hello");
    store.reconcileInput("t1", "msg-real-1", "queued", "req-abc123");
    store.reconcileInput("t1", "msg-real-1", "applied", "req-abc123");
    store.reconcileInput("t1", "msg-real-1", "applied");
    assert.equal(store.ensureThread("t1").items.length, 1);
    assert.equal(store.ensureThread("t1").items[0].payload.state, "applied");
  });
});

// ── FileChange hunks preservation ──────────────────────────────────────

describe("FileChange hunks", () => {
  let store;

  beforeEach(() => {
    resetThreadStore();
    store = getThreadStore();
  });

  it("preserves real hunks in the thread item payload", () => {
    store.applyWireEvent("FileChange", {
      thread_id: "t1",
      seq: 1,
      path: "src/main.py",
      status: "modified",
      additions: 2,
      deletions: 1,
      tool_call_id: "tc-1",
      run_id: "run-1",
      hunks: [
        {
          header: "@@ -1,1 +1,2 @@",
          lines: [
            { kind: "deletion", content: "old line" },
            { kind: "addition", content: "new line 1" },
            { kind: "addition", content: "new line 2" },
          ],
        },
      ],
    });
    const t = store.ensureThread("t1");
    assert.equal(t.items.length, 1);
    const item = t.items[0];
    assert.equal(item.kind, "file_change");
    const payload = item.payload;
    assert.ok(Array.isArray(payload.hunks), "hunks must be preserved");
    assert.equal(payload.hunks.length, 1);
    const hunk = payload.hunks[0];
    assert.equal(hunk.header, "@@ -1,1 +1,2 @@");
    const lines = hunk.lines;
    assert.equal(lines[0].content, "old line");
    assert.equal(lines[2].content, "new line 2");
  });

  it("FileChange without hunks stores an empty array", () => {
    store.applyWireEvent("FileChange", {
      thread_id: "t1",
      seq: 1,
      path: "data.txt",
    });
    const item = store.ensureThread("t1").items[0];
    assert.deepStrictEqual(
      item.payload.hunks,
      [],
    );
  });
});
