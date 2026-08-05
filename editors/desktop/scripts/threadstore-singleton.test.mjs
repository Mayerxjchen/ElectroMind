/** P4.6: ThreadStore 单例断言 — 运行时只允许一个实例。 */

import assert from "node:assert/strict";
import { test } from "node:test";

const { ThreadStore, getThreadStore, resetThreadStore } = await import(
  new URL("../src/renderer/store/ThreadStore.ts", import.meta.url)
);

test("double construction of ThreadStore throws", () => {
  resetThreadStore();
  getThreadStore(); // 第一个实例
  assert.throws(() => new ThreadStore(), /单例断言失败/);
  resetThreadStore();
});

test("resetThreadStore allows a fresh instance", () => {
  resetThreadStore();
  const a = getThreadStore();
  resetThreadStore();
  const b = getThreadStore();
  assert.notEqual(a, b);
});
