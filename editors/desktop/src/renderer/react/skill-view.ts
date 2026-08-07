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

/** /skill doctor 文本：Skills 状态健康检查（只读，无后端）。
 *  检查项：信任字段完备性（缺失即 fail-closed 按未信任处理）、
 *  名称完整性、重复名称、model-only 明细。 */
export function skillDoctorText(
  skills: readonly SkillStateItem[],
): string {
  if (skills.length === 0) {
    return "Skills 目录为空";
  }
  const trusted = skills.filter((s) => isSkillTrusted(s)).length;
  const lines = [
    `Skills ${skills.length} · Trusted ${trusted} · Untrusted ${skills.length - trusted}`,
  ];
  const missingTrust = skills.filter((s) => s.trust_state === undefined);
  if (missingTrust.length > 0) {
    lines.push(
      `⚠ ${missingTrust.length} 个缺少 trust_state（fail-closed 按未信任）: ` +
        missingTrust.map((s) => s.name).join(", "),
    );
  }
  const emptyName = skills.filter((s) => !s.name);
  if (emptyName.length > 0) {
    lines.push(`⚠ ${emptyName.length} 个 Skill 缺少名称字段`);
  }
  const seen = new Set<string>();
  const dupes = new Set<string>();
  for (const s of skills) {
    if (seen.has(s.name)) dupes.add(s.name);
    seen.add(s.name);
  }
  if (dupes.size > 0) {
    lines.push(`⚠ 重复名称: ${[...dupes].join(", ")}`);
  }
  const modelOnly = skills.filter((s) => (s.invocation ?? "both") === "model");
  if (modelOnly.length > 0) {
    lines.push(
      `ℹ ${modelOnly.length} 个仅模型可调用: ${modelOnly.map((s) => s.name).join(", ")}`,
    );
  }
  return lines.join("\n");
}
