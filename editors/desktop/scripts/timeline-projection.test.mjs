/** D3.3 TimelineProjection tests — the 18-case matrix from the spec.
 *
 * Compiles timeline-projection.ts (pure, DOM-free) via esbuild and
 * pins: deterministic grouping, upsert-not-append semantics, boundary
 * rules, subagent/thread isolation, full-vs-incremental equivalence,
 * id stability across replay/resume, and perf budgets.
 */

import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const esbuild = require("esbuild");

const MODULE_PATH = join(import.meta.dirname, "..", "src", "renderer", "timeline-projection.ts");

let _module = null;

async function getModule() {
  if (_module) return _module;
  const tmpDir = mkdtempSync(join(tmpdir(), "timeline-projection-test-"));
  const outFile = join(tmpDir, "timeline-projection.mjs");
  try {
    await esbuild.build({
      entryPoints: [MODULE_PATH],
      bundle: true,
      outfile: outFile,
      platform: "node",
      format: "esm",
      target: "node20",
      logLevel: "silent",
      absWorkingDir: join(import.meta.dirname, ".."),
    });
    _module = await import(outFile);
  } finally {
    rmSync(tmpDir, { recursive: true, force: true });
  }
  return _module;
}

const THREAD = "t-1";

/** Source builder with stable, sequential timestamps. */
function src(id, kind, payload = {}, threadId = THREAD, ts = 1000) {
  return { id, kind, threadId, timestamp: ts, payload };
}

function groupsOf(state) {
  return state.timeline.filter((i) => i.kind === "activity_group");
}

function actionsOf(state) {
  return groupsOf(state).flatMap((g) => g.actions);
}

test("1. single ToolCallBegin → running activity group", async () => {
  const { reduceTimeline, createProjectionState } = await getModule();
  let s = createProjectionState(THREAD);
  s = reduceTimeline(s, src("tool-a", "tool_call", { tool_call_id: "tc-1", name: "read_file", status: "running" }, THREAD, 1000));
  const groups = groupsOf(s);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].status, "running");
  assert.equal(groups[0].owner, "main");
  assert.equal(groups[0].actions.length, 1);
  assert.equal(groups[0].actions[0].status, "running");
  assert.equal(groups[0].actions[0].title, "read_file");
});

test("2. ToolResult updates the SAME action (no new card)", async () => {
  const { reduceTimeline, createProjectionState } = await getModule();
  let s = createProjectionState(THREAD);
  s = reduceTimeline(s, src("tool-a", "tool_call", { tool_call_id: "tc-1", name: "read_file", status: "running" }, THREAD, 1000));
  s = reduceTimeline(s, src("tool-a", "tool_call", { tool_call_id: "tc-1", name: "read_file", status: "done", duration_seconds: 2, exit_code: 0, content: "ok" }, THREAD, 2000));
  const groups = groupsOf(s);
  assert.equal(groups.length, 1, "group count unchanged");
  assert.equal(groups[0].actions.length, 1, "action count unchanged");
  assert.equal(groups[0].actions[0].status, "completed");
  assert.equal(groups[0].actions[0].durationMs, 2000);
});

test("3. consecutive tools merge into one group", async () => {
  const { reduceTimeline, createProjectionState } = await getModule();
  let s = createProjectionState(THREAD);
  for (const [id, tc, name] of [["tool-a", "tc-1", "read_file"], ["tool-b", "tc-2", "run_command"], ["tool-c", "tc-3", "write_file"]]) {
    s = reduceTimeline(s, src(id, "tool_call", { tool_call_id: tc, name, status: "done" }, THREAD, 1000));
  }
  const groups = groupsOf(s);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].actions.length, 3);
});

test("4. AssistantMessage ends the activity", async () => {
  const { reduceTimeline, createProjectionState } = await getModule();
  let s = createProjectionState(THREAD);
  s = reduceTimeline(s, src("tool-a", "tool_call", { tool_call_id: "tc-1", name: "read_file", status: "done" }, THREAD, 1000));
  s = reduceTimeline(s, src("asst-1", "assistant_message", { text: "完成" }, THREAD, 2000));
  const groups = groupsOf(s);
  assert.equal(groups[0].status, "completed");
  assert.ok(groups[0].endedAt);
  // The next tool call opens a FRESH group.
  s = reduceTimeline(s, src("tool-b", "tool_call", { tool_call_id: "tc-2", name: "run_command", status: "done" }, THREAD, 3000));
  assert.equal(groupsOf(s).length, 2);
});

