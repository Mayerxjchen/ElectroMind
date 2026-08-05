/** Thread list (left sidebar) — Projects → Threads navigation (D3.1).
 *
 * Replaces the flat session list with Codex-style project grouping:
 * - Threads grouped by ``ThreadSummary.projectPath`` (no backend change)
 * - Project groups collapsible (persisted in localStorage)
 * - Project pinning (pinned groups sort first, persisted)
 * - Title search filter
 * - Per-thread status: running / waiting approval (Review) / error / idle
 *
 * Props/actions unchanged (onSwitchThread/onNewThread/onDeleteThread) —
 * the vanilla shell owns the DOM containers; this component only renders.
 */

import React, { useCallback, useMemo, useState } from "react";
import {
  useActiveThreadId,
  useSessions,
  useThread,
} from "../useStore";
import { getThreadStore } from "../../store/ThreadStore";
import type { ThreadSummary } from "../../store/types";

// ── Props ────────────────────────────────────────────────────────────

interface Props {
  onSwitchThread: (id: string) => void;
  onNewThread: () => void;
  onDeleteThread: (id: string) => void;
}

// ── localStorage helpers（折叠 / Pin 持久化） ───────────────────────

const COLLAPSED_KEY = "electromind-desktop-project-collapsed";
const PINNED_KEY = "electromind-desktop-project-pinned";

function readSet(key: string): Set<string> {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return new Set();
    return new Set(JSON.parse(raw) as string[]);
  } catch {
    return new Set();
  }
}

function writeSet(key: string, value: Set<string>): void {
  try {
    window.localStorage.setItem(key, JSON.stringify([...value]));
  } catch {
    /* localStorage 不可用时静默降级 */
  }
}

const UNGROUPED_LABEL = "其他会话";

/** D3.1: 分组显示名 = 路径最后一级目录名（同名项目靠 tooltip 完整路径区分）。 */
function projectDisplayName(path: string): string {
  const parts = path.split(/[\\/]+/).filter(Boolean);
  return parts.length > 0 ? parts[parts.length - 1] : UNGROUPED_LABEL;
}

/** D3.1: 分组内排序 —— Review > Running > Error > 原顺序。 */
function threadSortRank(id: string): number {
  const thread = getThreadStore().getState().threads[id];
  if (!thread) return 3;
  if (thread.pendingPermits.length > 0) return 0;
  if (thread.status === "running") return 1;
  if (thread.status === "error") return 2;
  return 3;
}

// ── Component ────────────────────────────────────────────────────────

export const ThreadList: React.FC<Props> = ({
  onSwitchThread,
  onNewThread,
  onDeleteThread,
}) => {
  const activeId = useActiveThreadId();
  const sessions = useSessions();
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(() =>
    readSet(COLLAPSED_KEY),
  );
  const [pinned, setPinned] = useState<Set<string>>(() => readSet(PINNED_KEY));

  const toggleCollapsed = useCallback((group: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      next.has(group) ? next.delete(group) : next.add(group);
      writeSet(COLLAPSED_KEY, next);
      return next;
    });
  }, []);

  const togglePinned = useCallback((group: string) => {
    setPinned((prev) => {
      const next = new Set(prev);
      next.has(group) ? next.delete(group) : next.add(group);
      writeSet(PINNED_KEY, next);
      return next;
    });
  }, []);

  // 过滤 + 分组（纯前端，不动 store）。
  // D3.1 增强：搜索同时匹配 Project 名与 Thread 标题；组内按
  // Review > Running > Error > 原顺序排序；显示名取目录 basename。
  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const byProject = new Map<string, ThreadSummary[]>();

    for (const s of sessions) {
      const key = (s.projectPath || "").trim() || UNGROUPED_LABEL;
      const display = projectDisplayName(key);
      const titleMatch = (s.title || "").toLowerCase().includes(q);
      const projectMatch = display.toLowerCase().includes(q);
      if (q && !titleMatch && !projectMatch) continue;
      const list = byProject.get(key) ?? [];
      list.push(s);
      byProject.set(key, list);
    }

    for (const list of byProject.values()) {
      list.sort((a, b) => threadSortRank(a.id) - threadSortRank(b.id));
    }

    const keys = [...byProject.keys()];
    keys.sort((a, b) => {
      const pa = pinned.has(a) ? 0 : 1;
      const pb = pinned.has(b) ? 0 : 1;
      if (pa !== pb) return pa - pb;
      return projectDisplayName(a).localeCompare(projectDisplayName(b));
    });
    return keys.map((path) => ({
      path,
      name: projectDisplayName(path),
      threads: byProject.get(path)!,
    }));
  }, [sessions, query, pinned]);

  return (
    <div className="thread-list">
      <div className="thread-list-header">
        <span className="thread-list-title">任务</span>
        <button
          className="thread-new-btn codicon codicon-plus"
          title="新建任务"
          onClick={onNewThread}
        />
      </div>

      {/* D3.1: 标题搜索 */}
      <div className="thread-search">
        <span className="thread-search-icon codicon codicon-search" aria-hidden="true" />
        <input
          className="thread-search-input"
          type="text"
          placeholder="搜索任务…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          spellCheck={false}
        />
      </div>

      <div className="thread-list-items">
        {groups.length === 0 ? (
          <div className="thread-list-empty">
            {query ? "没有匹配的任务" : "暂无任务"}
          </div>
        ) : (
          groups.map((group) => {
            // D3.1: 当前 Thread 所在 Project 自动展开（折叠状态对其失效）
            const isActiveGroup =
              activeId != null &&
              (sessions.find((s) => s.id === activeId)?.projectPath || "") ===
                group.path;
            return (
              <ProjectGroup
                key={group.path}
                path={group.path}
                name={group.name}
                threads={group.threads}
                activeId={activeId ?? ""}
                collapsed={collapsed.has(group.path) && !isActiveGroup}
                pinned={pinned.has(group.path)}
                onToggleCollapsed={() => toggleCollapsed(group.path)}
                onTogglePinned={() => togglePinned(group.path)}
                onSwitchThread={onSwitchThread}
                onDeleteThread={onDeleteThread}
              />
            );
          })
        )}
      </div>
    </div>
  );
};

