/** Target · Permission Picker —— P5：点 Composer 的 "Local · Prompt" 状态 chip。
 *
 * 展示执行目标；权限 Prompt / Auto-safe / Full access（Full 经二次确认，
 * 只作用于当前 Thread —— 与 /permissions 走同一确认桥）。
 */

import React, { useEffect, useRef } from "react";
import { requestConfirm } from "../confirm-bridge.ts";

const LEVELS: { value: string; label: string; desc: string; confirm?: boolean }[] = [
  { value: "prompt", label: "Prompt", desc: "每次工具调用都询问" },
  { value: "auto-safe", label: "Auto-safe", desc: "只读自动放行，外部副作用询问" },
  {
    value: "full-access",
    label: "Full access",
    desc: "自动批准（需确认，仅当前 Thread）",
    confirm: true,
  },
];

interface Props {
  open: boolean;
  targetLabel: string;
  autonomy: string;
  onPermission: (level: string) => void;
  onClose: () => void;
}

export const StatusPicker: React.FC<Props> = ({
  open,
  targetLabel,
  autonomy,
  onPermission,
  onClose,
}) => {
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

  const handleSelect = async (level: string) => {
    if (level === "full-access") {
      const ok = await requestConfirm({
        title: "切换到 Full access？",
        message:
          "Full access 会自动批准工具调用（含可能的外部副作用）。此设置只作用于当前 Thread，不改变全局默认。",
        confirmText: "切换到 Full access",
        cancelText: "取消",
      });
      if (!ok) return;
    }
    onPermission(level);
  };

  return (
    <div className="model-picker" ref={boxRef} role="menu" data-status-picker>
      <div className="model-picker-effective">
        执行目标：<strong>{targetLabel}</strong>
      </div>
      <div className="model-picker-group-label">权限</div>
      {LEVELS.map((l) => (
        <button
          key={l.value}
          type="button"
          role="menuitem"
          className={`model-picker-item ${autonomy === l.value ? "active" : ""}`}
          onClick={() => {
            void handleSelect(l.value);
            onClose();
          }}
        >
          <span className="model-picker-label">{l.label}</span>
          <span className="model-picker-desc">{l.desc}</span>
        </button>
      ))}
    </div>
  );
};