test("5. PermitRequest ends the activity and creates an approval item", async () => {
  const { reduceTimeline, createProjectionState } = await getModule();
  let s = createProjectionState(THREAD);
  s = reduceTimeline(s, src("tool-a", "tool_call", { tool_call_id: "tc-1", name: "run_command", status: "running" }, THREAD, 1000));
  s = reduceTimeline(s, src("apr-1", "approval", { tool_call_id: "tc-1", name: "run_command", risk: "medium", workdir: "/p" }, THREAD, 2000));
  assert.equal(groupsOf(s)[0].status, "completed");
  const approvals = s.timeline.filter((i) => i.kind === "approval");
  assert.equal(approvals.length, 1);
  assert.equal(approvals[0].status, "pending");
  assert.equal(approvals[0].risk, "medium");
  // resolution updates the same item
  s = reduceTimeline(s, src("apr-1", "approval", { tool_call_id: "tc-1", status: "approved" }, THREAD, 3000));
  assert.equal(s.timeline.filter((i) => i.kind === "approval").length, 1);
  assert.equal(s.timeline.filter((i) => i.kind === "approval")[0].status, "approved");
});

test("6. tool failure auto-closes the group as failed", async () => {
  const { reduceTimeline, createProjectionState } = await getModule();
  let s = createProjectionState(THREAD);
  s = reduceTimeline(s, src("tool-a", "tool_call", { tool_call_id: "tc-1", name: "run_command", status: "running" }, THREAD, 1000));
  s = reduceTimeline(s, src("tool-a", "tool_call", { tool_call_id: "tc-1", name: "run_command", status: "error", content: "boom" }, THREAD, 2000));
  const groups = groupsOf(s);
  assert.equal(groups[0].status, "failed");
  assert.equal(groups[0].actions[0].status, "failed");
  assert.match(groups[0].actions[0].detail ?? "", /boom/);
  // A later tool call must start a fresh group (failure is a boundary).
  s = reduceTimeline(s, src("tool-b", "tool_call", { tool_call_id: "tc-2", name: "read_file", status: "done" }, THREAD, 3000));
  assert.equal(groupsOf(s).length, 2);
  assert.equal(groupsOf(s)[1].status, "running");
});

test("7. FileChange joins the current activity", async () => {
  const { reduceTimeline, createProjectionState } = await getModule();
  let s = createProjectionState(THREAD);
  s = reduceTimeline(s, src("tool-a", "tool_call", { tool_call_id: "tc-1", name: "read_file", status: "done", run_id: "run-1" }, THREAD, 1000));
  s = reduceTimeline(s, src("fc-1", "file_change", { path: "water64.xyz", status: "modified", additions: 12, deletions: 3, run_id: "run-1", tool_call_id: "tc-2" }, THREAD, 2000));
  const groups = groupsOf(s);
  assert.equal(groups.length, 1);
  const fc = groups[0].actions.find((a) => a.kind === "file_change");
  assert.ok(fc);
  assert.equal(fc.title, "water64.xyz");
  assert.equal(fc.status, "completed");
  assert.equal(fc.detail, "+12 −3");
});

test("8. Artifact enters the activity AND becomes a first-class item", async () => {
  const { reduceTimeline, createProjectionState } = await getModule();
  let s = createProjectionState(THREAD);
  s = reduceTimeline(s, src("tool-a", "tool_call", { tool_call_id: "tc-1", name: "run_command", status: "done", run_id: "run-1" }, THREAD, 1000));
  s = reduceTimeline(s, src("art-1", "artifact", { name: "out.xyz", path: "/p/out.xyz", size: 2048, status: "created" }, THREAD, 2000));
  const group = groupsOf(s)[0];
  assert.ok(group.actions.find((a) => a.kind === "artifact"));
  const artifacts = s.timeline.filter((i) => i.kind === "artifact");
  assert.equal(artifacts.length, 1);
  assert.equal(artifacts[0].path, "/p/out.xyz");
  // acceptance updates the same artifact item
  s = reduceTimeline(s, src("art-1", "artifact", { artifact_id: "a-1", path: "/p/out.xyz", status: "accepted" }, THREAD, 3000));
  assert.equal(s.timeline.filter((i) => i.kind === "artifact").length, 1);
  assert.equal(s.timeline.filter((i) => i.kind === "artifact")[0].status, "accepted");
});

