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

test("P6: attachmentEntriesForFlags hides skill under compact composer", () => {
  // compact_composer=true 且 legacy 面板仍开 → 隐藏 Skill 按钮
  const compact = m.attachmentEntriesForFlags({
    compactComposer: true,
    legacySkillsPanel: true,
  });
  assert.ok(!compact.some((e) => e.id === "skill"), "compact 隐藏 Skill 按钮");
  assert.ok(compact.some((e) => e.id === "file"), "文件入口保留");
  assert.ok(compact.some((e) => e.id === "image"), "图片入口保留");
  assert.ok(compact.some((e) => e.id === "folder"), "文件夹入口保留");

  const normal = m.attachmentEntriesForFlags({
    compactComposer: false,
    legacySkillsPanel: true,
  });
  assert.ok(normal.some((e) => e.id === "skill"), "非 compact 且 legacy 开 → 保留 Skill 按钮");
  assert.equal(normal.length, m.ATTACHMENT_ENTRIES.length);
});

test("P4: legacy_skills_panel=false hides skill entry regardless of compact", () => {
  // 默认 flag（legacy_skills_panel=false）→ Skill 入口隐藏（fail-closed）
  const closed = m.attachmentEntriesForFlags({
    compactComposer: false,
    legacySkillsPanel: false,
  });
  assert.ok(!closed.some((e) => e.id === "skill"), "legacy 关 → 隐藏 Skill 按钮");
  assert.equal(closed.length, m.ATTACHMENT_ENTRIES.length - 1);
});

test("attachmentRef inserts a visible reference, never empty text", () => {
  assert.equal(m.attachmentRef("water64.xyz"), "📎 water64.xyz");
  assert.equal(m.attachmentRef("  spaced  "), "📎 spaced");
  assert.equal(m.attachmentRef(""), "");
  assert.equal(m.attachmentRef("   "), "");
});
