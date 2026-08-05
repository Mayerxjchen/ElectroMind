/** D3.3 store integration tests — ThreadStore projects wire events into
 *  ThreadState.timeline (incremental feed) and rebuilds it from
 *  snapshots (full replay), with deterministic ids and no duplicates.
 *
 *  Node 25 type-strips .ts; DOM stubbed like threadstore-protocol-v2.
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

describe("ThreadStore timeline projection", () => {
  /** @type {import("../src/renderer/store/ThreadStore.ts").ThreadStore} */
  let store;

  beforeEach(() => {
    resetThreadStore();
    store = getThreadStore();
  });

  const ev = (method, params) => store.applyWireEvent(method, params);

  it("ToolCallBegin + ToolResult → one group with one completed action", () => {
    const p = { thread_id: "t1", seq: 1, run_id: "r-1" };
    ev("RunBegin", { ...p, run_id: "r-1" });
    ev("ToolCallBegin", {
      ...p,
      seq: 2,
      tool_call_id: "tc-1",
      name: "read_file",
      arguments: "{}",
    });
    ev("ToolResult", {
      ...p,
      seq: 3,
      tool_call_id: "tc-1",
      content: "ok",
      duration_seconds: 2,
      exit_code: 0,
      ok: true,
    });
    const t = store.ensureThread("t1");
    const groups = t.timeline.filter((i) => i.kind === "activity_group");
    assert.equal(groups.length, 1);
    assert.equal(groups[0].runId, "r-1");
    assert.equal(groups[0].actions.length, 1);
    assert.equal(groups[0].actions[0].status, "completed");
    assert.equal(groups[0].actions[0].durationMs, 2000);
  });

  it("TextDelta accumulates into ONE assistant item; closes the group", () => {
    const p = { thread_id: "t1", seq: 1, run_id: "r-1" };
    ev("RunBegin", p);
    ev("ToolCallBegin", { ...p, seq: 2, tool_call_id: "tc-1", name: "prep", arguments: "{}" });
    ev("ToolResult", { ...p, seq: 3, tool_call_id: "tc-1", ok: true });
    ev("TextDelta", { ...p, seq: 4, text: "正在" });
    ev("TextDelta", { ...p, seq: 5, text: "处理" });
    const t = store.ensureThread("t1");
    const messages = t.timeline.filter((i) => i.kind === "assistant_message");
    assert.equal(messages.length, 1, "deltas merge into one item");
    assert.equal(messages[0].text, "正在处理");
    const groups = t.timeline.filter((i) => i.kind === "activity_group");
    assert.equal(groups[0].status, "completed", "assistant text ends the group");
  });

  it("approval requested → pending item; resolved → same item updated", () => {
    const p = { thread_id: "t1", seq: 1 };
    ev("PermitRequest", {
      ...p,
      seq: 2,
      tool_call_id: "tc-9",
      name: "run_command",
      arguments: "{}",
      summary: "run cp2k",
      risk: "medium",
      workdir: "/p",
    });
    ev("approval/resolved", { ...p, seq: 3, tool_call_id: "tc-9", allowed: true });
    const t = store.ensureThread("t1");
    const approvals = t.timeline.filter((i) => i.kind === "approval");
    assert.equal(approvals.length, 1, "never appended twice");
    assert.equal(approvals[0].status, "approved");
    assert.equal(approvals[0].toolCallId, "tc-9");
  });

  it("plan/state and artifact/state project first-class items", () => {
    const p = { thread_id: "t1", seq: 1 };
    ev("plan/state", {
      ...p,
      seq: 2,
      plan: {
        plan_id: "pl-1",
        fingerprint: "fp-1",
        version: 1,
        status: "proposed",
        objective: "run water64",
        steps: [{ id: "s1", title: "Prepare", status: "pending" }],
        created_at: 1000,
      },
    });
    ev("artifact/state", {
      ...p,
      seq: 3,
      artifacts: [
        { artifact_id: "a-1", path: "/p/o1.xyz", status: "completed", acceptance_status: "created", created_at: 2000 },
      ],
    });
    const t = store.ensureThread("t1");
    const plans = t.timeline.filter((i) => i.kind === "plan");
    assert.equal(plans.length, 1);
    assert.equal(plans[0].id, "plan:fp-1");
    assert.equal(plans[0].objective, "run water64");
    const artifacts = t.timeline.filter((i) => i.kind === "artifact");
    assert.equal(artifacts.length, 1);
    assert.equal(artifacts[0].id, "artifact:/p/o1.xyz");
  });

  it("run/completed closes the open group", () => {
    const p = { thread_id: "t1", seq: 1, run_id: "r-1" };
    ev("RunBegin", p);
    ev("ToolCallBegin", { ...p, seq: 2, tool_call_id: "tc-1", name: "x", arguments: "{}" });
    ev("RunEnd", { ...p, seq: 3, run_id: "r-1" });
    const groups = store.ensureThread("t1").timeline.filter((i) => i.kind === "activity_group");
    assert.equal(groups[0].status, "completed");
  });

  it("threads never mix timelines", () => {
    const pa = { thread_id: "a", seq: 1, run_id: "ra" };
    const pb = { thread_id: "b", seq: 1, run_id: "rb" };
    ev("RunBegin", pa);
    ev("RunBegin", pb);
    ev("ToolCallBegin", { ...pa, seq: 2, tool_call_id: "tc-a", name: "a", arguments: "{}" });
    ev("ToolCallBegin", { ...pb, seq: 2, tool_call_id: "tc-b", name: "b", arguments: "{}" });
    const ta = store.ensureThread("a");
    const tb = store.ensureThread("b");
    assert.equal(ta.timeline.filter((i) => i.kind === "activity_group").length, 1);
    assert.equal(tb.timeline.filter((i) => i.kind === "activity_group").length, 1);
    assert.equal(
      ta.timeline.filter((i) => i.kind === "activity_group")[0].actions[0].title,
      "a",
    );
    assert.equal(
      tb.timeline.filter((i) => i.kind === "activity_group")[0].actions[0].title,
      "b",
    );
  });

  it("duplicate wire events (event_id) do not duplicate timeline items", () => {
    const p = { thread_id: "t1", seq: 1, run_id: "r-1", event_id: "e-1" };
    ev("RunBegin", p);
    ev("ToolCallBegin", {
      ...p,
      seq: 2,
      event_id: "e-2",
      tool_call_id: "tc-1",
      name: "x",
      arguments: "{}",
    });
    // Same event_id re-sent → deduped before any feed
    ev("ToolCallBegin", {
      ...p,
      seq: 2,
      event_id: "e-2",
      tool_call_id: "tc-1",
      name: "x",
      arguments: "{}",
    });
    const t = store.ensureThread("t1");
    const groups = t.timeline.filter((i) => i.kind === "activity_group");
    assert.equal(groups.length, 1);
    assert.equal(groups[0].actions.length, 1);
  });

  it("addOptimisticInput projects a user message and ends the group", () => {
    const p = { thread_id: "t1", seq: 1, run_id: "r-1" };
    ev("RunBegin", p);
    ev("ToolCallBegin", { ...p, seq: 2, tool_call_id: "tc-1", name: "x", arguments: "{}" });
    store.addOptimisticInput("t1", "req-1", "继续");
    const t = store.ensureThread("t1");
    const users = t.timeline.filter((i) => i.kind === "user_message");
    assert.equal(users.length, 1);
    assert.equal(users[0].text, "继续");
    assert.equal(
      t.timeline.filter((i) => i.kind === "activity_group")[0].status,
      "completed",
    );
  });

  it("snapshot restore rebuilds the timeline without duplicates (resume)", () => {
    // Live session shape for reference
    const p = { thread_id: "t1", seq: 1, run_id: "r-1" };
    ev("RunBegin", p);
    ev("ToolCallBegin", { ...p, seq: 2, tool_call_id: "tc-1", name: "read_file", arguments: "{}" });
    ev("ToolResult", { ...p, seq: 3, tool_call_id: "tc-1", ok: true });
    ev("TextDelta", { ...p, seq: 4, text: "done" });

    // Simulated resume: fresh store + applySnapshot with persisted state
    resetThreadStore();
    store = getThreadStore();
    const item = (id, kind, payload) => ({
      id,
      kind,
      role: kind === "user_message" ? "user" : "assistant",
      text: String(payload.text ?? ""),
      tool_call_id: payload.tool_call_id,
      name: payload.name,
      arguments: payload.arguments,
      content: payload.content,
      status: payload.status,
      run_id: payload.run_id,
    });
    const snap = {
      thread_id: "t1",
      items: [
        item("tool-tc-1", "tool_call", { tool_call_id: "tc-1", name: "read_file", status: "done", run_id: "r-1" }),
        item("asst-1", "assistant_message", { text: "done" }),
      ],
    };
    store.applySnapshot(snap);
    const resumed = store.ensureThread("t1");
    // Structural equality: group bound to the same run, same action set,
    // no duplicate tool actions.  (Message ids derive from stream ids and
    // differ across resume by design — the persisted timeline itself is
    // the resume source of truth.)
    const rGroups = resumed.timeline.filter((i) => i.kind === "activity_group");
    assert.equal(rGroups.length, 1);
    assert.equal(rGroups[0].id, "group:r-1");
    assert.equal(rGroups[0].actions.length, 1);
    assert.equal(rGroups[0].actions[0].status, "completed");
    const toolActions = rGroups.flatMap((g) => g.actions).filter((a) => a.kind === "tool");
    assert.equal(new Set(toolActions.map((a) => a.toolCallId)).size, 1, "no duplicate tool");
    assert.equal(
      resumed.timeline.filter((i) => i.kind === "assistant_message").length,
      1,
    );
    // Idempotent: applying the same snapshot again changes nothing
    const before = JSON.stringify(resumed.timeline);
    store.applySnapshot(snap);
    assert.equal(JSON.stringify(resumed.timeline), before);
  });

  it("HistoryReplay rebuilds from the history list", () => {
    ev("RunBegin", { thread_id: "t1", seq: 1, run_id: "r-1" });
    ev("ToolCallBegin", { thread_id: "t1", seq: 2, tool_call_id: "tc-1", name: "x", arguments: "{}" });
    store.applyWireEvent("HistoryReplay", {
      thread_id: "t1",
      messages: [
        { kind: "text", role: "user", text: "hello" },
        { kind: "tool_call", tool_call_id: "tc-9", name: "prep", arguments: "{}" },
      ],
    });
    const t = store.ensureThread("t1");
    const kinds = t.timeline.map((i) => i.kind);
    assert.deepEqual(kinds, ["user_message", "activity_group"]);
    const group = t.timeline.filter((i) => i.kind === "activity_group")[0];
    assert.equal(group.actions[0].title, "prep");
  });
});