test("9. job status updates the same Job item (PENDING→RUNNING→COMPLETED)", async () => {
  const { reduceTimeline, createProjectionState } = await getModule();
  let s = createProjectionState(THREAD);
  s = reduceTimeline(s, src("job-1", "job", { job_id: "2748657", state: "PENDING" }, THREAD, 1000));
  s = reduceTimeline(s, src("job-1", "job", { job_id: "2748657", state: "RUNNING", detail: "64 cores" }, THREAD, 2000));
  s = reduceTimeline(s, src("job-1", "job", { job_id: "2748657", state: "COMPLETED" }, THREAD, 3000));
  const jobs = s.timeline.filter((i) => i.kind === "job");
  assert.equal(jobs.length, 1, "one Job item, never appended");
  assert.equal(jobs[0].state, "COMPLETED");
  assert.equal(jobs[0].detail, "64 cores");
  assert.equal(jobs[0].id, "job:2748657");
});

test("9b. JobSubmitted closes the current activity group", async () => {
  const { reduceTimeline, createProjectionState } = await getModule();
  let s = createProjectionState(THREAD);
  s = reduceTimeline(s, src("tool-a", "tool_call", { tool_call_id: "tc-1", name: "prep", status: "done" }, THREAD, 1000));
  s = reduceTimeline(s, src("job-1", "job", { job_id: "j-9", state: "PENDING" }, THREAD, 2000));
  assert.equal(groupsOf(s)[0].status, "completed");
});

test("10. Plan status updates the same Plan item", async () => {
  const { reduceTimeline, createProjectionState } = await getModule();
  let s = createProjectionState(THREAD);
  s = reduceTimeline(s, src("tool-a", "tool_call", { tool_call_id: "tc-1", name: "prep", status: "done" }, THREAD, 1000));
  s = reduceTimeline(s, src("plan-1", "plan", { plan_id: "p-1", fingerprint: "fp-1", version: 1, status: "proposed", objective: "run water64", steps: [{ id: "s1", title: "Prepare", status: "pending" }] }, THREAD, 2000));
  assert.equal(groupsOf(s)[0].status, "completed", "PlanProposed ends the group");
  const plans = s.timeline.filter((i) => i.kind === "plan");
  assert.equal(plans.length, 1);
  assert.equal(plans[0].id, "plan:fp-1");
  // revision updates the same item
  s = reduceTimeline(s, src("plan-1", "plan", { plan_id: "p-1", fingerprint: "fp-1", version: 2, status: "approved", objective: "run water64", steps: [{ id: "s1", title: "Prepare", status: "running" }] }, THREAD, 3000));
  const plans2 = s.timeline.filter((i) => i.kind === "plan");
  assert.equal(plans2.length, 1);
  assert.equal(plans2[0].version, 2);
  assert.equal(plans2[0].status, "approved");
  assert.equal(plans2[0].steps[0].status, "running");
});

test("11. thread switch never mixes events", async () => {
  const { reduceTimeline, createProjectionState } = await getModule();
  let s = createProjectionState("t-1");
  s = reduceTimeline(s, src("tool-a", "tool_call", { tool_call_id: "tc-1", name: "read_file", status: "done" }, "t-1", 1000));
  const before = JSON.stringify(s.timeline);
  // foreign-thread event must be ignored entirely
  s = reduceTimeline(s, src("tool-b", "tool_call", { tool_call_id: "tc-2", name: "other", status: "done" }, "t-2", 2000));
  assert.equal(JSON.stringify(s.timeline), before);
});

