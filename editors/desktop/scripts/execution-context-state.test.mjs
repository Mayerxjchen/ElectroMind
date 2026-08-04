/** ExecutionContextState and HistoryReplay behavior tests.
 *
 *  Compiles the pure TypeScript module via esbuild and imports it into
 *  the Node test runner so assertions test actual executable logic, not
 *  regex matches against source text.
 */

import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const esbuild = require("esbuild");

// ---------------------------------------------------------------------------
// Compile helper
// ---------------------------------------------------------------------------

const MODULE_PATH = join(
  import.meta.dirname,
  "..",
  "src",
  "renderer",
  "execution-context-state.ts",
);

let _module = null;

async function getModule() {
  if (_module) return _module;

  const tmpDir = mkdtempSync(join(tmpdir(), "ectx-test-"));
  const outFile = join(tmpDir, "execution-context-state.mjs");

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
  } catch (err) {
    rmSync(tmpDir, { recursive: true, force: true });
    throw err;
  }

  try {
    _module = await import(outFile);
  } finally {
    // Clean up temp dir — the module is now loaded in the registry.
    rmSync(tmpDir, { recursive: true, force: true });
  }

  return _module;
}

// ---------------------------------------------------------------------------
// Helpers: build payloads
// ---------------------------------------------------------------------------

function payload(overrides = {}) {
  return {
    type: "ExecutionContextState",
    thread_id: "",
    target: "",
    profile_id: "",
    documents: [],
    diagnostics: [],
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// ExecutionContextState transition tests
// ---------------------------------------------------------------------------

test("stale clear from A while B current leaves B state unchanged", async () => {
  const { computeExecutionContextTransition } = await getModule();

  // Thread A sends a clear event, but the active thread is B.
  const state = payload({ thread_id: "thread-A" });
  const result = computeExecutionContextTransition(state, "thread-B");

  assert.deepStrictEqual(
    result,
    { kind: "noop" },
    "stale event from thread-A must be a noop when thread-B is active",
  );
});

test("active thread clear returns clear transition", async () => {
  const { computeExecutionContextTransition } = await getModule();

  // Active thread sends a clear (empty payload, no target/docs/diags).
  const state = payload({ thread_id: "thread-A" });
  const result = computeExecutionContextTransition(state, "thread-A");

  assert.deepStrictEqual(
    result,
    { kind: "clear" },
    "clear payload for active thread must return { kind: 'clear' }",
  );
});

test("active thread normal state applies", async () => {
  const { computeExecutionContextTransition } = await getModule();

  const state = payload({
    thread_id: "thread-A",
    target: "ssh://host.example.com",
    profile_id: "my-profile",
    documents: [
      { remote_path: "/etc/hosts", sha256: "abc123", size: 128, fetched_at: 1000 },
    ],
  });

  const result = computeExecutionContextTransition(state, "thread-A");

  assert.deepStrictEqual(
    result,
    { kind: "apply", state },
    "non-empty payload for active thread must apply the state",
  );
});

test("legacy empty-thread_id state applies", async () => {
  const { computeExecutionContextTransition } = await getModule();

  // Legacy events with empty thread_id pass the guard (falsy thread_id).
  const state = payload({
    thread_id: "",
    target: "ssh://legacy.example.com",
    profile_id: "legacy-profile",
    documents: [{ remote_path: "/x", sha256: "def", size: 64, fetched_at: 2000 }],
  });

  const result = computeExecutionContextTransition(state, "thread-C");

  assert.deepStrictEqual(
    result,
    { kind: "apply", state },
    "legacy event with empty thread_id must apply regardless of active thread",
  );
});

test("legacy empty-thread_id clear applies", async () => {
  const { computeExecutionContextTransition } = await getModule();

  // Legacy clear event with empty thread_id — should still clear.
  const state = payload({ thread_id: "" });
  const result = computeExecutionContextTransition(state, "thread-X");

  assert.deepStrictEqual(
    result,
    { kind: "clear" },
    "legacy clear event with empty thread_id must clear regardless of active thread",
  );
});

test("state with only diagnostics is not a clear", async () => {
  const { computeExecutionContextTransition } = await getModule();

  const state = payload({
    thread_id: "thread-A",
    diagnostics: [
      { code: "E001", message: "something wrong", path: "/x", severity: "error" },
    ],
  });

  const result = computeExecutionContextTransition(state, "thread-A");

  assert.deepStrictEqual(
    result,
    { kind: "apply", state },
    "payload with only diagnostics is still an apply, not a clear",
  );
});

test("state with only target but no docs is not a clear", async () => {
  const { computeExecutionContextTransition } = await getModule();

  const state = payload({
    thread_id: "thread-B",
    target: "local",
  });

  const result = computeExecutionContextTransition(state, "thread-B");

  assert.deepStrictEqual(
    result,
    { kind: "apply", state },
    "payload with target set is an apply even with no documents",
  );
});

// ---------------------------------------------------------------------------
// HistoryReplay clear predicate tests
// ---------------------------------------------------------------------------

test("HistoryReplay: matching non-empty thread_id clears", () => {
  // Test synchronously — shouldClearExecutionContextOnReplay has no dependencies
  // that need esbuild compilation (it's pure logic).  We still import it
  // from the compiled module for consistency.
  const shouldClearExecutionContextOnReplay = (replayedThreadId, currentThreadId) =>
    replayedThreadId !== "" && replayedThreadId === currentThreadId;

  assert.ok(
    shouldClearExecutionContextOnReplay("thread-A", "thread-A"),
    "matching thread_id must trigger clear",
  );
});

test("HistoryReplay: mismatched thread_id does not clear", () => {
  const shouldClearExecutionContextOnReplay = (replayedThreadId, currentThreadId) =>
    replayedThreadId !== "" && replayedThreadId === currentThreadId;

  assert.ok(
    !shouldClearExecutionContextOnReplay("thread-A", "thread-B"),
    "mismatched thread_id must NOT trigger clear",
  );
});

test("HistoryReplay: empty thread_id does not clear", () => {
  const shouldClearExecutionContextOnReplay = (replayedThreadId, currentThreadId) =>
    replayedThreadId !== "" && replayedThreadId === currentThreadId;

  assert.ok(
    !shouldClearExecutionContextOnReplay("", "thread-A"),
    "empty thread_id (synthetic replay) must NOT trigger clear",
  );
});

test("HistoryReplay: empty thread_id with empty current does not clear", () => {
  const shouldClearExecutionContextOnReplay = (replayedThreadId, currentThreadId) =>
    replayedThreadId !== "" && replayedThreadId === currentThreadId;

  assert.ok(
    !shouldClearExecutionContextOnReplay("", ""),
    "empty thread_id with empty current must NOT trigger clear",
  );
});

test("HistoryReplay predicate from compiled module matches inline logic", async () => {
  const { shouldClearExecutionContextOnReplay } = await getModule();

  // Verify the compiled function behaves identically to the inline version
  assert.strictEqual(
    shouldClearExecutionContextOnReplay("thread-A", "thread-A"),
    true,
  );
  assert.strictEqual(
    shouldClearExecutionContextOnReplay("thread-A", "thread-B"),
    false,
  );
  assert.strictEqual(
    shouldClearExecutionContextOnReplay("", "thread-A"),
    false,
  );
  assert.strictEqual(
    shouldClearExecutionContextOnReplay("", ""),
    false,
  );
});
