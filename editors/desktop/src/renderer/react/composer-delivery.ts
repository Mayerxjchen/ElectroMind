/** Composer 投递决策 —— 纯函数（无 DOM），P0 审批优先级 + 投递语义。
 *
 * 统一交互优先级（P0 规格）：
 *
 *     disconnected > waiting_approval > running > idle
 *
 * 等待审批时：
 *   - 不显示 steer / 下一任务控件；
 *   - 输入框禁用（新任务不能绕过当前审批，Enter 不得误发）；
 *   - 只有审批卡上的 Allow once / Deny 是主操作。
 */

export type DeliveryMode = "auto" | "immediate" | "enqueue";

export interface ComposerState {
  disconnected: boolean;
  isRunning: boolean;
  awaitingApproval: boolean;
  enqueueNext: boolean;
}

/** 本次发送的投递方式；null 表示不允许发送（断线 / 等待审批）。 */
export function deliveryForState(s: ComposerState): DeliveryMode | null {
  if (s.disconnected) return null;
  if (s.awaitingApproval) return null;
  if (s.enqueueNext) return "enqueue";
  return s.isRunning ? "immediate" : "auto";
}

/** 运行中且不在等待审批时才显示 steer / 下一任务控件。 */
export function showSteerControls(s: Pick<ComposerState, "isRunning" | "awaitingApproval">): boolean {
  return s.isRunning && !s.awaitingApproval;
}

/** 断线或等待审批时输入框禁用。 */
export function composerInputDisabled(s: Pick<ComposerState, "disconnected" | "awaitingApproval">): boolean {
  return s.disconnected || s.awaitingApproval;
}

/** 输入框占位文案（审批优先于运行态）。 */
export function composerPlaceholder(s: {
  awaitingApproval: boolean;
  isRunning: boolean;
  mode: string;
}): string {
  if (s.awaitingApproval) return "等待审批…";
  if (s.isRunning) return "输入 steer 指令…";
  return s.mode === "plan" ? "描述要规划的任务…" : "输入任务…";
}
