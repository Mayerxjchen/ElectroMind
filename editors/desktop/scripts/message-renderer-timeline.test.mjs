/** D3.4 MessageRenderer timeline tests — the projected TimelineItem[]
 *  renders as Codex-style blocks: activity groups with expand rules,
 *  inline approvals, job/artifact/plan rows, bounded virtual window.
 *
 *  Uses the same minimal DOM stub family as message-renderer-virtual.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

// ── Minimal DOM stub (extended: classList.toggle, setAttribute) ──────

class FakeClassList {
  constructor() {
    this.set = new Set();
  }
  add(...cls) {
    cls.forEach((c) => this.set.add(c));
  }
  remove(...cls) {
    cls.forEach((c) => this.set.delete(c));
  }
  contains(cls) {
    return this.set.has(cls);
  }
  toggle(cls, force) {
    const next = force !== undefined ? Boolean(force) : !this.set.has(cls);
    if (next) this.set.add(cls);
    else this.set.delete(cls);
    return next;
  }
}

class FakeElement {
  constructor(tag = "div") {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.style = {};
    this.listeners = {};
    this.scrollTop = 0;
    this.clientHeight = 600;
    this.scrollHeight = 0;
    this.className = "";
    this.parentNode = null;
    this.dataset = {};
    this.attributes = {};
    this.classList = new FakeClassList();
    this._innerHTML = "";
    this.textContent = "";
    this.type = "";
    this.title = "";
  }
  set innerHTML(v) {
    this._innerHTML = v;
    // Real DOM replaces children on innerHTML assignment.
    this.children = [];
  }
  get innerHTML() {
    return this._innerHTML;
  }
  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  remove() {
    if (this.parentNode) {
      const idx = this.parentNode.children.indexOf(this);
      if (idx >= 0) this.parentNode.children.splice(idx, 1);
      this.parentNode = null;
    }
  }
  replaceWith(newEl) {
    if (this.parentNode) {
      const idx = this.parentNode.children.indexOf(this);
      if (idx >= 0) this.parentNode.children[idx] = newEl;
      newEl.parentNode = this.parentNode;
      this.parentNode = null;
    }
  }
  addEventListener(name, fn) {
    (this.listeners[name] ??= []).push(fn);
  }
  fire(name) {
    for (const fn of this.listeners[name] ?? []) fn();
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }
  getAttribute(name) {
    return this.attributes[name] ?? null;
  }
  querySelectorAll() {
    return [];
  }
  querySelector() {
    return null;
  }
}

globalThis.document = {
  createElement: (tag) => new FakeElement(tag),
  createElementNS: (_ns, tag) => new FakeElement(tag),
  querySelector: () => null,
  querySelectorAll: () => [],
  createTextNode: () => ({}),
};
globalThis.ResizeObserver = class {
  observe() {}
  disconnect() {}
  unobserve() {}
};
globalThis.requestAnimationFrame = (fn) => fn();
Object.defineProperty(globalThis, "navigator", {
  value: { clipboard: { writeText: async () => {} } },
  configurable: true,
});

const { MessageRenderer } = await import(
  new URL("../src/renderer/MessageRenderer.ts", import.meta.url)
);

function collectText(el) {
  let t = el.textContent || "";
  for (const ch of el.children) t += collectText(ch);
  return t;
}

function groupItem(over = {}) {
  return {
    id: "group:r-1",
    kind: "activity_group",
    threadId: "t1",
    owner: "main",
    runId: "r-1",
    status: "completed",
    startedAt: 1000,
    endedAt: 43000,
    actions: [
      { id: "action:tc-1", toolCallId: "tc-1", kind: "tool", title: "read_file", status: "completed", durationMs: 1200 },
      { id: "action:tc-2", toolCallId: "tc-2", kind: "command", title: "cp2k.popt -c water64.inp", status: "completed", durationMs: 30000 },
      { id: "action:fc-1", kind: "file_change", title: "water64.xyz", status: "completed" },
    ],
    ...over,
  };
}

function mountedBlocks(container) {
  const inner = container.children[0];
  if (!inner) return [];
  // VirtualList wraps each item in a .virtual-list-item element.
  return inner.children.map((wrapper) => wrapper.children[0]).filter(Boolean);
}

test("completed group: collapsed by default, summary 'Worked for 42s · 3 actions'", () => {
  const container = new FakeElement();
  const renderer = new MessageRenderer(container, () => {});
  renderer.syncTimeline([groupItem()]);
  const block = mountedBlocks(container)[0];
  assert.equal(block.className, "msg-block activity-group");
  const header = block.children[0];
  assert.match(collectText(header), /Worked for 42s · 3 actions/);
  const actions = block.children[1];
  assert.equal(actions.classList.contains("collapsed"), true, "completed collapses");
  assert.equal(header.getAttribute("aria-expanded"), "false");
});

test("running group: expanded by default with spinner summary", () => {
  const container = new FakeElement();
  const renderer = new MessageRenderer(container, () => {});
  renderer.syncTimeline([groupItem({ status: "running", endedAt: undefined })]);
  const block = mountedBlocks(container)[0];
  const header = block.children[0];
  assert.match(collectText(header), /Working… 3 actions/);
  const actions = block.children[1];
  assert.equal(actions.classList.contains("collapsed"), false, "running expands");
  assert.equal(header.getAttribute("aria-expanded"), "true");
});

test("failed group: expanded, failed action shows detail", () => {
  const container = new FakeElement();
  const renderer = new MessageRenderer(container, () => {});
  renderer.syncTimeline([
    groupItem({
      status: "failed",
      actions: [
        { id: "action:tc-1", toolCallId: "tc-1", kind: "tool", title: "run_command", status: "failed", detail: "boom: segmentation fault", exitCode: 139 },
        { id: "action:tc-2", toolCallId: "tc-2", kind: "tool", title: "read_file", status: "completed" },
      ],
    }),
  ]);
  const block = mountedBlocks(container)[0];
  assert.match(collectText(block.children[0]), /Failed after 42s · 2 actions/);
  assert.equal(block.children[1].classList.contains("collapsed"), false);
  const actionRows = block.children[1].children;
  assert.equal(actionRows.length, 2);
  assert.match(collectText(actionRows[0]), /boom: segmentation fault/);
  assert.match(collectText(actionRows[0]), /exit 139/);
});

test("toggle: click header expands a completed group; override persists across syncs", () => {
  const container = new FakeElement();
  const renderer = new MessageRenderer(container, () => {});
  renderer.syncTimeline([groupItem()]);
  const block = mountedBlocks(container)[0];
  const header = block.children[0];
  header.fire("click");
  assert.equal(block.children[1].classList.contains("collapsed"), false, "expanded after click");
  assert.equal(header.getAttribute("aria-expanded"), "true");
  // Re-sync (e.g. next store emit) keeps the user override.
  renderer.syncTimeline([groupItem()]);
  const block2 = mountedBlocks(container)[0];
  assert.equal(block2.children[1].classList.contains("collapsed"), false, "override survives re-sync");
});

test("approval pending: inline card with Deny / Allow once wired to onPermit", () => {
  const permits = [];
  const container = new FakeElement();
  const renderer = new MessageRenderer(container, (toolCallId, approved) => {
    permits.push({ toolCallId, approved });
  });
  renderer.syncTimeline([
    {
      id: "approval:tc-9",
      kind: "approval",
      threadId: "t1",
      timestamp: 1,
      toolCallId: "tc-9",
      toolName: "run_command",
      status: "pending",
      target: "Local",
      workdir: "/project/input",
      risk: "medium",
      summary: "cp2k.popt -c water64.inp",
    },
  ]);
  const block = mountedBlocks(container)[0];
  const text = collectText(block);
  assert.match(text, /Approval required/);
  assert.match(text, /run_command/);
  assert.match(text, /Local · \/project\/input · medium risk/);
  const actions = block.children.find((c) => c.className === "approval-actions");
  const [deny, allow] = actions.children;
  assert.equal(deny.textContent, "Deny");
  assert.equal(allow.textContent, "Allow once");
  allow.fire("click");
  deny.fire("click");
  assert.deepEqual(permits, [
    { toolCallId: "tc-9", approved: true },
    { toolCallId: "tc-9", approved: false },
  ]);
});

test("approval resolved: quiet status row, no buttons", () => {
  const container = new FakeElement();
  const renderer = new MessageRenderer(container, () => {});
  renderer.syncTimeline([
    {
      id: "approval:tc-9",
      kind: "approval",
      threadId: "t1",
      timestamp: 1,
      toolCallId: "tc-9",
      toolName: "run_command",
      status: "approved",
    },
  ]);
  const block = mountedBlocks(container)[0];
  assert.match(collectText(block), /已批准：run_command/);
  assert.equal(block.children.some((c) => c.className === "approval-actions"), false);
});

test("job row: state renders and updates IN PLACE (same item)", () => {
  const container = new FakeElement();
  const renderer = new MessageRenderer(container, () => {});
  const job = (state, detail) => ({
    id: "job:2748657",
    kind: "job",
    threadId: "t1",
    timestamp: 1,
    jobId: "2748657",
    state,
    detail,
  });
  renderer.syncTimeline([job("PENDING")]);
  const block = mountedBlocks(container)[0];
  assert.match(collectText(block), /Slurm job 2748657/);
  assert.match(collectText(block), /PENDING/);
  renderer.syncTimeline([job("RUNNING", "cpu · 64 cores")]);
  const block2 = mountedBlocks(container)[0];
  assert.match(collectText(block2), /RUNNING/);
  assert.match(collectText(block2), /cpu · 64 cores/);
});

test("artifact row: compact meta + inspector trigger attrs", () => {
  const container = new FakeElement();
  const renderer = new MessageRenderer(container, () => {});
  renderer.syncTimeline([
    {
      id: "artifact:/p/o1.xyz",
      kind: "artifact",
      threadId: "t1",
      timestamp: 1,
      artifactId: "/p/o1.xyz",
      path: "/p/o1.xyz",
      name: "water64_force_energy.out",
      size: 2516582,
      status: "Validated",
    },
  ]);
  const block = mountedBlocks(container)[0];
  assert.match(collectText(block), /water64_force_energy.out/);
  assert.match(collectText(block), /Validated · 2.4 MB/);
  assert.equal(block.dataset.inspectorTab, "artifacts");
  assert.equal(block.dataset.inspectorResource, "/p/o1.xyz");
});

test("plan card: summary + inspector plan trigger", () => {
  const container = new FakeElement();
  const renderer = new MessageRenderer(container, () => {});
  renderer.syncTimeline([
    {
      id: "plan:fp-1",
      kind: "plan",
      threadId: "t1",
      timestamp: 1,
      planId: "p-1",
      version: 1,
      status: "approved",
      objective: "run water64",
      steps: [
        { id: "s1", title: "Prepare", status: "completed" },
        { id: "s2", title: "Run", status: "pending" },
        { id: "s3", title: "Validate", status: "pending" },
      ],
    },
  ]);
  const block = mountedBlocks(container)[0];
  assert.match(collectText(block), /Plan · 1\/3 completed/);
  assert.match(collectText(block), /approved/);
  assert.equal(block.dataset.inspectorTab, "plan");
});

test("messages, reasoning, error, recovery render through syncTimeline", () => {
  const container = new FakeElement();
  const renderer = new MessageRenderer(container, () => {});
  renderer.syncTimeline([
    { id: "u-1", kind: "user_message", threadId: "t1", timestamp: 1, text: "hi" },
    { id: "r-1", kind: "assistant_message", threadId: "t1", timestamp: 2, text: "think", reasoning: true },
    { id: "a-1", kind: "assistant_message", threadId: "t1", timestamp: 3, text: "hello" },
    { id: "e-1", kind: "error", threadId: "t1", timestamp: 4, message: "boom" },
    { id: "rec-1", kind: "recovery", threadId: "t1", timestamp: 5, message: "连接已恢复" },
  ]);
  const blocks = mountedBlocks(container);
  assert.equal(blocks.length, 5);
  assert.equal(blocks[0].className, "msg-block user-message");
  assert.equal(blocks[1].className, "msg-block reasoning-block");
  assert.equal(blocks[2].className, "msg-block assistant-message");
  assert.equal(blocks[3].className, "msg-block error-banner");
  assert.equal(blocks[4].className, "msg-block recovery-row");
});

test("5000 timeline items: bounded window, scroll height intact", () => {
  const container = new FakeElement();
  const renderer = new MessageRenderer(container, () => {});
  const items = Array.from({ length: 5000 }, (_, i) =>
    i % 2 === 0
      ? groupItem({ id: `group:r-${i}`, status: "completed", actions: [{ id: `action:${i}`, kind: "tool", title: `t${i}`, status: "completed" }] })
      : { id: `a-${i}`, kind: "assistant_message", threadId: "t1", timestamp: i, text: `m ${i}` },
  );
  renderer.syncTimeline(items);
  const inner = container.children[0];
  assert.equal(inner.style.height, "400000px");
  const mounted = inner.children.length;
  assert.ok(mounted <= 16, `bounded window, got ${mounted}`);
  assert.ok(mounted >= 6, `viewport covered, got ${mounted}`);
});

test("status fingerprint triggers refresh on in-place action updates", () => {
  const container = new FakeElement();
  const renderer = new MessageRenderer(container, () => {});
  const running = groupItem({ status: "running", endedAt: undefined, actions: [{ id: "action:tc-1", kind: "tool", title: "x", status: "running" }] });
  renderer.syncTimeline([running]);
  const done = groupItem({ status: "completed", endedAt: 5000, actions: [{ id: "action:tc-1", kind: "tool", title: "x", status: "completed" }] });
  renderer.syncTimeline([done]);
  // After refresh the visible block reflects the terminal state.
  const block = mountedBlocks(container)[0];
  assert.match(collectText(block.children[0]), /Worked for 4s · 1 action/);
});