test("12. subagent owner change splits groups", async () => {
  const { reduceTimeline, createProjectionState } = await getModule();
  let s = createProjectionState(THREAD);
  s = reduceTimeline(s, src("tool-a", "tool_call", { tool_call_id: "tc-1", name: "main_step", status: "done" }, THREAD, 1000));
  s = reduceTimeline(s, src("tool-b", "tool_call", { tool_call_id: "tc-2", name: "scout_step", status: "done", owner: "subagent:scout" }, THREAD, 2000));
  const groups = groupsOf(s);
  assert.equal(groups.length, 2);
  assert.equal(groups[0].owner, "main");
  assert.equal(groups[1].owner, "subagent:scout");
  assert.equal(groups[1].actions.length, 1, "no cross-owner mixing");
  // Same owner keeps aggregating into the same group (spec: consecutive
  // tool calls of one owner aggregate; only an OWNER CHANGE splits).
  s = reduceTimeline(s, src("tool-c", "tool_call", { tool_call_id: "tc-3", name: "back", status: "done", owner: "subagent:scout" }, THREAD, 3000));
  assert.equal(groupsOf(s).length, 2);
  assert.equal(groupsOf(s)[1].actions.length, 2);
  // Back to main → new group again.
  s = reduceTimeline(s, src("tool-d", "tool_call", { tool_call_id: "tc-4", name: "finish", status: "done", owner: "main" }, THREAD, 4000));
  const groupsAfter = groupsOf(s);
  assert.equal(groupsAfter.length, 3);
  assert.equal(groupsAfter[2].owner, "main");
});

test("13. run cancelled closes the activity as cancelled", async () => {
  const { reduceTimeline, createProjectionState } = await getModule();
  let s = createProjectionState(THREAD);
  s = reduceTimeline(s, src("tool-a", "tool_call", { tool_call_id: "tc-1", name: "read_file", status: "running", run_id: "r-1" }, THREAD, 1000));
  s = reduceTimeline(s, src("run-end", "run_cancelled", { run_id: "r-1" }, THREAD, 2000));
  assert.equal(groupsOf(s)[0].status, "cancelled");
});

test("14. full projection ≡ incremental reduction (both paths)", async () => {
  const { projectTimeline, projectThreadItems, reduceTimeline, createProjectionState } = await getModule();
  // A realistic stream with in-place mutations (same id re-emitted).
  const stream = [
    src("tool-a", "tool_call", { tool_call_id: "tc-1", name: "read_file", status: "running", run_id: "r-1" }, THREAD, 1000),
    src("tool-b", "tool_call", { tool_call_id: "tc-2", name: "run_command", status: "running", run_id: "r-1" }, THREAD, 2000),
    src("tool-a", "tool_call", { tool_call_id: "tc-1", name: "read_file", status: "done", run_id: "r-1" }, THREAD, 3000),
    src("asst-1", "assistant_message", { text: "正在" }, THREAD, 4000),
    src("asst-1", "assistant_message", { text: "正在处理" }, THREAD, 5000),
    src("fc-1", "file_change", { path: "a.py", additions: 1, deletions: 0, run_id: "r-1" }, THREAD, 6000),
    src("tool-c", "tool_call", { tool_call_id: "tc-3", name: "write_file", status: "done", run_id: "r-1" }, THREAD, 7000),
    src("apr-1", "approval", { tool_call_id: "tc-3", name: "write_file" }, THREAD, 8000),
    src("job-1", "job", { job_id: "j-1", state: "RUNNING" }, THREAD, 9000),
  ];
  // incremental
  let state = createProjectionState(THREAD);
  for (const e of stream) state = reduceTimeline(state, e);
  // Full replay over the persisted item list: the store appends an item
  // ONCE with its creation timestamp and mutates payload in place, so the
  // persisted form is first-occurrence timestamp + last payload.
  const firstById = new Map();
  const lastById = new Map();
  const order = [];
  for (const e of stream) {
    if (!firstById.has(e.id)) {
      order.push(e.id);
      firstById.set(e.id, e);
    }
    lastById.set(e.id, e);
  }
  const finalItems = order.map((id) => {
    const first = firstById.get(id);
    const last = lastById.get(id);
    return { ...first, timestamp: first.timestamp, payload: { ...last.payload } };
  });
  const replay = projectTimeline(finalItems, {}, THREAD);
  assert.deepEqual(replay.timeline, state.timeline, "replay must equal incremental");
  // convenience wrapper agrees too
  const viaItems = projectThreadItems(finalItems);
  assert.deepEqual(viaItems.timeline, state.timeline);
});

