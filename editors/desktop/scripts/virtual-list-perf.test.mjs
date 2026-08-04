/** VirtualList performance contract tests (Section IX).
 *
 * With 5000 items, only viewport-visible items + overscan are mounted;
 * scrolling re-renders a bounded window; total inner height matches the
 * full content size.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

// ── Minimal DOM stub (no jsdom dependency) ────────────────────────────

class FakeElement {
  constructor(tag = "div") {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.style = {};
    this.listeners = {};
    this.scrollTop = 0;
    this.clientHeight = 600; // viewport height
    this.scrollHeight = 0;
    this.className = "";
    this.parentNode = null;
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
  addEventListener(name, fn) {
    (this.listeners[name] ??= []).push(fn);
  }
  fire(name) {
    for (const fn of this.listeners[name] ?? []) fn();
  }
  querySelectorAll() {
    return [];
  }
}

let createCounter = 0;
const realCreateElement = globalThis.document?.createElement;
globalThis.document = {
  createElement: (tag) => {
    createCounter++;
    return new FakeElement(tag);
  },
};
// ResizeObserver stub (never fires — heights come from estimates)
globalThis.ResizeObserver = class {
  observe() {}
  disconnect() {}
  unobserve() {}
};
globalThis.requestAnimationFrame = (fn) => fn();

// Import AFTER stubbing DOM
const { VirtualList } = await import(
  new URL("../src/renderer/VirtualList.ts", import.meta.url)
);

// ── Tests ─────────────────────────────────────────────────────────────

test("5000 items: only visible + overscan are mounted", () => {
  createCounter = 0;
  const container = new FakeElement();
  const renderCalls = [];
  const list = new VirtualList(container, {
    itemCount: 5000,
    renderItem: (i, el) => {
      el.textContent = `item-${i}`;
      renderCalls.push(i);
    },
    estimateHeight: () => 80,
    overscan: 3,
  });

  // Initial render: 600px viewport / 80px items = 7.5 → ~8 + overscan
  assert.ok(
    renderCalls.length <= 16,
    `initial mount should be bounded, got ${renderCalls.length}`,
  );
  assert.ok(renderCalls.length >= 8, "must render at least the viewport");
  assert.ok(
    renderCalls.every((i) => i >= 0 && i < 5000),
    "indices must be in range",
  );

  // Inner spacer represents the full 5000-item height
  const inner = container.children[0];
  assert.equal(inner.style.height, "400000px"); // 5000 × 80
});

test("scrolling far down re-renders a bounded window", () => {
  createCounter = 0;
  const container = new FakeElement();
  const renderCalls = [];
  const list = new VirtualList(container, {
    itemCount: 5000,
    renderItem: (i, el) => {
      el.textContent = `item-${i}`;
      renderCalls.push(i);
    },
    estimateHeight: () => 80,
    overscan: 3,
  });
  renderCalls.length = 0;

  // Scroll to the middle (item 2500 → offset 200000px)
  container.scrollTop = 200000;
  container.fire("scroll");

  assert.ok(
    renderCalls.length <= 16,
    `scrolled mount should stay bounded, got ${renderCalls.length}`,
  );
  const nearMiddle = renderCalls.some((i) => i >= 2400 && i <= 2600);
  assert.ok(nearMiddle, `render should be near scroll target: ${renderCalls}`);
});

test("total mounted elements never grows with item count", () => {
  createCounter = 0;
  const container = new FakeElement();
  const list = new VirtualList(container, {
    itemCount: 5000,
    renderItem: () => {},
    estimateHeight: () => 80,
  });
  const mountedAfterInit = createCounter;

  // Scroll through several positions
  for (const top of [0, 80000, 160000, 240000, 320000, 399000]) {
    container.scrollTop = top;
    container.fire("scroll");
  }
  // Element pool is bounded — no unbounded DOM growth
  assert.ok(
    createCounter <= mountedAfterInit + 16,
    `DOM elements must not grow unboundedly: ${createCounter}`,
  );
});
