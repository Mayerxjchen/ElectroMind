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

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useActiveThreadSnapshot, useActivityState, useBridgeActive } from "../useStore";
import {
  autonomyIsRisky,
  isRiskDismissed,
  markRiskDismissed,
  permissionText,
  riskNoteText,
} from "../composer-permissions.ts";
import { lastErrorFromItems } from "../composer-status.ts";
import {
  attachmentEntries,
  attachmentEntry,
  attachmentRef,
} from "../composer-attachments.ts";
import type { AttachmentId } from "../composer-attachments.ts";
import {
  composerInputDisabled,
  composerPlaceholder,
  deliveryForState,
  showSteerControls,
} from "../composer-delivery.ts";

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
  // Reactive snapshot: ThreadStore mutates the thread in place, so the
  // stable ref from useActiveThread would never re-render on field changes
  // (mode/model/autonomy selects, permission readout, error surface).
  const thread = useActiveThreadSnapshot();
  const activity = useActivityState();
  const [text, setText] = useState("");
  const [enqueueNext, setEnqueueNext] = useState(false);
  // D3.4: one-time Auto risk-note dismissal (lazy init from localStorage).
  const [riskDismissed, setRiskDismissed] = useState(isRiskDismissed);
  // D3.4: thread-scoped error surfacing — dismissed per error message, so a
  // NEW error re-appears even if the previous one was closed.
  const [dismissedError, setDismissedError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const isRunning = activity === "running";
  // P0 交互优先级：waiting_approval > running —— 等待审批时 Composer
  // 降级为非主操作区（隐藏 steer、禁用输入），审批卡成为唯一主焦点。
  const awaitingApproval = (thread?.pendingPermits?.length ?? 0) > 0;

  const mode = thread?.sessionMode ?? "agent";
  const model = typeof thread?.model === "object" && thread?.model
    ? (thread.model as { kind: string; modelId?: string })
    : { kind: "auto" };
  const autonomy = thread?.autonomy ?? "prompt";
  const risky = autonomyIsRisky(autonomy);
  const showRiskNote = risky && !riskDismissed;

  const lastError = lastErrorFromItems(thread?.items ?? []);
  const showError = lastError !== null && dismissedError !== lastError;

  const handleDismissRisk = useCallback(() => {
    setRiskDismissed(true);
    markRiskDismissed();
  }, []);

  const handleDismissError = useCallback(() => {
    setDismissedError(lastError);
  }, [lastError]);

  // ── D3.4: attachment menu (first version, keyboard-accessible) ──────
  const [attachOpen, setAttachOpen] = useState(false);
  const attachBoxRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pickerDirectoryRef = useRef(false);

  // ── D3.4: disconnected → composer disabled + reconnect entry ────────
  const bridgeActive = useBridgeActive();
  const disconnected = !bridgeActive;
  const inputDisabled = composerInputDisabled({ disconnected, awaitingApproval });

  const toggleAttach = useCallback(() => {
    setAttachOpen((v) => !v);
  }, []);

  const pickAttachment = useCallback((id: AttachmentId) => {
    const entry = attachmentEntry(id);
    if (!entry) return;
    setAttachOpen(false);
    if (entry.action === "event") {
      if (entry.eventName) {
        // Skills button: main agent listens for `electromind:skills-open`.
        window.dispatchEvent(new CustomEvent(entry.eventName));
      }
      return;
    }
    const input = fileInputRef.current;
    if (!input) return;
    pickerDirectoryRef.current = entry.directory === true;
    if (entry.directory) input.setAttribute("webkitdirectory", "");
    else input.removeAttribute("webkitdirectory");
    input.accept = entry.inputAccept ?? "";
    input.value = "";
    input.click();
  }, []);

  const onFilePicked = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    let refText: string;
    if (pickerDirectoryRef.current && files[0]) {
      // Folder picker: reference the top-level folder name.
      const rel =
        (files[0] as File & { webkitRelativePath?: string }).webkitRelativePath ?? "";
      const folder = rel.split("/")[0];
      refText = attachmentRef(folder || files[0].name);
    } else {
      refText = Array.from(files)
        .map((f) => attachmentRef(f.name))
        .filter(Boolean)
        .join(" ");
    }
    if (refText) {
      setText((prev) => (prev ? `${prev} ${refText}` : refText));
    }
  }, []);

  // D3-polish: the timeline's welcome empty state asks for focus.
  useEffect(() => {
    const focus = () => inputRef.current?.focus();
    window.addEventListener("electromind:focus-composer", focus);
    return () => window.removeEventListener("electromind:focus-composer", focus);
  }, []);

  // Close the attachment menu on outside click / Escape.
  useEffect(() => {
    if (!attachOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (attachBoxRef.current && !attachBoxRef.current.contains(e.target as Node)) {
        setAttachOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setAttachOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [attachOpen]);

  const handleReconnect = useCallback(() => {
    window.dispatchEvent(new CustomEvent("electromind:reconnect"));
  }, []);

  const handleSend = useCallback(() => {
    const trimmed = text.trim();
    // Harness Spine: sending during a running turn is allowed — the wire
    // enqueues the input and sends an input/state ACK back.
    if (!trimmed) return;
    // P0: waiting_approval / disconnected → null（新任务不能绕过当前审批）。
    const delivery = deliveryForState({
      disconnected,
      isRunning,
      awaitingApproval,
      enqueueNext,
    });
    if (!delivery) return;
    onSend(trimmed, delivery);
    setText("");
    setEnqueueNext(false);
  }, [text, onSend, enqueueNext, isRunning, disconnected, awaitingApproval]);

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
      {/* D3.4: disconnected → disabled input + reconnect entry */}
      {disconnected && (
        <div className="composer-disconnected" role="alert" data-composer-disconnected>
          <span className="composer-disconnected-text">连接已断开</span>
          <button
            type="button"
            className="composer-reconnect-btn"
            onClick={handleReconnect}
          >
            重新连接
          </button>
        </div>
      )}

      <div className="composer-bar">
        {/* D3.4: attachment menu (first version) — keyboard-accessible */}
        <div className="composer-attach" ref={attachBoxRef}>
          <button
            type="button"
            className="composer-attach-btn"
            onClick={toggleAttach}
            aria-haspopup="menu"
            aria-expanded={attachOpen}
            title="添加附件"
            disabled={disconnected}
          >
            ⊕
          </button>
          {attachOpen && (
            <div className="composer-attach-menu" role="menu" data-attach-menu>
              {attachmentEntries().map((entry) =>
                entry.supported ? (
                  <button
                    key={entry.id}
                    type="button"
                    role="menuitem"
                    className="composer-attach-item"
                    onClick={() => pickAttachment(entry.id)}
                  >
                    {entry.label}
                  </button>
                ) : (
                  <button
                    key={entry.id}
                    type="button"
                    role="menuitem"
                    className="composer-attach-item is-disabled"
                    disabled
                    title={entry.reason}
                  >
                    {entry.label}
                    <span className="composer-attach-reason">{entry.reason}</span>
                  </button>
                ),
              )}
            </div>
          )}
          {/* Hidden native picker for file / image / folder */}
          <input
            ref={fileInputRef}
            type="file"
            hidden
            onChange={onFilePicked}
            aria-hidden="true"
            tabIndex={-1}
          />
        </div>

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

        {/* D3.4: explicit permission copy — never a bare "Auto" or an icon */}
        <span
          className="composer-permission"
          data-permission-text
          data-risky={risky ? "true" : "false"}
          title={permissionText(autonomy)}
        >
          {permissionText(autonomy)}
        </span>

        {/* Execution target (read-only display) */}
        <span className="composer-target" title="执行目标">
          {targetLabel}
        </span>

        {/* Steer / enqueue selector — 仅运行中且不在等待审批时显示
            （P0：等待审批时 Composer 降级，审批卡是唯一主焦点） */}
        {showSteerControls({ isRunning, awaitingApproval }) && (
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

      {/* D3.4: one-time risk note for auto-approved runs */}
      {showRiskNote && (
        <div className="composer-risk-note" role="note" data-risk-note>
          <span className="composer-risk-note-text">{riskNoteText(autonomy)}</span>
          <button
            type="button"
            className="composer-risk-note-dismiss"
            onClick={handleDismissRisk}
            aria-label="知道了"
          >
            知道了
          </button>
        </div>
      )}

      {/* D3.4: most recent thread error, shown near the input, dismissible */}
      {showError && (
        <div className="composer-error" role="alert" data-composer-error>
          <span className="composer-error-icon" aria-hidden="true">⚠</span>
          <span className="composer-error-text">{lastError}</span>
          <button
            type="button"
            className="composer-error-dismiss"
            onClick={handleDismissError}
            aria-label="关闭错误提示"
          >
            ×
          </button>
        </div>
      )}

      <div className="composer-input-row">
        <textarea
          ref={inputRef}
          className="composer-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={composerPlaceholder({
            awaitingApproval,
            isRunning,
            mode,
          })}
          rows={1}
          disabled={inputDisabled}
        />
        {isRunning && !awaitingApproval ? (
          <button
            className="composer-stop-btn"
            onClick={onStop}
            title="停止 (Esc)"
            disabled={disconnected}
          >
            ■
          </button>
        ) : (
          <button
            className="composer-send-btn"
            onClick={handleSend}
            disabled={!text.trim() || inputDisabled}
            title="发送 (Enter)"
          >
            ↑
          </button>
        )}
      </div>
    </div>
  );
};