test("15. repeated projection of same input yields same IDs, no duplicates", async () => {
  const { projectTimeline } = await getModule();
  const stream = [
    src("tool-a", "tool_call", { tool_call_id: "tc-1", name: "read_file", status: "done", run_id: "r-1" }, THREAD, 1000),
    src("job-1", "job", { job_id: "j-1", state: "RUNNING" }, THREAD, 2000),
    src("art-1", "artifact", { path: "/p/out.xyz", status: "created" }, THREAD, 3000),
  ];
  const a = projectTimeline(stream, {}, THREAD);
  const b = projectTimeline(stream, {}, THREAD);
  assert.deepEqual(a, b);
  assert.deepEqual(
    a.timeline.map((i) => i.id),
    b.timeline.map((i) => i.id),
  );
  assert.equal(new Set(a.timeline.map((i) => i.id)).size, a.timeline.length, "ids unique");
});

test("16. resume rebuild from persisted items: same ids, no duplicate tool/job/artifact", async () => {
  const { projectTimeline, projectThreadItems } = await getModule();
  const stream = [
    src("tool-a", "tool_call", { tool_call_id: "tc-1", name: "read_file", status: "running", run_id: "r-1" }, THREAD, 1000),
    src("tool-b", "tool_call", { tool_call_id: "tc-2", name: "prep", status: "done", run_id: "r-1" }, THREAD, 2000),
    src("tool-a", "tool_call", { tool_call_id: "tc-1", name: "read_file", status: "done", run_id: "r-1" }, THREAD, 3000),
    src("job-1", "job", { job_id: "j-9", state: "COMPLETED" }, THREAD, 4000),
    src("art-1", "artifact", { path: "/p/o1.xyz", status: "accepted" }, THREAD, 5000),
  ];
  const live = projectTimeline(stream, {}, THREAD);
  // persisted final items (first-occurrence timestamp + last payload)
  const firstById = new Map();
  const lastById = new Map();
  const order = [];
  for (const e of stream) {
    if (!firstById.has(e.id)) {
      order.push(e.id);
      firstById.set(e.id, e);
    }
    lastById.set(e.id, e);
  }
  const resumed = projectThreadItems(
    order.map((id) => {
      const first = firstById.get(id);
      const last = lastById.get(id);
      return { ...first, timestamp: first.timestamp, payload: { ...last.payload } };
    }),
  );
  assert.deepEqual(resumed.timeline.map((i) => i.id), live.timeline.map((i) => i.id));
  const toolActions = resumed.timeline.flatMap((i) => (i.kind === "activity_group" ? i.actions : [])).filter((a) => a.kind === "tool");
  assert.equal(toolActions.length, 2, "distinct tool calls only");
  assert.equal(new Set(toolActions.map((a) => a.toolCallId)).size, 2);
});

test("17. unknown / future kinds are safely ignored", async () => {
  const { reduceTimeline, createProjectionState } = await getModule();
  let s = createProjectionState(THREAD);
  const weird = { id: "x-1", kind: "banana", threadId: THREAD, timestamp: 1, payload: {} };
  assert.doesNotThrow(() => {
    s = reduceTimeline(s, weird);
  });
  assert.equal(s.timeline.length, 0);
});

