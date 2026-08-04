/** Inspector shell (right panel) — tab bar + content area.
 *
 * Tabs: Context | Changes | Files | Runs | Artifacts
 * Content is rendered by tab-specific panels.  The shell itself
 * just manages tab state and renders the chrome.
 */

import React, { useEffect, useState } from "react";
import { useActiveThread, useExecutionContextState, useSkillsState, useActiveRun } from "../useStore";
import { getThreadStore } from "../../store/ThreadStore";
import { DiffViewer } from "./DiffViewer";

// ── Tab definitions ──────────────────────────────────────────────────

type TabId = "context" | "changes" | "files" | "runs" | "artifacts";

const TABS: { id: TabId; label: string; badge?: () => number | null }[] = [
  {
    id: "context",
    label: "Context",
    badge: () => {
      // eslint-disable-next-line react-hooks/rules-of-hooks
      const ec = useExecutionContextState();
      return ec?.documents.length ?? null;
    },
  },
  { id: "changes", label: "Changes" },
  { id: "files", label: "Files" },
  {
    id: "runs",
    label: "Runs",
    badge: () => {
      // eslint-disable-next-line react-hooks/rules-of-hooks
      const run = useActiveRun();
      return run ? 1 : null;
    },
  },
  { id: "artifacts", label: "Artifacts" },
];

// ── Props ────────────────────────────────────────────────────────────

interface Props {
  onTabChange?: (tab: TabId) => void;
}

// ── Component ────────────────────────────────────────────────────────

export const InspectorShell: React.FC<Props> = ({ onTabChange }) => {
  const [activeTab, setActiveTab] = useState<TabId>("context");
  const ec = useExecutionContextState();
  const skills = useSkillsState();
  const run = useActiveRun();

  const handleTabClick = (tab: TabId) => {
    setActiveTab(tab);
    onTabChange?.(tab);
  };

  return (
    <div className="inspector-shell">
      <div className="inspector-tabs">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`inspector-tab ${activeTab === tab.id ? "active" : ""}`}
            onClick={() => handleTabClick(tab.id)}
          >
            {tab.label}
            {tab.id === "context" && ec?.documents.length ? (
              <span className="inspector-badge">{ec.documents.length}</span>
            ) : null}
            {tab.id === "runs" && run ? (
              <span className="inspector-badge running">●</span>
            ) : null}
          </button>
        ))}
      </div>
      <div className="inspector-content">
        {activeTab === "context" && <ContextPanel ec={ec} skills={skills} />}
        {activeTab === "changes" && <ChangesPanel />}
        {activeTab === "files" && <FilesPanel />}
        {activeTab === "runs" && <RunsPanel run={run} />}
        {activeTab === "artifacts" && <ArtifactsPanel />}
      </div>
    </div>
  );
};

// ── Sub-panels ───────────────────────────────────────────────────────

