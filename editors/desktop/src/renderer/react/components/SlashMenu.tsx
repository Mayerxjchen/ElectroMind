/** Slash Menu —— P2（Claude Code 风格）。
 *
 * 输入框以 "/" 开头时显示：COMMON 分组（当前可用命令，前缀过滤）。
 * 键盘导航由 Composer 统一处理（↑/↓/Tab/Enter/Esc）；本组件只渲染。
 * SKILLS 分组在 P4（可信 Skill 动态生成命令）加入。
 */

import React from "react";
import type { CommandSpec } from "../command-registry";

interface Props {
  /** 已过滤的候选（分组前）。 */
  candidates: CommandSpec[];
  selected: number;
  onMouseEnter: (index: number) => void;
  onExecute: (spec: CommandSpec) => void;
}

export const SlashMenu: React.FC<Props> = ({
  candidates,
  selected,
  onMouseEnter,
  onExecute,
}) => {
  if (candidates.length === 0) {
    return (
      <div className="slash-menu" role="menu" data-slash-menu>
        <div className="slash-menu-empty">没有匹配的命令</div>
      </div>
    );
  }
  return (
    <div className="slash-menu" role="menu" data-slash-menu>
      <div className="slash-menu-group">
        <div className="slash-menu-group-label">COMMON</div>
        {candidates.map((spec, idx) => (
          <button
            key={spec.id}
            type="button"
            role="menuitem"
            className={`slash-menu-item ${idx === selected ? "active" : ""}`}
            onMouseEnter={() => onMouseEnter(idx)}
            onClick={() => onExecute(spec)}
          >
            <span className="slash-menu-name">
              /{spec.slash?.[0] ?? spec.id}
            </span>
            <span className="slash-menu-title">{spec.title}</span>
            {spec.usage ? (
              <span className="slash-menu-usage">{spec.usage}</span>
            ) : null}
          </button>
        ))}
      </div>
    </div>
  );
};