test("18. perf: 5000-item full projection < 100ms, single step < 5ms", async () => {
  const { projectTimeline, reduceTimeline, createProjectionState } = await getModule();
  const stream = [];
  let ts = 1000;
  for (let i = 0; i < 5000; i++) {
    const run = `r-${Math.floor(i / 100)}`;
    switch (i % 6) {
      case 0:
        stream.push(src(`tool-${i}`, "tool_call", { tool_call_id: `tc-${i}`, name: `tool_${i % 5}`, status: i % 37 === 0 ? "error" : "done", run_id: run }, THREAD, ts));
        break;
      case 1:
        stream.push(src(`cmd-${i}`, "command", { command: `cmd ${i}`, ok: true, duration_seconds: 1, run_id: run }, THREAD, ts));
        break;
      case 2:
        stream.push(src(`fc-${i}`, "file_change", { path: `f/${i}.py`, additions: i, deletions: i % 3, run_id: run }, THREAD, ts));
        break;
      case 3:
        stream.push(src(`art-${i}`, "artifact", { path: `/p/o${i}.xyz`, status: "created" }, THREAD, ts));
        break;
      case 4:
        stream.push(src(`asst-${i}`, "assistant_message", { text: `step ${i}` }, THREAD, ts));
        break;
      default:
        stream.push(src(`reas-${i}`, "reasoning", { text: `think ${i}` }, THREAD, ts));
    }
    ts += 100;
  }
  const t0 = performance.now();
  const state = projectTimeline(stream, {}, THREAD);
  const fullMs = performance.now() - t0;
  assert.ok(fullMs < 100, `full projection took ${fullMs.toFixed(1)}ms`);
  assert.equal(state.timeline.length > 0, true);

  // Boundary first, then a new tool → a fresh group item is appended.
  // (Base length must be captured first: reduceTimeline state shares the
  // timeline array with its predecessor — the documented mutable contract.)
  const baseLen = state.timeline.length;
  let next = reduceTimeline(state, src("asst-last", "assistant_message", { text: "done" }, THREAD, ts));
  const t1 = performance.now();
  next = reduceTimeline(next, src("tool-last", "tool_call", { tool_call_id: "tc-last", name: "x", status: "done" }, THREAD, ts + 1));
  const stepMs = performance.now() - t1;
  assert.ok(stepMs < 5, `single step took ${stepMs.toFixed(2)}ms`);
  assert.equal(next.timeline.length, baseLen + 2);
});

test("19. time gap is a fallback boundary only when enabled", async () => {
  const { projectTimeline } = await getModule();
  const stream = [
    src("tool-a", "tool_call", { tool_call_id: "tc-1", name: "a", status: "done" }, THREAD, 1000),
    src("tool-b", "tool_call", { tool_call_id: "tc-2", name: "b", status: "done" }, THREAD, 9000),
  ];
  // default: no gap boundary → one group
  const noGap = projectTimeline(stream, {}, THREAD);
  assert.equal(noGap.timeline.filter((i) => i.kind === "activity_group").length, 1);
  // with gapMs → two groups
  const withGap = projectTimeline(stream, { gapMs: 3000 }, THREAD);
  assert.equal(withGap.timeline.filter((i) => i.kind === "activity_group").length, 2);
});

test("20. run_id binds a group; a new run opens a fresh group", async () => {
  const { reduceTimeline, createProjectionState } = await getModule();
  let s = createProjectionState(THREAD);
  s = reduceTimeline(s, src("tool-a", "tool_call", { tool_call_id: "tc-1", name: "a", status: "done", run_id: "r-1" }, THREAD, 1000));
  s = reduceTimeline(s, src("run-end", "run_end", { run_id: "r-1" }, THREAD, 2000));
  s = reduceTimeline(s, src("tool-b", "tool_call", { tool_call_id: "tc-2", name: "b", status: "done", run_id: "r-2" }, THREAD, 3000));
  const groups = groupsOf(s);
  assert.equal(groups.length, 2);
  assert.equal(groups[0].status, "completed");
  assert.equal(groups[1].runId, "r-2");
  assert.equal(groups[1].id, "group:r-2");
});

test("21. skill_loaded upserts by skill name (P4)", async () => {
  const { reduceTimeline, createProjectionState } = await getModule();
  let s = createProjectionState(THREAD);
  s = reduceTimeline(s, src("s1", "skill_loaded", { name: "cp2k", source: "builtin", digest: "abc123", ok: true }, THREAD, 1000));
  const items = s.timeline.filter((i) => i.kind === "skill_loaded");
  assert.equal(items.length, 1);
  assert.equal(items[0].name, "cp2k");
  assert.equal(items[0].digest, "abc123");
  // 同名更新（激活失败 → 同一行 upsert，不重复）
  s = reduceTimeline(s, src("s2", "skill_loaded", { name: "cp2k", ok: false }, THREAD, 2000));
  const after = s.timeline.filter((i) => i.kind === "skill_loaded");
  assert.equal(after.length, 1, "同名 Skill 记录 upsert 不重复");
  assert.equal(after[0].ok, false);
});
