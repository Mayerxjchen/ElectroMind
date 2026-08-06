/** Slash Menu —— P2/P4（Claude Code 风格）。
 *
 * 输入框以 "/" 开头时显示：COMMON（常规命令）+ SKILLS（可信且可用户
 * 调用的 Skill 动态生成命令，P4）分组；前缀过滤；键盘导航由 Composer
 * 统一处理（↑/↓/Tab/Enter/Esc）；本组件只渲染。
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
  const skills = candidates.filter((c) => c.category === "skills");
  const common = candidates.filter((c) => c.category !== "skills");
  // 展平索引（Composer 的 selected 是展平后的下标）
  const flat = [...common, ...skills];
  const renderItem = (spec: CommandSpec) => {
    const idx = flat.indexOf(spec);
    return (
      <button
        key={spec.id}
        type="button"
        role="menuitem"
        className={`slash-menu-item ${idx === selected ? "active" : ""}`}
        onMouseEnter={() => onMouseEnter(idx)}
        onClick={() => onExecute(spec)}
      >
        <span className="slash-menu-name">/{spec.slash?.[0] ?? spec.id}</span>
        <span className="slash-menu-title">{spec.title}</span>
        {spec.usage ? (
          <span className="slash-menu-usage">{spec.usage}</span>
        ) : null}
      </button>
    );
  };
  return (
    <div className="slash-menu" role="menu" data-slash-menu>
      {common.length > 0 && (
        <div className="slash-menu-group">
          <div className="slash-menu-group-label">COMMON</div>
          {common.map(renderItem)}
        </div>
      )}
      {skills.length > 0 && (
        <div className="slash-menu-group">
          <div className="slash-menu-group-label">SKILLS</div>
          {skills.map(renderItem)}
        </div>
      )}
    </div>
  );
};
