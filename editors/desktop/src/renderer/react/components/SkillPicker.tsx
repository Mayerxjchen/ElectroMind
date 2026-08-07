/** Skill Picker —— P3：/skill 无参打开，列出已安装 Skill。
 *
 * 每行：名称 + 描述 + Trusted/Untrusted · Built-in/Managed 徽标。
 * 选择后只补全输入 `/skill <name> `（不立即执行，由用户补任务描述后
 * Enter 走 agent 命令）；键盘 ↑/↓/Enter/Esc 导航。
 */

import React, { useEffect, useMemo, useRef, useState } from "react";
import type { SkillStateItem } from "../../store/types";
import { skillPickerRows } from "../skill-view";

interface Props {
  open: boolean;
  skills: readonly SkillStateItem[];
  onPick: (name: string) => void;
  onClose: () => void;
}

export const SkillPicker: React.FC<Props> = ({
  open,
  skills,
  onPick,
  onClose,
}) => {
  const boxRef = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState(0);
  const rows = useMemo(() => skillPickerRows(skills), [skills]);

  useEffect(() => {
    if (!open) return;
    setSelected(0);
    const onDocClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      } else if (e.key === "ArrowDown" && rows.length > 0) {
        e.preventDefault();
        setSelected((s) => Math.min(s + 1, rows.length - 1));
      } else if (e.key === "ArrowUp" && rows.length > 0) {
        e.preventDefault();
        setSelected((s) => Math.max(s - 1, 0));
      } else if (e.key === "Enter" && rows.length > 0) {
        const row = rows[Math.min(selected, rows.length - 1)];
        if (row) onPick(row.name);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, rows, selected, onPick, onClose]);

  if (!open) return null;

  return (
    <div className="skill-picker" ref={boxRef} role="menu" data-skill-picker>
      <div className="skill-picker-group-label">INSTALLED</div>
      {rows.length === 0 && (
        <div className="skill-picker-empty">未安装任何 Skill</div>
      )}
      {rows.map((r, i) => (
        <button
          key={r.name}
          type="button"
          role="menuitem"
          className={`skill-picker-item ${i === selected ? "active" : ""}`}
          onMouseEnter={() => setSelected(i)}
          onClick={() => onPick(r.name)}
        >
          <span className="skill-picker-name">{r.name}</span>
          <span className="skill-picker-desc">{r.description}</span>
          <span className="skill-picker-badge">
            {r.trustLabel} · {r.sourceLabel}
          </span>
        </button>
      ))}
    </div>
  );
};
