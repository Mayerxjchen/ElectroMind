/** Composer — the bottom input bar with mode / model / autonomy selectors.
 *
 * Supports:
 * - Session mode selector: Ask | Plan | Agent
 * - Model selector: Auto | named models
 * - Autonomy selector: Prompt | Auto-safe | Full access
 * - Execution target display
 * - Text input with Enter-to-send, Shift+Enter newline
 * - Steer vs enqueue mode indicator
 */

import React, { useCallback, useRef, useState } from "react";
import { useActiveThread, useActivityState } from "../useStore";

// ── Props ────────────────────────────────────────────────────────────

interface Props {
  onSend: (text: string, delivery: string) => void;
  onStop: () => void;
  onModeChange: (mode: string) => void;
  onModelChange: (model: string) => void;
  onAutonomyChange: (level: string) => void;
}

// ── Constants ────────────────────────────────────────────────────────

const MODES: { value: string; label: string; desc: string }[] = [
  { value: "agent", label: "Agent", desc: "执行完整任务" },
  { value: "plan", label: "Plan", desc: "调研并制定计划" },
  { value: "ask", label: "Ask", desc: "解释与查询" },
];

const MODELS: { value: string; label: string }[] = [
  { value: "auto", label: "Auto" },
  { value: "claude-fable-5", label: "Claude Fable 5" },
  { value: "claude-opus-5", label: "Claude Opus 5" },
  { value: "claude-sonnet-5", label: "Claude Sonnet 5" },
  { value: "deepseek-v4-pro", label: "DeepSeek V4 Pro" },
  { value: "deepseek-v4-flash", label: "DeepSeek V4 Flash" },
];

const AUTONOMY_LEVELS: { value: string; label: string }[] = [
  { value: "prompt", label: "Prompt" },
  { value: "auto-safe", label: "Auto-safe" },
  { value: "full-access", label: "Full access" },
];

// ── Component ────────────────────────────────────────────────────────

export const Composer: React.FC<Props> = ({
  onSend,
  onStop,
  onModeChange,
  onModelChange,
  onAutonomyChange,
}) => {
  const thread = useActiveThread();
  const activity = useActivityState();
  const [text, setText] = useState("");
  const [enqueueNext, setEnqueueNext] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const isRunning = activity === "running";

  const mode = thread?.sessionMode ?? "agent";
  const model = typeof thread?.model === "object" && thread?.model
    ? (thread.model as { kind: string; modelId?: string })
    : { kind: "auto" };
  const autonomy = thread?.autonomy ?? "prompt";

  const handleSend = useCallback(() => {
    const trimmed = text.trim();
    // Harness Spine: sending during a running turn is allowed — the wire
    // enqueues the input and sends an input/state ACK back.
    if (!trimmed) return;
    // Explicit "下一任务" → enqueue; otherwise steer (immediate) while
    // running, auto when idle.
    const delivery = enqueueNext
      ? "enqueue"
      : isRunning
        ? "immediate"
        : "auto";
    onSend(trimmed, delivery);
    setText("");
    setEnqueueNext(false);
  }, [text, onSend, enqueueNext, isRunning]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const targetLabel = thread?.executionTarget
    ? (thread.executionTarget as { kind: string }).kind === "ssh"
      ? `SSH · ${(thread.executionTarget as { host?: string }).host ?? ""}`
      : (thread.executionTarget as { kind: string }).kind === "sandbox"
        ? "Docker Sandbox"
        : "Local"
    : "Local";

  return (
    <div className="composer">
      <div className="composer-bar">
        {/* Mode selector */}
        <select
          className="composer-select"
          value={mode}
          onChange={(e) => onModeChange(e.target.value)}
          title="任务模式"
        >
          {MODES.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>

        {/* Model selector */}
        <select
          className="composer-select"
          value={model.kind === "named" ? model.modelId : "auto"}
          onChange={(e) => onModelChange(e.target.value)}
          title="模型选择"
        >
          {MODELS.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>

        {/* Autonomy selector */}
        <select
          className="composer-select"
          value={autonomy}
          onChange={(e) => onAutonomyChange(e.target.value)}
          title="自主程度"
        >
          {AUTONOMY_LEVELS.map((a) => (
            <option key={a.value} value={a.value}>
              {a.label}
            </option>
          ))}
        </select>

        {/* Execution target (read-only display) */}
        <span className="composer-target" title="执行目标">
          {targetLabel}
        </span>

        {/* Steer / enqueue selector (only while running) */}
        {isRunning && (
          <>
            <button
              className={`composer-steer-btn${enqueueNext ? "" : " active"}`}
              onClick={() => setEnqueueNext(false)}
              title="立即插入当前 Run（steer）"
            >
              steer
            </button>
            <button
              className={`composer-enqueue-btn${enqueueNext ? " active" : ""}`}
              onClick={() => setEnqueueNext(true)}
              title="作为下一任务排队执行（enqueue）"
            >
              下一任务
            </button>
          </>
        )}
      </div>

      <div className="composer-input-row">
        <textarea
          ref={inputRef}
          className="composer-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            isRunning
              ? "输入 steer 指令…"
              : thread?.sessionMode === "plan"
                ? "描述要规划的任务…"
                : "输入任务…"
          }
          rows={1}
          disabled={false}
        />
        {isRunning ? (
          <button className="composer-stop-btn" onClick={onStop} title="停止 (Esc)">
            ■
          </button>
        ) : (
          <button
            className="composer-send-btn"
            onClick={handleSend}
            disabled={!text.trim()}
            title="发送 (Enter)"
          >
            ↑
          </button>
        )}
      </div>
    </div>
  );
};
