/** /skill 视图纯逻辑（无 DOM，node --test 可直接 bundle 测）。
 *
 * 职责：把 SkillStateItem 数组转成 Picker 行（含 Trusted/Untrusted 与
 * Built-in/Managed/Project 徽标）以及 /skill list、/skill info 文本。
 * 信任判定统一走 isSkillTrusted（fail-closed，spec 2026-08-07 §P3）。
 */

import type { SkillStateItem } from "../store/types.ts";
import { isSkillTrusted } from "../store/types.ts";

export type SkillPickerRow = {
  name: string;
  description: string;
  trustLabel: "Trusted" | "Untrusted";
  sourceLabel: string;
  trusted: boolean;
};

/** scope → 来源标签：builtin → Built-in，project → Project，其余 → Managed。 */
export function sourceLabel(scope?: string): string {
  switch (scope) {
    case "builtin":
      return "Built-in";
    case "project":
      return "Project";
    default:
      return "Managed";
  }
}

/** Picker 行：按名称排序，含信任与来源徽标。 */
export function skillPickerRows(
  skills: readonly SkillStateItem[],
): SkillPickerRow[] {
  return [...skills]
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((s) => ({
      name: s.name,
      description: s.description,
      trustLabel: isSkillTrusted(s) ? "Trusted" : "Untrusted",
      sourceLabel: sourceLabel(s.scope),
      trusted: isSkillTrusted(s),
    }));
}

/** /skill list 文本（每行一个 Skill）。 */
export function skillListText(skills: readonly SkillStateItem[]): string {
  if (skills.length === 0) {
    return "未安装任何 Skill";
  }
  return skills
    .map(
      (s) =>
        `${s.name} · ${isSkillTrusted(s) ? "Trusted" : "Untrusted"} · ${sourceLabel(s.scope)}`,
    )
    .join("\n");
}

/** /skill info <name> 文本（多行）。 */
export function skillInfoText(s: SkillStateItem): string {
  return [
    `名称: ${s.name}`,
    `描述: ${s.description || "-"}`,
    `来源: ${s.source || "-"} (${sourceLabel(s.scope)})`,
    `信任: ${isSkillTrusted(s) ? "Trusted" : "Untrusted"}`,
    `调用: ${s.invocation ?? "both"}`,
    `状态: ${s.status}`,
    `Digest: ${s.sha256}`,
  ].join("\n");
}
