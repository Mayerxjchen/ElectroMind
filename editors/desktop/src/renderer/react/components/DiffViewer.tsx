/** DiffViewer — renders file changes with accept/reject actions.
 *
 * Supports:
 * - Inline diff display with +/− line coloring
 * - File-level accept / reject
 * - "Open in editor" button
 * - Copy patch action
 * - Change summary (N files changed, +M −K lines)
 */

import React, { useState } from "react";

// ── Types ────────────────────────────────────────────────────────────

interface FileChange {
  path: string;
  status: "added" | "modified" | "deleted";
  additions: number;
  deletions: number;
  hunks: DiffHunk[];
}

interface DiffHunk {
  header: string;
  lines: DiffLine[];
}

interface DiffLine {
  kind: "context" | "addition" | "deletion";
  content: string;
  oldLine?: number;
  newLine?: number;
}

// ── Props ────────────────────────────────────────────────────────────

interface Props {
  changes: FileChange[];
  onAcceptFile?: (path: string) => void;
  onRejectFile?: (path: string) => void;
  onAcceptAll?: () => void;
  onRejectAll?: () => void;
  onOpenInEditor?: (path: string) => void;
}

// ── Patch builder (unified-diff-ish) ─────────────────────────────────

export function buildPatch(changes: FileChange[]): string {
  const parts: string[] = [];
  for (const file of changes) {
    const header = `--- a/${file.path}\n+++ b/${file.path}`;
    const body = file.hunks.length
      ? file.hunks
          .map((h) => `${h.header}\n${h.lines.map((l) => `${l.kind === "addition" ? "+" : l.kind === "deletion" ? "-" : " "}${l.content}`).join("\n")}`)
          .join("\n")
      : `@@ -0,0 +1,${file.additions} @@\n${Array.from({ length: file.additions }, () => "+").join("")}`;
    parts.push(`${header}\n${body}`);
  }
  return parts.join("\n");
}

// ── Component ────────────────────────────────────────────────────────

export const DiffViewer: React.FC<Props> = ({
  changes,
  onAcceptFile,
  onRejectFile,
  onAcceptAll,
  onRejectAll,
  onOpenInEditor,
}) => {
  const [expandedFiles, setExpandedFiles] = useState<Set<string>>(new Set());

  if (!changes.length) {
    return <div className="diff-empty">暂无文件变更</div>;
  }

  const totalAdditions = changes.reduce((s, c) => s + c.additions, 0);
  const totalDeletions = changes.reduce((s, c) => s + c.deletions, 0);

  const toggleFile = (path: string) => {
    setExpandedFiles((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  return (
    <div className="diff-viewer">
      {/* Summary */}
      <div className="diff-summary">
        <span className="diff-summary-text">
          {changes.length} files changed
          <span className="diff-additions"> +{totalAdditions}</span>
          <span className="diff-deletions"> −{totalDeletions}</span>
        </span>
        <div className="diff-summary-actions">
          <button
            className="diff-btn"
            title="复制 unified patch"
            onClick={() => {
              void navigator.clipboard.writeText(buildPatch(changes));
            }}
          >
            复制 Patch
          </button>
          {onAcceptAll && (
            <button className="diff-btn diff-btn-accept" onClick={onAcceptAll}>
              全部接受
            </button>
          )}
          {onRejectAll && (
            <button className="diff-btn diff-btn-reject" onClick={onRejectAll}>
              全部放弃
            </button>
          )}
        </div>
      </div>

      {/* File list */}
      {changes.map((file) => (
        <div key={file.path} className="diff-file">
          <div
            className="diff-file-header"
            onClick={() => toggleFile(file.path)}
          >
            <span className={`diff-file-status diff-status-${file.status}`}>
              {file.status === "added" ? "A" : file.status === "deleted" ? "D" : "M"}
            </span>
            <span className="diff-file-path">{file.path}</span>
            <span className="diff-file-stats">
              <span className="diff-additions">+{file.additions}</span>
              <span className="diff-deletions">−{file.deletions}</span>
            </span>
            <div className="diff-file-actions">
              {onAcceptFile && (
                <button
                  className="diff-btn-icon diff-btn-accept"
                  title="接受"
                  onClick={(e) => { e.stopPropagation(); onAcceptFile(file.path); }}
                >✓</button>
              )}
              {onRejectFile && (
                <button
                  className="diff-btn-icon diff-btn-reject"
                  title="放弃"
                  onClick={(e) => { e.stopPropagation(); onRejectFile(file.path); }}
                >✗</button>
              )}
              {onOpenInEditor && (
                <button
                  className="diff-btn-icon"
                  title="在编辑器中打开"
                  onClick={(e) => { e.stopPropagation(); onOpenInEditor(file.path); }}
                >↗</button>
              )}
            </div>
          </div>

          {/* Hunks (expandable) */}
          {expandedFiles.has(file.path) && (
            <div className="diff-hunks">
              {file.hunks.map((hunk, hi) => (
                <div key={hi} className="diff-hunk">
                  <div className="diff-hunk-header">{hunk.header}</div>
                  {hunk.lines.map((line, li) => (
                    <div
                      key={li}
                      className={`diff-line diff-line-${line.kind}`}
                    >
                      <span className="diff-line-num">
                        {line.oldLine ?? " "}
                      </span>
                      <span className="diff-line-num">
                        {line.newLine ?? " "}
                      </span>
                      <span className="diff-line-sign">
                        {line.kind === "addition" ? "+" : line.kind === "deletion" ? "−" : " "}
                      </span>
                      <span className="diff-line-content">{line.content}</span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
};
