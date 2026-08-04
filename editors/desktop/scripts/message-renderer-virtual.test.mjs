/** MessageRenderer + VirtualList production integration (Section IX).
 *
 * The REAL MessageRenderer must route its timeline through VirtualList:
 * with 5000 ThreadItems only a bounded window is mounted, scrolling
 * re-renders near the target, and addUser/showError route through the
 * virtual list (single rendering path).
 */

import { test } from "node:test";
import assert from "node:assert/strict";

// ── Minimal DOM stub ─────────────────────────────────────────────────

let createCounter = 0;

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
    this.classList = new FakeClassList();
    this._innerHTML = "";
    this.textContent = "";
  }
  set innerHTML(v) {
    this._innerHTML = v;
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
  querySelectorAll() {
    return [];
  }
  querySelector() {
    return null;
  }
}

globalThis.document = {
  createElement: (tag) => {
    createCounter++;
    return new FakeElement(tag);
  },
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

/** Collect descendant text (FakeElement.textContent does not aggregate). */
function collectText(el) {
  let t = el.textContent || "";
  for (const ch of el.children) t += collectText(ch);
  return t;
}

function makeItem(i) {
  return {
    id: `item-${i}`,
    kind: i % 3 === 0 ? "assistant_message" : i % 3 === 1 ? "user_message" : "tool_call",
    threadId: "t1",
    timestamp: i,
    payload:
      i % 3 === 2
        ? { tool_call_id: `tc-${i}`, name: "run_command", arguments: "{}", status: "done", content: "ok" }
        : { text: `message ${i}` },
  };
}

test("MessageRenderer mounts only a bounded window for 5000 items", () => {
  createCounter = 0;
  const container = new FakeElement();
  const renderer = new MessageRenderer(container, () => {});

  const items = Array.from({ length: 5000 }, (_, i) => makeItem(i));
  renderer.syncItems(items);

  // The virtual list inner spacer exists and represents full height
  const inner = container.children[0];
  assert.ok(inner, "VirtualList inner spacer must be mounted");
  assert.equal(inner.style.height, "400000px"); // 5000 × 80

  // Only a bounded number of item elements are mounted
  const mountedItems = inner.children.length;
  assert.ok(
    mountedItems <= 16,
    `mounted items must be bounded, got ${mountedItems}`,
  );
  assert.ok(mountedItems >= 6, `must cover the viewport, got ${mountedItems}`);
});

test("MessageRenderer scroll re-renders near the target", () => {
  createCounter = 0;
  const container = new FakeElement();
  const renderer = new MessageRenderer(container, () => {});
  const items = Array.from({ length: 5000 }, (_, i) => makeItem(i));
  renderer.syncItems(items);

  // Scroll to the middle (item 2500 → offset 200000px)
  const inner = container.children[0];
  container.scrollTop = 200000;
  container.fire("scroll");

  const renderedTexts = inner.children.map((c) => collectText(c)).join("|");
  assert.ok(
    /message 24\d\d/.test(renderedTexts),
    `rendered items should be near scroll target: ${renderedTexts.slice(0, 120)}`,
  );
});

test("addUser and showError route through the virtual timeline", () => {
  createCounter = 0;
  const container = new FakeElement();
  const renderer = new MessageRenderer(container, () => {});

  renderer.syncItems([makeItem(0)]);
  renderer.addUser("local send");
  renderer.showError("boom");

  const inner = container.children[0];
  const texts = inner.children.map((c) => collectText(c)).join("|");
  assert.ok(texts.includes("local send"), "user message must be in the timeline");
  assert.ok(texts.includes("boom"), "error must be in the timeline");
});
