/** D3.3 renderer adapter tests — projected TimelineItem[] maps onto the
 *  exact item shapes the existing MessageRenderer draws (visual parity).
 */

import { describe, it, beforeEach } from "node:test";
import assert from "node:assert/strict";

// Feature gate reads window.localStorage — stub it per test.
let storedValue = null;
globalThis.window = {
  localStorage: {
    getItem: () => storedValue,
    setItem: () => {},
  },
};

const { timelineProjectionEnabled, timelineToRenderItems } = await import(
  new URL("../src/renderer/timeline-adapter.ts", import.meta.url)
);

describe("timeline adapter", () => {
  beforeEach(() => {
    storedValue = null;
  });

  const T = "t-1";
  const tl = (items) => timelineToRenderItems(items);

  it("passes user and assistant messages through", () => {
    const out = tl([
      { id: "u-1", kind: "user_message", threadId: T, timestamp: 1, text: "hi" },
      { id: "a-1", kind: "assistant_message", threadId: T, timestamp: 2, text: "hello" },
    ]);
    assert.deepEqual(
      out.map((i) => [i.kind, i.payload.text]),
      [
        ["user_message", "hi"],
        ["assistant_message", "hello"],
      ],
    );
  });

  it("reasoning marker maps back to the reasoning block", () => {
    const out = tl([
      { id: "r-1", kind: "assistant_message", threadId: T, timestamp: 1, text: "think", reasoning: true },
    ]);
    assert.equal(out.length, 1);
    assert.equal(out[0].kind, "reasoning");
    assert.equal(out[0].payload.text, "think");
  });

  it("group actions become tool_call items with stable ids and status mapping", () => {
    const out = tl([
      {
        id: "group:r-1",
        kind: "activity_group",
        threadId: T,
        owner: "main",
        runId: "r-1",
        status: "running",
        startedAt: 10,
        actions: [
          { id: "action:tc-1", toolCallId: "tc-1", kind: "tool", title: "read_file", status: "running" },
          { id: "action:tc-2", toolCallId: "tc-2", kind: "tool", title: "write_file", status: "completed", durationMs: 1500, exitCode: 0 },
          { id: "action:tc-3", toolCallId: "tc-3", kind: "tool", title: "run_cmd", status: "failed", detail: "boom", exitCode: 2 },
        ],
      },
    ]);
    assert.equal(out.length, 3);
    assert.deepEqual(
      out.map((i) => [i.id, i.kind, i.payload.status]),
      [
        ["action:tc-1", "tool_call", "running"],
        ["action:tc-2", "tool_call", "done"],
        ["action:tc-3", "tool_call", "error"],
      ],
    );
    assert.equal(out[1].payload.duration_seconds, 1.5);
    assert.equal(out[2].payload.content, "boom");
    assert.equal(out[2].payload.exit_code, 2);
    // stable ids keep the renderer's upgrade refresh working
    assert.equal(new Set(out.map((i) => i.id)).size, 3);
  });

  it("command actions render as tool cards with the command as title", () => {
    const out = tl([
      {
        id: "group:r-1",
        kind: "activity_group",
        threadId: T,
        owner: "main",
        status: "completed",
        startedAt: 1,
        actions: [{ id: "action:cmd-1", kind: "command", title: "cp2k.popt -c water64.inp", status: "completed", durationMs: 5000 }],
      },
    ]);
    assert.equal(out[0].kind, "tool_call");
    assert.equal(out[0].payload.name, "cp2k.popt -c water64.inp");
    assert.equal(out[0].payload.status, "done");
  });

  it("cancelled actions stay running (parity: no result card arrives today)", () => {
    const out = tl([
      {
        id: "group:r-1",
        kind: "activity_group",
        threadId: T,
        owner: "main",
        status: "cancelled",
        startedAt: 1,
        actions: [{ id: "action:tc-1", toolCallId: "tc-1", kind: "tool", title: "x", status: "cancelled" }],
      },
    ]);
    assert.equal(out[0].payload.status, "running");
  });

  it("file_change actions pass through as file_change items (default-path parity)", () => {
    const out = tl([
      {
        id: "group:r-1",
        kind: "activity_group",
        threadId: T,
        owner: "main",
        status: "completed",
        startedAt: 1,
        actions: [{ id: "action:fc-1", kind: "file_change", title: "water64.xyz", status: "completed" }],
      },
    ]);
    assert.equal(out[0].kind, "file_change");
    assert.equal(out[0].payload.path, "water64.xyz");
  });

  it("artifact actions and one-level plan/job/artifact/approval/recovery items are skipped", () => {
    const out = tl([
      {
        id: "group:r-1",
        kind: "activity_group",
        threadId: T,
        owner: "main",
        status: "completed",
        startedAt: 1,
        actions: [{ id: "action:art-1", kind: "artifact", title: "o1.xyz", status: "completed" }],
      },
      { id: "plan:fp-1", kind: "plan", threadId: T, timestamp: 1, planId: "p-1", version: 1, status: "proposed", objective: "", steps: [] },
      { id: "job:j-1", kind: "job", threadId: T, timestamp: 1, jobId: "j-1", state: "RUNNING" },
      { id: "artifact:/p/o1", kind: "artifact", threadId: T, timestamp: 1, artifactId: "/p/o1", path: "/p/o1", status: "created" },
      { id: "approval:tc-1", kind: "approval", threadId: T, timestamp: 1, toolCallId: "tc-1", toolName: "x", status: "pending" },
      { id: "rec-1", kind: "recovery", threadId: T, timestamp: 1, message: "reconnected" },
    ]);
    assert.equal(out.length, 0);
  });

  it("error items map to error banners", () => {
    const out = tl([
      { id: "e-1", kind: "error", threadId: T, timestamp: 1, message: "boom" },
    ]);
    assert.equal(out[0].kind, "error");
    assert.equal(out[0].payload.message, "boom");
  });

  it("feature gate: v2 default; localStorage v1 opts out", () => {
    assert.equal(timelineProjectionEnabled(), true);
    storedValue = "v1";
    assert.equal(timelineProjectionEnabled(), false);
    storedValue = "v2";
    assert.equal(timelineProjectionEnabled(), true);
  });
});
