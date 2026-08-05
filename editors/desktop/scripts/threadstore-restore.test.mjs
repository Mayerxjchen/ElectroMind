/** D3.3.1 restore-completeness tests — terminal timeline facts survive
 *  snapshot restore.
 *
 *  Principle: the timeline is DERIVED data.  Terminal facts (run
 *  ended/cancelled, approval permitted/denied) persist as ThreadItems,
 *  and snapshot restore re-projects them, so:
 *
 *    timelineFromLiveFeed === timelineFromSnapshot === timelineFromFullReplay
 *
 *  Node 25 type-strips .ts; DOM stubbed like the other store tests.
 */

import { describe, it, beforeEach } from "node:test";
import assert from "node:assert/strict";

globalThis.window = {
  localStorage: {
    getItem: () => null,
    setItem: () => {},
  },
};

const { getThreadStore, resetThreadStore } = await import(
  new URL("../src/renderer/store/ThreadStore.ts", import.meta.url)
);

const { projectTimeline } = await import(
  new URL("../src/renderer/timeline-projection.ts", import.meta.url)
);

describe("ThreadStore terminal-state restore", () => {
  /** @type {import("../src/renderer/store/ThreadStore.ts").ThreadStore} */
  let store;

  beforeEach(() => {
    resetThreadStore();
    store = getThreadStore();
  });

  /** Serialize a live thread's items into the backend-history shape
   *  historyToItem understands (kinds + flat fields + timestamps). */
  function serializeItems(threadId) {
    return store.ensureThread(threadId).items.map((it) => {
      const p = it.payload ?? {};
      switch (it.kind) {
        case "user_message":
          return { kind: "text", role: "user", text: String(p.text ?? ""), timestamp: it.timestamp };
        case "assistant_message":
          return {
            kind: "text",
            role: "assistant",
            id: it.id,
            text: String(p.text ?? ""),
            streaming: p.streaming,
            timestamp: it.timestamp,
          };
        case "reasoning":
          return {
            kind: "thinking",
            id: it.id,
            text: String(p.text ?? ""),
            streaming: p.streaming,
            timestamp: it.timestamp,
          };
        case "tool_call":
          return {
            kind: "tool_call",
            id: it.id,
            tool_call_id: p.tool_call_id,
            name: p.name,
            arguments: p.arguments,
            run_id: p.run_id,
            status: p.status,
            content: p.content,
            exit_code: p.exit_code,
            duration_seconds: p.duration_seconds,
            timestamp: it.timestamp,
          };
        case "tool_result":
          return { kind: "tool_result", tool_call_id: p.tool_call_id, content: p.content, timestamp: it.timestamp };
        case "approval":
          return {
            kind: "approval",
            id: it.id,
            tool_call_id: p.tool_call_id,
            name: p.name,
            arguments: p.arguments,
            status: p.status,
            timestamp: it.timestamp,
          };
        case "run_begin":
        case "run_end":
        case "run_cancelled":
          return { kind: it.kind, id: it.id, run_id: p.run_id, timestamp: it.timestamp };
        default:
          return { kind: it.kind, timestamp: it.timestamp, ...p };
      }
    });
  }

  /** Restore into a FRESH store via applySnapshot with only items. */
  function restoreFrom(records) {
    resetThreadStore();
    store = getThreadStore();
    store.applySnapshot({ thread_id: "t1", items: records });
    return store.ensureThread("t1").timeline;
  }

  /** Full replay of the same records as projection sources. */
  function fullReplay(records, threadId = "t1") {
    const sources = records.map((r, i) => {
      const p = { ...r };
      delete p.kind;
      delete p.id;
      delete p.timestamp;
      delete p.role;
      delete p.text;
      return {
        id: String(r.id ?? `hist-${i}`),
        kind:
          r.kind === "text"
            ? r.role === "user"
              ? "user_message"
              : "assistant_message"
            : r.kind === "thinking"
              ? "reasoning"
              : r.kind,
        threadId,
        timestamp: r.timestamp,
        payload: { ...p, text: r.text },
      };
    });
    return projectTimeline(sources, {}, threadId).timeline;
  }

  const run = (id, runId = "r-1") => ({ thread_id: "t1", seq: id, run_id: runId });

  it("completed run: group stays completed after restore (A≡B≡C)", () => {
    store.applyWireEvent("RunBegin", run(1));
    store.applyWireEvent("ToolCallBegin", { ...run(2), tool_call_id: "tc-1", name: "read_file", arguments: "{}" });
    store.applyWireEvent("ToolResult", { ...run(3), tool_call_id: "tc-1", ok: true });
    store.applyWireEvent("TextDelta", { ...run(4), text: "done" });
    store.applyWireEvent("RunEnd", run(5));
    const live = store.ensureThread("t1").timeline;

    const records = serializeItems("t1");
    const restored = restoreFrom(records);
    const replayed = fullReplay(records);
    assert.deepEqual(restored, live, "snapshot restore equals live feed");
    assert.deepEqual(replayed, live, "full replay equals live feed");
    const group = restored.find((i) => i.kind === "activity_group");
    assert.equal(group.status, "completed", "completed run survives restore");
    assert.ok(group.endedAt, "endedAt survives restore");
  });

  it("cancelled run: group stays cancelled after restore", () => {
    store.applyWireEvent("run/started", run(1));
    store.applyWireEvent("ToolCallBegin", { ...run(2), tool_call_id: "tc-1", name: "x", arguments: "{}" });
    store.applyWireEvent("run/cancelled", run(3));
    const live = store.ensureThread("t1").timeline;

    const records = serializeItems("t1");
    const restored = restoreFrom(records);
    assert.deepEqual(restored, live);
    assert.equal(restored.find((i) => i.kind === "activity_group").status, "cancelled");
  });

  it("failed run: group stays failed after restore (tool error)", () => {
    store.applyWireEvent("RunBegin", run(1));
    store.applyWireEvent("ToolCallBegin", { ...run(2), tool_call_id: "tc-1", name: "run_command", arguments: "{}" });
    store.applyWireEvent("ToolResult", { ...run(3), tool_call_id: "tc-1", ok: false, content: "boom", exit_code: 2 });
    const live = store.ensureThread("t1").timeline;

    const records = serializeItems("t1");
    const restored = restoreFrom(records);
    assert.deepEqual(restored, live);
    const group = restored.find((i) => i.kind === "activity_group");
    assert.equal(group.status, "failed");
    assert.equal(group.actions[0].status, "failed");
  });

  it("permitted approval: does NOT come back as pending after restore", () => {
    store.applyWireEvent("RunBegin", run(1));
    store.applyWireEvent("PermitRequest", { ...run(2), tool_call_id: "tc-9", name: "run_command", arguments: "{}" });
    store.applyWireEvent("approval/resolved", { ...run(3), tool_call_id: "tc-9", allowed: true });
    const live = store.ensureThread("t1").timeline;
    assert.equal(live.find((i) => i.kind === "approval").status, "approved");

    const records = serializeItems("t1");
    const restored = restoreFrom(records);
    assert.deepEqual(restored, live);
    const approval = restored.find((i) => i.kind === "approval");
    assert.equal(approval.status, "approved", "never re-pending");
    assert.equal(approval.toolCallId, "tc-9");
  });

  it("denied approval: does NOT come back as pending after restore", () => {
    store.applyWireEvent("PermitRequest", { thread_id: "t1", seq: 1, tool_call_id: "tc-9", name: "run_command", arguments: "{}" });
    store.applyWireEvent("approval/resolved", { thread_id: "t1", seq: 2, tool_call_id: "tc-9", status: "denied" });
    const records = serializeItems("t1");
    const restored = restoreFrom(records);
    assert.equal(restored.find((i) => i.kind === "approval").status, "denied");
  });

  it("timeline IDs are identical across live/restore/replay", () => {
    store.applyWireEvent("RunBegin", run(1));
    store.applyWireEvent("ToolCallBegin", { ...run(2), tool_call_id: "tc-1", name: "x", arguments: "{}" });
    store.applyWireEvent("ToolResult", { ...run(3), tool_call_id: "tc-1", ok: true });
    store.applyWireEvent("PermitRequest", { ...run(4), tool_call_id: "tc-1", name: "x", arguments: "{}" });
    store.applyWireEvent("approval/resolved", { ...run(5), tool_call_id: "tc-1", allowed: true });
    store.applyWireEvent("TextDelta", { ...run(6), text: "done" });
    store.applyWireEvent("RunEnd", run(7));
    const live = store.ensureThread("t1").timeline;
    const liveIds = live.map((i) => i.id);

    const records = serializeItems("t1");
    const restored = restoreFrom(records);
    const replayed = fullReplay(records);
    assert.deepEqual(
      restored.map((i) => i.id),
      liveIds,
      "restore keeps identical ids",
    );
    assert.deepEqual(replayed.map((i) => i.id), liveIds);
    assert.equal(new Set(liveIds).size, liveIds.length, "ids unique");
  });

  it("re-applying the snapshot is idempotent (no duplicates)", () => {
    store.applyWireEvent("RunBegin", run(1));
    store.applyWireEvent("ToolCallBegin", { ...run(2), tool_call_id: "tc-1", name: "x", arguments: "{}" });
    store.applyWireEvent("ToolResult", { ...run(3), tool_call_id: "tc-1", ok: true });
    store.applyWireEvent("RunEnd", run(4));
    const records = serializeItems("t1");

    const first = restoreFrom(records);
    const second = restoreFrom(records);
    assert.deepEqual(second, first);
    const toolCount = second
      .filter((i) => i.kind === "activity_group")
      .flatMap((g) => g.actions)
      .filter((a) => a.kind === "tool").length;
    assert.equal(toolCount, 1);
  });

  it("re-receiving a terminal event after restore stays idempotent", () => {
    store.applyWireEvent("RunBegin", run(1));
    store.applyWireEvent("ToolCallBegin", { ...run(2), tool_call_id: "tc-1", name: "x", arguments: "{}" });
    store.applyWireEvent("RunEnd", run(3));
    const records = serializeItems("t1");
    const restored = restoreFrom(records);
    const before = JSON.stringify(restored);

    // Duplicate terminal event (deduped by seq at the wire layer)
    store.applyWireEvent("RunEnd", run(3));
    assert.equal(JSON.stringify(store.ensureThread("t1").timeline), before);

    // New terminal event for the same already-closed run — no new cards
    store.applyWireEvent("run/completed", { thread_id: "t1", seq: 10, run_id: "r-1" });
    const after = store.ensureThread("t1").timeline;
    assert.equal(
      after.filter((i) => i.kind === "activity_group").length,
      restored.filter((i) => i.kind === "activity_group").length,
      "no duplicate groups from repeated terminal events",
    );
  });
});
