/** Mode Picker —— P5：Ask / Plan / Agent 模式选择（点 Composer 模式 chip）。
 *
 * 选择经 onSelect(mode) 写回 Thread 的 sessionMode；
 * 与 /ask /plan /agent 走同一状态（Registry 也写同一 store 字段）。
 */

import React, { useEffect, useRef } from "react";

const MODES: { value: string; label: string; desc: string }[] = [
  { value: "agent", label: "Agent", desc: "执行完整任务" },
  { value: "plan", label: "Plan", desc: "调研并制定计划" },
  { value: "ask", label: "Ask", desc: "解释与查询" },
];

interface Props {
  open: boolean;
  current: string;
  onSelect: (mode: string) => void;
  onClose: () => void;
}

export const ModePicker: React.FC<Props> = ({ open, current, onSelect, onClose }) => {
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="model-picker" ref={boxRef} role="menu" data-mode-picker>
      <div className="model-picker-group-label">模式</div>
      {MODES.map((m) => (
        <button
          key={m.value}
          type="button"
          role="menuitem"
          className={`model-picker-item ${current === m.value ? "active" : ""}`}
          onClick={() => {
            onSelect(m.value);
            onClose();
          }}
        >
          <span className="model-picker-label">{m.label}</span>
          <span className="model-picker-desc">{m.desc}</span>
        </button>
      ))}
    </div>
  );
};
