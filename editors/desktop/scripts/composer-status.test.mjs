/** D3.4 composer status helpers tests — thread-scoped error surfacing.
 *
 *  Spec: "Errors shown near the Composer" — the composer surfaces the most
 *  recent error item of the active thread (dismissible).  Pure module
 *  (no React) so it is fully unit-tested under node --test.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

const m = await import(
  new URL("../src/renderer/react/composer-status.ts", import.meta.url)
);

const err = (message) => ({ kind: "error", payload: { message } });
const asst = (text) => ({ kind: "assistant_message", payload: { text } });

test("returns null when there are no error items", () => {
  assert.equal(m.lastErrorFromItems([]), null);
  assert.equal(m.lastErrorFromItems([asst("hi"), { kind: "tool_call", payload: {} }]), null);
});

test("returns the most recent error's message", () => {
  const items = [asst("a"), err("first error"), err("second error")];
  assert.equal(m.lastErrorFromItems(items), "second error");
});

test("errors after the last message win (tail order)", () => {
  const items = [err("early"), asst("done"), err("late")];
  assert.equal(m.lastErrorFromItems(items), "late");
});

test("an error with an empty message is skipped for a real one", () => {
  const items = [err(""), { kind: "error", payload: {} }, err("real")];
  assert.equal(m.lastErrorFromItems(items), "real");
});

test("non-object / malformed items do not throw", () => {
  assert.equal(m.lastErrorFromItems([null, undefined, "boom", { kind: "error", payload: { message: "ok" } }]), "ok");
  assert.equal(m.lastErrorFromItems([{ kind: "error" }]), null);
});
