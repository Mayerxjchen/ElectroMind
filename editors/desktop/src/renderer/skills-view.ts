/** 七: Skills Manager —— 纯视图逻辑（无 DOM，node --test 可直接 bundle 测）。
 *
 * 职责：把 Skill 候选行 / 操作按钮 / 操作中状态转换成 HTML 与状态迁移，
 * 全部为纯函数；main.ts 只负责事件绑定与 wire 收发。
 */

export interface SkillViewItem {
  name: string;
  skill_id?: string;
  description?: string;
  source?: string;
  scope?: string;
  sha256?: string;
  status?: string;
  enabled_state?: string;
  trust_state?: string;
}

export type SkillActionKind = "trust" | "revoke" | "update" | "remove";

export const SKILL_ACTION_LABELS: Record<SkillActionKind, string> = {
  trust: "信任",
  revoke: "撤销信任",
  update: "更新",
  remove: "移除",
};

/** 非 builtin 的 Skill 才可管理；trusted 显示撤销，否则显示信任。 */
export function getSkillActions(skill: SkillViewItem): SkillActionKind[] {
  if (skill.scope === "builtin") {
    return [];
  }
  const actions: SkillActionKind[] =
    skill.trust_state === "trusted" ? ["revoke"] : ["trust"];
  actions.push("update", "remove");
  return actions;
}

export interface SkillsPanelState {
  /** 操作中的 Skill 名集合（按钮 disabled + 标签"操作中…"） */
  busy: Set<string>;
  lastError: string | null;
  lastResult: string | null;
}

export function initialSkillsPanelState(): SkillsPanelState {
  return { busy: new Set(), lastError: null, lastResult: null };
}

export type SkillsAction =
  | { type: "begin"; name: string }
  | { type: "end"; name: string; ok: boolean; error?: string; result?: string };

export function reduceSkillsAction(
  state: SkillsPanelState,
  action: SkillsAction,
): SkillsPanelState {
  const busy = new Set(state.busy);
  switch (action.type) {
    case "begin": {
      busy.add(action.name);
      return { ...state, busy, lastError: null };
    }
    case "end": {
      busy.delete(action.name);
      if (!action.ok) {
        return { ...state, busy, lastError: action.error ?? "操作失败" };
      }
      return {
        ...state,
        busy,
        lastResult: action.result ?? null,
      };
    }
  }
}

function esc(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** 操作按钮行（busy 时 disabled 并显示"操作中…"）。 */
export function renderSkillActions(
  skill: SkillViewItem,
  busy: Set<string>,
): string {
  const actions = getSkillActions(skill);
  if (actions.length === 0) {
    return "";
  }
  // installer 的 trust/update/remove 以 name 为键（skill_id 是限定 id，
  // 如 user:electromind:demo-skill，不能直接用于安装器操作）
  const id = esc(skill.name);
  const isBusy = busy.has(skill.name);
  return `
    <div class="skill-actions">
      ${actions
        .map((kind) => {
          const label = isBusy ? "操作中…" : SKILL_ACTION_LABELS[kind];
          const data =
            kind === "trust" || kind === "revoke"
              ? "data-skill-trust"
              : `data-skill-${kind}`;
          // trust/revoke 共用切换语义：按钮携带当前信任态，点击取反
          const extra =
            (kind === "trust" || kind === "revoke") &&
            skill.trust_state === "trusted"
              ? ' data-trusted="1"'
              : "";
          return `<button class="skill-action${kind === "remove" ? " skill-action-danger" : ""}" type="button" ${data}="${id}"${extra} ${isBusy ? "disabled" : ""}>${label}</button>`;
        })
        .join("")}
    </div>`;
}

/** 可用 Skill 行（含来源/scope/信任徽标/操作按钮）。 */
export function renderSkillRows(
  skills: SkillViewItem[],
  busy: Set<string>,
): string {
  return skills
    .map((skill) => {
      const sourceLabel = skill.source
        ? skill.source.split("-").slice(0, 2).join("/")
        : "";
      const trusted = skill.trust_state === "trusted";
      return `
        <div class="skill-item" title="来源: ${esc(skill.source ?? "")}">
          <span class="skill-name">${esc(skill.name)}</span>
          ${sourceLabel ? `<span class="skill-source-tag">${esc(sourceLabel)}</span>` : ""}
          ${skill.scope ? `<span class="skill-scope-tag">${esc(skill.scope)}</span>` : ""}
          ${trusted ? `<span class="skill-badge skill-badge-trust" title="已授予信任">✓ 信任</span>` : ""}
          <span class="skill-desc">${esc(skill.description ?? "")}</span>
          ${renderSkillActions(skill, busy)}
        </div>`;
    })
    .join("");
}
