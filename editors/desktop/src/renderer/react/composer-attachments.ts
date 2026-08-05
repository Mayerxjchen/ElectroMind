/** D3.4 attachment menu (first version) — entries and support matrix.
 *
 *  Spec (§ D3.4): "Add file / artifact / folder context / image / skill —
 *  hide or disable unsupported entries with a reason."
 *
 *  The wire currently carries no attachment payload, so file-picking entries
 *  are ``supported`` and insert a visible reference into the outgoing text
 *  (honest, end-to-end at the text level); entries without a backing flow
 *  are ``supported: false`` with a human reason.
 *
 *  Pure module (no React) so it is unit-testable under node --test; the
 *  React Composer consumes it.
 */

export type AttachmentId = "file" | "image" | "folder" | "artifact" | "skill";

export type AttachmentEntry = {
  id: AttachmentId;
  label: string;
  /** Whether the entry has a working action in this build. */
  supported: boolean;
  /** How the entry acts when activated. */
  action: "file" | "event";
  /** CustomEvent name dispatched for ``action: "event"`` entries. */
  eventName?: string;
  /** Human reason shown when unsupported. */
  reason?: string;
  /** Native ``<input type="file">`` accept hint for file-picking entries. */
  inputAccept?: string;
  /** Folder picker (``webkitdirectory``). */
  directory?: boolean;
};

export const ATTACHMENT_ENTRIES: readonly AttachmentEntry[] = [
  { id: "file", label: "文件", supported: true, action: "file" },
  { id: "image", label: "图片", supported: true, action: "file", inputAccept: "image/*" },
  { id: "folder", label: "文件夹", supported: true, action: "file", directory: true },
  {
    id: "artifact",
    label: "Artifact",
    supported: false,
    action: "event",
    reason: "在右侧 Artifacts 面板中选择",
  },
  {
    id: "skill",
    label: "Skill",
    supported: true,
    action: "event",
    eventName: "electromind:skills-open",
  },
];

/** The attachment entries in display order. */
export function attachmentEntries(): readonly AttachmentEntry[] {
  return ATTACHMENT_ENTRIES;
}

export function attachmentEntry(id: string): AttachmentEntry | undefined {
  return ATTACHMENT_ENTRIES.find((e) => e.id === id);
}

/** Whether an attachment entry has a working action in this build. */
export function isAttachmentSupported(id: string): boolean {
  return attachmentEntry(id)?.supported ?? false;
}

/** Reference text inserted into the outgoing message for a picked file. */
export function attachmentRef(name: string): string {
  const trimmed = name.trim();
  return trimmed ? `📎 ${trimmed}` : "";
}
