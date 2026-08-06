/** P3 Auto Model —— ModelSelection ↔ policy 字符串 / 展示标签（纯函数）。
 *
 * policy 字符串是桌面 → agent 的线协议值（input/send 的 model 字段）：
 *   auto / fast / balanced / best / plan-execute / <model-id>
 */

import type { ModelSelection } from "../store/types";

/** ModelSelection → 线协议 policy 字符串。 */
export function modelPolicyString(selection: ModelSelection | null | undefined): string {
  if (!selection) return "auto";
  switch (selection.kind) {
    case "auto":
      return "auto";
    case "profile":
      return selection.profile;
    case "hybrid":
      return selection.profile;
    case "named":
      return selection.modelId;
  }
}

/** policy 字符串 → ModelSelection（解析失败按 named 处理，与后端 parse 一致）。 */
export function modelSelectionFromPolicy(policy: string): ModelSelection {
  const value = policy.trim();
  if (value === "auto") return { kind: "auto" };
  if (value === "fast" || value === "balanced" || value === "best") {
    return { kind: "profile", profile: value };
  }
  if (value === "plan-execute") return { kind: "hybrid", profile: "plan-execute" };
  return { kind: "named", modelId: value };
}

/** 展示标签：Auto / Fast / Balanced / Best / Plan→Execute / named:<id>。 */
export function modelPolicyLabel(selection: ModelSelection | null | undefined): string {
  if (!selection) return "Auto";
  switch (selection.kind) {
    case "auto":
      return "Auto";
    case "profile":
      return selection.profile.charAt(0).toUpperCase() + selection.profile.slice(1);
    case "hybrid":
      return "Plan→Execute";
    case "named":
      return selection.modelId;
  }
}