const ContextPanel: React.FC<{
  ec: ReturnType<typeof useExecutionContextState>;
  skills: ReturnType<typeof useSkillsState>;
}> = ({ ec, skills }) => {
  return (
    <div className="context-panel">
      {ec?.documents.length ? (
        <details open>
          <summary>
            执行上下文 ({ec.target} · {ec.profileId})
          </summary>
          <ul className="context-docs">
            {ec.documents.map((d, i) => (
              <li key={i} className="context-doc">
                <span className="context-doc-path">{d.remote_path}</span>
                <span className="context-doc-meta">
                  {d.size} bytes · {d.sha256.slice(0, 8)}
                </span>
              </li>
            ))}
          </ul>
          {ec.diagnostics.length > 0 && (
            <ul className="context-diags">
              {ec.diagnostics.map((d, i) => (
                <li key={i} className={`context-diag context-diag-${d.severity}`}>
                  <span className="context-diag-code">{d.code}</span>
                  <span>{d.message}</span>
                </li>
              ))}
            </ul>
          )}
        </details>
      ) : null}
      {skills?.skills.length ? (
        <details>
          <summary>Skills ({skills.skills.length})</summary>
          <ul className="context-skills">
            {skills.skills.map((s, i) => (
              <li key={i} className="context-skill">
                <span className={`skill-status ${s.status}`}>{s.name}</span>
                <span className="skill-source">{s.source}</span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {!ec?.documents.length && !skills?.skills.length && (
        <div className="context-empty">暂无上下文信息</div>
      )}
    </div>
  );
};

const RunsPanel: React.FC<{
  run: ReturnType<typeof useActiveRun>;
}> = ({ run }) => {
  if (!run) {
    return <PlaceholderPanel text="暂无活动运行" />;
  }
  return (
    <div className="runs-panel">
      <div className="run-card">
        <div className="run-header">
          <span className={`run-phase ${run.phase}`}>{run.phase}</span>
          <span className="run-time">
            {((Date.now() - run.startedAt) / 1000).toFixed(0)}s
          </span>
        </div>
        <div className="run-stats">
          <span>工具调用: {run.toolCallsIssued}</span>
          <span>等待审批: {run.pendingApprovals.length}</span>
        </div>
      </div>
    </div>
  );
};

/** Changes tab — file_change items from the active thread's timeline,
 *  rendered as a DiffViewer with per-file details and copy-patch. */
const ChangesPanel: React.FC = () => {
  const thread = useActiveThread();
  const changes = (thread?.items ?? []).filter(
    (it) => it.kind === "file_change",
  );
  const fileChanges = changes.map((it) => {
    const p = it.payload as Record<string, unknown>;
    const additions = Number(p.additions ?? 0);
    const deletions = Number(p.deletions ?? 0);
    const status = String(p.status ?? "modified") as "added" | "modified" | "deleted";
    // Use the REAL hunks from the backend (actual old/new text) verbatim;
    // only fall back to the line-count summary when no text is available.
    const rawHunks = Array.isArray(p.hunks) ? (p.hunks as Array<unknown>) : [];
    const hunks: Array<{
      header: string;
      lines: Array<{ kind: "context" | "addition" | "deletion"; content: string }>;
    }> = rawHunks.map((h) => {
      const hunk = h as { header?: string; lines?: Array<{ kind?: string; content?: string }> };
      return {
        header: String(hunk.header ?? ""),
        lines: (hunk.lines ?? []).map((l) => ({
          kind: (String(l.kind ?? "context")) as "context" | "addition" | "deletion",
          content: String(l.content ?? ""),
        })),
      };
    });
    return {
      path: String(p.path ?? ""),
      status,
      additions,
      deletions,
      toolCallId: String(p.tool_call_id ?? ""),
      hunks,
    };
  });
  if (!fileChanges.length) {
    return <PlaceholderPanel text="暂无文件变更" />;
  }
  return (
    <div className="changes-panel">
      <div className="changes-summary">
        {fileChanges.length} 个文件变更 · +
        {fileChanges.reduce((s, c) => s + c.additions, 0)} −
        {fileChanges.reduce((s, c) => s + c.deletions, 0)}
      </div>
      <DiffViewer changes={fileChanges} />
    </div>
  );
};

/** Files tab — project tree with in-panel content preview + actions. */
const FilesPanel: React.FC = () => {
  const [selected, setSelected] = useState<string | null>(null);
  const [meta, setMeta] = useState<Record<string, unknown> | null>(null);
  const [preview, setPreview] = useState<{
    kind: string;
    text?: string;
    reason?: string;
    truncated?: boolean;
  } | null>(null);
  const projectNodes = useProjectTreeNodes();

  const handleSelect = async (path: string) => {
    setSelected(path);
    setPreview(null);
    const ref = { source: "project", path } as never;
    try {
      const m = await window.desktop.getFileMetadata(ref);
      setMeta(m as unknown as Record<string, unknown>);
      const p = await window.desktop.previewFile?.(ref);
      if (p) {
        setPreview({
          kind: p.kind,
          text: p.text,
          reason: p.reason,
          truncated: p.truncated,
        });
      }
    } catch {
      setMeta(null);
    }
  };

  if (!projectNodes.length) {
    return <PlaceholderPanel text="选择文件以查看" />;
  }
  return (
    <div className="files-panel">
      <ul className="files-tree">
        {projectNodes.map((node) => (
          <TreeRow
            key={String((node as { id?: string }).id ?? "")}
            node={node as TreeNode}
            depth={0}
            selected={selected}
            onSelect={handleSelect}
          />
        ))}
      </ul>
      {meta && (
        <div className="file-meta">
          <div className="file-meta-path">{String(meta.path ?? "")}</div>
          <div className="file-meta-size">{String(meta.size ?? "")} bytes</div>
          <button
            className="inspector-action"
            onClick={() => {
              void window.desktop.copyFilePath(
                { source: "project", path: selected ?? "" } as never,
                "absolute",
              );
            }}
          >
            复制绝对路径
          </button>
          <button
            className="inspector-action"
            onClick={() => {
              void window.desktop.exportFile(
                { source: "project", path: selected ?? "" } as never,
              );
            }}
          >
            导出
          </button>
        </div>
      )}
      {preview && (
        <div className="file-preview">
          {preview.reason ? (
            <div className="file-preview-reason">{preview.reason}</div>
          ) : (
            <>
              <pre className="file-preview-text">{preview.text ?? ""}</pre>
              {preview.truncated && (
                <div className="file-preview-truncated">内容过长，已截断预览</div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
};

/** Tree node shape from the project tree API. */
interface TreeNode {
  id: string;
  label: string;
  kind: "dir" | "file";
  children?: TreeNode[];
}

/** Recursive tree row — directories expand (never preview), files select
 *  (preview).  Only leaf "file" nodes trigger the preview flow. */
const TreeRow: React.FC<{
  node: TreeNode;
  depth: number;
  selected: string | null;
  onSelect: (path: string) => void;
}> = ({ node, depth, selected, onSelect }) => {
  const [expanded, setExpanded] = useState(false);
  const isDir = node.kind === "dir";
  const isSelected = !isDir && selected === node.id;

  return (
    <>
      <li className="tree-row">
        {isDir ? (
          <button
            className={`tree-node tree-dir ${expanded ? "expanded" : ""}`}
            style={{ paddingLeft: 8 + depth * 14 }}
            onClick={() => setExpanded((e) => !e)}
          >
            <span className="tree-caret">{expanded ? "▾" : "▸"}</span>
            {node.label}
          </button>
        ) : (
          <button
            className={`tree-node tree-file ${isSelected ? "active" : ""}`}
            style={{ paddingLeft: 20 + depth * 14 }}
            onClick={() => onSelect(node.id)}
          >
            {node.label}
          </button>
        )}
      </li>
      {isDir &&
        expanded &&
        (node.children ?? []).map((child) => (
          <TreeRow
            key={child.id}
            node={child}
            depth={depth + 1}
            selected={selected}
            onSelect={onSelect}
          />
        ))}
    </>
  );
};

/** Artifacts tab — artifact list with IN-PANEL preview + export actions. */
const ArtifactsPanel: React.FC = () => {
  const [artifacts, setArtifacts] = useState<
    Array<{ name: string; path: string; size: number }>
  >([]);
  const [preview, setPreview] = useState<{
    name: string;
    kind: string;
    text?: string;
    reason?: string;
  } | null>(null);

  useEffect(() => {
    window.desktop
      .listArtifacts()
      .then((list) =>
        setArtifacts(
          list.map((a) => ({
            name: a.name,
            path: a.path,
            size: a.size,
          })),
        ),
      )
      .catch(() => setArtifacts([]));
  }, []);

  const handlePreview = async (path: string, name: string) => {
    try {
      const p = await window.desktop.readArtifact(path);
      setPreview({ name, kind: p.kind, text: p.text, reason: p.reason });
    } catch {
      setPreview({ name, kind: "binary", reason: "预览失败" });
    }
  };

  if (!artifacts.length) {
    return <PlaceholderPanel text="暂无产物" />;
  }
  return (
    <div className="artifacts-panel">
      <ul className="artifacts-list">
        {artifacts.map((a) => (
          <li key={a.path} className="artifact-item">
            <span className="artifact-name">{a.name}</span>
            <span className="artifact-meta">
              {a.size} bytes · {a.path}
            </span>
            <div className="artifact-actions">
              <button
                className="inspector-action"
                onClick={() => void handlePreview(a.path, a.name)}
              >
                预览
              </button>
              <button
                className="inspector-action"
                onClick={() => void window.desktop.openArtifact(a.path)}
              >
                在系统中打开
              </button>
              <button
                className="inspector-action"
                onClick={() =>
                  void window.desktop.exportFile(
                    { source: "project", path: a.path } as never,
                    a.name,
                  )
                }
              >
                导出
              </button>
            </div>
          </li>
        ))}
      </ul>
      {preview && (
        <div className="artifact-preview">
          <div className="artifact-preview-header">{preview.name}</div>
          {preview.reason ? (
            <div className="artifact-preview-reason">{preview.reason}</div>
          ) : (
            <pre className="artifact-preview-text">{preview.text ?? ""}</pre>
          )}
        </div>
      )}
    </div>
  );
};

const PlaceholderPanel: React.FC<{ text: string }> = ({ text }) => (
  <div className="inspector-placeholder">{text}</div>
);

/** Project tree nodes from the store (shared with the vanilla file tree). */
function useProjectTreeNodes(): unknown[] {
  return getThreadStore().getState().projectTreeNodes;
}
