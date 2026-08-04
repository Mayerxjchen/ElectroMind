/** Thread list (left sidebar) — renders the session list with status indicators.
 *
 * Replaces the ad-hoc DOM building in ``renderSessionList()``.
 * Each row shows:
 * - Running indicator (pulsing dot)
 * - Thread title
 * - Execution target badge (Local / Docker / SSH)
 * - Relative time
 *
 * Clicking a thread calls ``SessionManager.switchThread()`` without
 * stopping the previous thread's agent.
 */

import React, { useCallback, useMemo } from "react";
import {
  useActiveThreadId,
  useSessions,
  useThread,
} from "../useStore";
import type { ThreadSummary } from "../../store/types";

// ── Props ────────────────────────────────────────────────────────────

interface Props {
  onSwitchThread: (id: string) => void;
  onNewThread: () => void;
  onDeleteThread: (id: string) => void;
}

// ── Component ────────────────────────────────────────────────────────

export const ThreadList: React.FC<Props> = ({
  onSwitchThread,
  onNewThread,
  onDeleteThread,
}) => {
  const activeId = useActiveThreadId();
  const sessions = useSessions();

  return (
    <div className="thread-list">
      <div className="thread-list-header">
        <span className="thread-list-title">Threads</span>
        <button
          className="thread-new-btn codicon codicon-plus"
          title="新建 Thread"
          onClick={onNewThread}
        />
      </div>
      <div className="thread-list-items">
        {sessions.length === 0 ? (
          <div className="thread-list-empty">暂无会话</div>
        ) : (
          sessions.map((s) => (
            <ThreadRow
              key={s.id}
              session={s}
              isActive={s.id === activeId}
              onClick={() => onSwitchThread(s.id)}
              onDelete={() => onDeleteThread(s.id)}
            />
          ))
        )}
      </div>
    </div>
  );
};

// ── Row ──────────────────────────────────────────────────────────────

const ThreadRow: React.FC<{
  session: ThreadSummary;
  isActive: boolean;
  onClick: () => void;
  onDelete: () => void;
}> = ({ session, isActive, onClick, onDelete }) => {
  const thread = useThread(session.id);
  const isRunning = thread?.status === "running";

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
      <span className={`thread-status ${isRunning ? "running" : "idle"}`} />
      <div className="thread-row-body">
        <span className="thread-row-title">{session.title || "未命名"}</span>
        <span className="thread-row-meta">
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
