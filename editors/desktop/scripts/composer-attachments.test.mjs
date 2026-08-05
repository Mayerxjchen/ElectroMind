/** D3.4 attachment menu (first version) tests — entries and support matrix.
 *
 *  Spec: "Add file / artifact / folder context / image / skill — hide or
 *  disable unsupported entries with a reason."  Pure module (no React) so it
 *  is fully unit-tested under node --test.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

const m = await import(
  new URL("../src/renderer/react/composer-attachments.ts", import.meta.url)
);

test("entries are well-formed with unique ids", () => {
  const entries = m.attachmentEntries();
  assert.ok(entries.length >= 5);
  const ids = new Set(entries.map((e) => e.id));
  assert.equal(ids.size, entries.length, "ids unique");
  for (const e of entries) {
    assert.ok(e.label && e.label.length > 0, `${e.id} has a label`);
    assert.ok(e.action === "file" || e.action === "event", `${e.id} has an action`);
  }
});

test("file-picking entries carry the right native-input hints", () => {
  assert.equal(m.attachmentEntry("file").action, "file");
  assert.equal(m.attachmentEntry("image").inputAccept, "image/*");
  assert.equal(m.attachmentEntry("folder").directory, true);
  assert.ok(m.isAttachmentSupported("file"));
  assert.ok(m.isAttachmentSupported("image"));
  assert.ok(m.isAttachmentSupported("folder"));
});

test("artifact is disabled with a reason (no backing flow)", () => {
  const a = m.attachmentEntry("artifact");
  assert.equal(a.supported, false);
  assert.ok(a.reason && a.reason.length > 0, "has a reason");
  assert.equal(m.isAttachmentSupported("artifact"), false);
});

test("skill is a supported event entry (skills-open contract)", () => {
  const s = m.attachmentEntry("skill");
  assert.equal(s.supported, true);
  assert.equal(s.action, "event");
  assert.equal(s.eventName, "electromind:skills-open");
});

test("attachmentRef inserts a visible reference, never empty text", () => {
  assert.equal(m.attachmentRef("water64.xyz"), "📎 water64.xyz");
  assert.equal(m.attachmentRef("  spaced  "), "📎 spaced");
  assert.equal(m.attachmentRef(""), "");
  assert.equal(m.attachmentRef("   "), "");
});