// ── Project group ────────────────────────────────────────────────────

const ProjectGroup: React.FC<{
  path: string;
  name: string;
  threads: ThreadSummary[];
  activeId: string;
  collapsed: boolean;
  pinned: boolean;
  onToggleCollapsed: () => void;
  onTogglePinned: () => void;
  onSwitchThread: (id: string) => void;
  onDeleteThread: (id: string) => void;
}> = ({
  path,
  name,
  threads,
  activeId,
  collapsed,
  pinned,
  onToggleCollapsed,
  onTogglePinned,
  onSwitchThread,
  onDeleteThread,
}) => {
  return (
    <div className="project-group">
      <div
        className="project-group-header"
        role="button"
        tabIndex={0}
        onClick={onToggleCollapsed}
        onKeyDown={(e) => {
          if (e.key === "Enter") onToggleCollapsed();
        }}
        // 同名项目靠完整路径 tooltip 区分
        title={name === UNGROUPED_LABEL ? "未绑定项目的会话" : `${name} — ${path}`}
      >
        <span className={`project-chevron codicon ${collapsed ? "codicon-chevron-right" : "codicon-chevron-down"}`} />
        <span className="project-group-name">{name}</span>
        <span className="project-group-count">{threads.length}</span>
        <button
          className={`project-pin codicon ${pinned ? "codicon-pinned" : "codicon-pin"}`}
          title={pinned ? "取消置顶" : "置顶项目"}
          onClick={(e) => {
            e.stopPropagation();
            onTogglePinned();
          }}
        />
      </div>
      {!collapsed && (
        <div className="project-group-items">
          {threads.map((s) => (
            <ThreadRow
              key={s.id}
              session={s}
              isActive={s.id === activeId}
              onClick={() => onSwitchThread(s.id)}
              onDelete={() => onDeleteThread(s.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
};

// ── Row ──────────────────────────────────────────────────────────────

/** D3.1 状态：running / waiting approval (Review) / error / idle。 */
type RowStatus = "idle" | "running" | "review" | "error";

const ThreadRow: React.FC<{
  session: ThreadSummary;
  isActive: boolean;
  onClick: () => void;
  onDelete: () => void;
}> = ({ session, isActive, onClick, onDelete }) => {
  const thread = useThread(session.id);
  const status: RowStatus = useMemo(() => {
    if (thread?.status === "running") return "running";
    if (thread?.status === "error") return "error";
    if (thread && thread.pendingPermits.length > 0) return "review";
    return "idle";
  }, [thread]);

  const handleDelete = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      onDelete();
    },
    [onDelete],
  );

  const badge = useMemo(() => {
    const be = session.sandboxBackend;
    if (!be || be === "local") return null;
    if (be === "ssh") return <span className="thread-badge ssh">SSH</span>;
    return <span className="thread-badge container">{be}</span>;
  }, [session.sandboxBackend]);

  return (
    <div
      className={`thread-row ${isActive ? "active" : ""}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter") onClick();
      }}
    >
      <span className={`thread-status ${status}`} />
      <div className="thread-row-body">
        <span className="thread-row-title">{session.title || "未命名"}</span>
        <span className="thread-row-meta">
          {status === "review" && (
            <span className="thread-review-badge">Review</span>
          )}
          {session.relativeTime}
          {badge}
        </span>
      </div>
      <button
        className="thread-row-delete codicon codicon-close"
        title="删除会话"
        onClick={handleDelete}
      />
    </div>
  );
};
