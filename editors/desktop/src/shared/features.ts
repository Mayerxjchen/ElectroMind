/** Desktop v2 Feature Flags（纯逻辑模块，无 electron 依赖，可被 node --test
 *  直接 bundle 测试）。
 *
 * 冻结契约（spec 2026-08-07-desktop-stability-refactor.md §2）：
 *   所有新功能必须有 Feature Flag；旧桌面在所有 Flag=false 时行为完全不变。
 *
 * 语义：
 *   - shell_v2           单一 AppShell 硬化布局（当前已生效，flag 供回退门控）
 *   - compact_composer   精简 Composer（移除模式/模型/权限下拉等）
 *   - slash_skill_v2     /skill 根命令 + Picker（替代旧 Skills 面板）
 *   - auto_model_v2      Auto Model 快照 / 溯源 / /model 扩展
 *   - legacy_skills_panel 旧 Skills 面板（P4: 默认关闭；slash_skill_v2 验收后删除）
 *
 * fail-closed 规则：features 缺失、非对象、字段非 boolean → 一律回落默认值，
 * 绝不把未知 flag 解释为"开启"。默认值 = 当前稳定桌面行为。
 */

export type DesktopFeatureKey =
  | "shell_v2"
  | "compact_composer"
  | "slash_skill_v2"
  | "auto_model_v2"
  | "legacy_skills_panel";

export type DesktopFeatures = Record<DesktopFeatureKey, boolean>;

export const DEFAULT_FEATURES: DesktopFeatures = {
  shell_v2: false,
  compact_composer: false,
  slash_skill_v2: false,
  auto_model_v2: false,
  // P4: 旧 Skills 面板默认关闭（/skill v2 替代）；显式开 flag 可回退
  legacy_skills_panel: false,
};

/** 把 desktop.json 里的 `features` 原样解析为强类型 DesktopFeatures。
 *  任何异常/缺字段都回落默认值（fail-closed），不抛错。 */
export function parseFeatures(raw: unknown): DesktopFeatures {
  const out: DesktopFeatures = { ...DEFAULT_FEATURES };
  if (typeof raw !== "object" || raw === null) {
    return out;
  }
  const obj = raw as Record<string, unknown>;
  for (const key of Object.keys(DEFAULT_FEATURES) as DesktopFeatureKey[]) {
    const value = obj[key];
    if (typeof value === "boolean") {
      out[key] = value;
    }
  }
  return out;
}
