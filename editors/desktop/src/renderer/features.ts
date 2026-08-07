/** 渲染层 Feature Flags 访问器。
 *
 * fail-closed：主进程解析（shared/features.ts）失败或 IPC 不可用时一律回落
 * 默认值（默认 = 当前稳定桌面行为），绝不把未加载的 flag 当作"开启"。
 * 加载结果缓存一次；后续 flag 读取走同步 currentFeature。
 */

import {
  DEFAULT_FEATURES,
  type DesktopFeatures,
} from "../shared/features.ts";

let cached: DesktopFeatures | null = null;

/** 加载并缓存 Feature Flags（幂等；失败回退默认值，不抛错）。 */
export async function loadDesktopFeatures(): Promise<DesktopFeatures> {
  if (cached) {
    return cached;
  }
  try {
    const flags = await window.desktop.getFeatures();
    cached = { ...DEFAULT_FEATURES, ...flags };
  } catch {
    cached = { ...DEFAULT_FEATURES };
  }
  return cached;
}

/** 同步读取单个 flag；未加载时按默认值（= 当前稳定桌面行为）处理。 */
export function currentFeature(key: keyof DesktopFeatures): boolean {
  return cached?.[key] ?? DEFAULT_FEATURES[key];
}

/** 测试专用：注入已加载的 flags（正常路径由 loadDesktopFeatures 填充）。
 *  仅 node --test 下用于驱动 flag 门控分支。 */
export function __seedDesktopFeaturesForTest(
  flags: Partial<DesktopFeatures>,
): void {
  cached = { ...DEFAULT_FEATURES, ...flags };
}
