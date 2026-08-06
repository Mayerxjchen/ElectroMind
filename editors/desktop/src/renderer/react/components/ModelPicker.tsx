/** Model Picker —— P3：Auto Model 选择（点 Composer 状态 chip 或 /model 打开）。
 *
 * Auto / Fast / Balanced / Best / Plan→Execute + 可用模型列表。
 * 选择经 onSelect(policy) 写回 Thread 的 ModelSelection；
 * 实际模型由后端 ModelResolver 在 Run 开始时解析并广播（model/resolved）。
 */

import React, { useEffect, useRef } from "react";
import type { ModelSelection } from "../../store/types";

const PROFILES: { policy: string; label: string; desc: string }[] = [
  { policy: "auto", label: "Auto", desc: "按模式自动选择" },
  { policy: "fast", label: "Fast", desc: "Ask 默认 · 轻量" },
  { policy: "balanced", label: "Balanced", desc: "Agent 默认 · 均衡" },
  { policy: "best", label: "Best", desc: "Plan 默认 · 最强" },
  { policy: "plan-execute", label: "Plan → Execute", desc: "规划 best · 执行 balanced" },
];

const NAMED_MODELS = [
  { id: "deepseek-v4-pro", label: "DeepSeek V4 Pro" },
  { id: "deepseek-v4-flash", label: "DeepSeek V4 Flash" },
];

interface Props {
  open: boolean;
  current: ModelSelection | null;
  effectiveModel: string;
  onSelect: (policy: string) => void;
  onClose: () => void;
}

export const ModelPicker: React.FC<Props> = ({
  open,
  current,
  effectiveModel,
  onSelect,
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

  const currentPolicy =
    current?.kind === "profile" || current?.kind === "hybrid"
      ? current.profile
      : current?.kind === "named"
        ? current.modelId
        : "auto";

  return (
    <div className="model-picker" ref={boxRef} role="menu" data-model-picker>
      {effectiveModel && (
        <div className="model-picker-effective">
          实际模型：<strong>{effectiveModel}</strong>
        </div>
      )}
      <div className="model-picker-group-label">档位</div>
      {PROFILES.map((p) => (
        <button
          key={p.policy}
          type="button"
          role="menuitem"
          className={`model-picker-item ${currentPolicy === p.policy ? "active" : ""}`}
          onClick={() => {
            onSelect(p.policy);
            onClose();
          }}
        >
          <span className="model-picker-label">{p.label}</span>
          <span className="model-picker-desc">{p.desc}</span>
        </button>
      ))}
      <div className="model-picker-group-label">模型</div>
      {NAMED_MODELS.map((m) => (
        <button
          key={m.id}
          type="button"
          role="menuitem"
          className={`model-picker-item ${currentPolicy === m.id ? "active" : ""}`}
          onClick={() => {
            onSelect(m.id);
            onClose();
          }}
        >
          <span className="model-picker-label">{m.label}</span>
          <span className="model-picker-desc">{m.id}</span>
        </button>
      ))}
    </div>
  );
};
