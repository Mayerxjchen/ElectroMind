/** D3.2 Inspector state model tests.
 *
 * Compiles the pure TypeScript module (inspector-model.ts) via esbuild
 * and asserts the open/close/pin rules from the D3.2 spec:
 *   - default closed at startup
 *   - contextual trigger opens the correct tab
 *   - same-trigger toggle closes
 *   - Escape closes only non-pinned
 *   - pinned survives thread switch, unpinned closes
 *   - pinned flag + last tab persist across restore; panel starts closed
 */

import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const esbuild = require("esbuild");

const MODULE_PATH = join(import.meta.dirname, "..", "src", "renderer", "inspector-model.ts");

let _module = null;

async function getModule() {
  if (_module) return _module;
  const tmpDir = mkdtempSync(join(tmpdir(), "inspector-model-test-"));
  const outFile = join(tmpDir, "inspector-model.mjs");
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

function fresh() {
  return { open: false, pinned: false, activeTab: "files" };
}

test("default state: closed, unpinned, files tab", async () => {
  const { createInitialInspectorState } = await getModule();
  assert.deepEqual(createInitialInspectorState(), fresh());
});

test("contextual trigger opens the matching tab", async () => {
  const { inspectorReducer } = await getModule();
  const cases = [
    { tab: "plan", triggerId: "item-1" },
    { tab: "changes", triggerId: "item-2" },
    { tab: "artifacts", triggerId: "item-3", selectedResourceId: "water64.out" },
    { tab: "jobs", triggerId: "item-4" },
    { tab: "runtime", triggerId: "sandbox-pill" },
    { tab: "logs", triggerId: "item-5" },
    { tab: "files", triggerId: "project-pill" },
  ];
  for (const c of cases) {
    const next = inspectorReducer(fresh(), { type: "trigger", ...c });
    assert.equal(next.open, true, `open for ${c.tab}`);
    assert.equal(next.activeTab, c.tab, `tab for ${c.tab}`);
    assert.equal(next.triggerId, c.triggerId);
    if (c.selectedResourceId !== undefined) {
      assert.equal(next.selectedResourceId, c.selectedResourceId);
    }
  }
});

test("same trigger toggles closed; different trigger switches tab", async () => {
  const { inspectorReducer } = await getModule();
  const opened = inspectorReducer(fresh(), { type: "trigger", tab: "plan", triggerId: "item-1" });
  const toggled = inspectorReducer(opened, { type: "trigger", tab: "plan", triggerId: "item-1" });
  assert.equal(toggled.open, false, "same trigger toggles closed");

  const switched = inspectorReducer(opened, { type: "trigger", tab: "changes", triggerId: "item-2" });
  assert.equal(switched.open, true);
  assert.equal(switched.activeTab, "changes");

  // A different object with the same category must NOT toggle closed.
  const reopened = inspectorReducer(fresh(), { type: "trigger", tab: "plan", triggerId: "item-9" });
  const other = inspectorReducer(reopened, { type: "trigger", tab: "plan", triggerId: "item-10" });
  assert.equal(other.open, true, "distinct objects do not toggle");
});

test("trigger without id never toggles", async () => {
  const { inspectorReducer } = await getModule();
  const opened = inspectorReducer(fresh(), { type: "trigger", tab: "plan" });
  const again = inspectorReducer(opened, { type: "trigger", tab: "plan" });
  assert.equal(again.open, true);
});

test("tab-bar click always opens and never toggles", async () => {
  const { inspectorReducer } = await getModule();
  const opened = inspectorReducer(fresh(), { type: "openTab", tab: "logs" });
  assert.equal(opened.open, true);
  assert.equal(opened.activeTab, "logs");
  const again = inspectorReducer(opened, { type: "openTab", tab: "logs" });
  assert.equal(again.open, true, "tab-bar click on active tab keeps it open");
});

test("escape closes non-pinned, keeps pinned open", async () => {
  const { inspectorReducer } = await getModule();
  const opened = inspectorReducer(fresh(), { type: "trigger", tab: "plan", triggerId: "item-1" });
  const closed = inspectorReducer(opened, { type: "escape" });
  assert.equal(closed.open, false);

  const pinned = inspectorReducer(opened, { type: "pin", pinned: true });
  const afterEscape = inspectorReducer(pinned, { type: "escape" });
  assert.equal(afterEscape.open, true, "pinned survives Escape");
  assert.equal(afterEscape.pinned, true);
});

test("close always closes even when pinned", async () => {
  const { inspectorReducer } = await getModule();
  const opened = inspectorReducer(fresh(), { type: "trigger", tab: "jobs", triggerId: "item-1" });
  const pinned = inspectorReducer(opened, { type: "pin", pinned: true });
  const closed = inspectorReducer(pinned, { type: "close" });
  assert.equal(closed.open, false);
  assert.equal(closed.pinned, true, "pin flag survives close");
});

test("thread switch: unpinned closes, pinned stays with cleared selection", async () => {
  const { inspectorReducer } = await getModule();
  const opened = inspectorReducer(fresh(), {
    type: "trigger",
    tab: "artifacts",
    triggerId: "item-1",
    selectedResourceId: "a.out",
  });
  const switched = inspectorReducer(opened, { type: "threadSwitched" });
  assert.equal(switched.open, false, "unpinned closes on thread switch");
  assert.equal(switched.selectedResourceId, undefined);

  const pinned = inspectorReducer(opened, { type: "pin", pinned: true });
  const pinnedSwitched = inspectorReducer(pinned, { type: "threadSwitched" });
  assert.equal(pinnedSwitched.open, true, "pinned stays open across switch");
  assert.equal(pinnedSwitched.selectedResourceId, undefined, "stale selection dropped");
  assert.equal(pinnedSwitched.activeTab, "artifacts", "tab kept");
});

test("restore: pinned flag and last tab kept, panel starts closed", async () => {
  const { inspectorReducer } = await getModule();
  const restored = inspectorReducer(fresh(), {
    type: "restore",
    pinned: true,
    lastTab: "logs",
  });
  assert.equal(restored.open, false, "starts closed");
  assert.equal(restored.pinned, true);
  assert.equal(restored.activeTab, "logs");
  assert.equal(restored.triggerId, undefined);
});
