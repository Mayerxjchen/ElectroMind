/** 统一状态优先级 —— P2（spec 2026-08-07 §P2）。
 *
 * 单一状态推导：disconnected > waiting_approval > running > idle。
 * 所有"当前是什么状态"的判断都从这里来，避免各处各算一套。
 * 等待审批时只放行 /status /logs /stop /allow /deny。
 *
 * 纯模块（无 DOM / React 依赖）—— node --test 可直接 bundle 测。
 */

import type { CommandContext } from "./command-registry.ts";

export type CompositeState =
  | "disconnected"
  | "waiting_approval"
  | "running"
  | "idle";

const PRIORITY: Record<CompositeState, number> = {
  disconnected: 4,
  waiting_approval: 3,
  running: 2,
  idle: 1,
};

/** 状态优先级数值（越大越优先；用于多信号冲突时仲裁）。 */
export function statePriority(s: CompositeState): number {
  return PRIORITY[s];
}

/** 从信号推导唯一复合状态（按优先级，不按出现顺序）。 */
export function computeCompositeState(input: {
  bridgeActive: boolean;
  running: boolean;
  pendingApproval: boolean;
}): CompositeState {
  if (!input.bridgeActive) return "disconnected";
  if (input.pendingApproval) return "waiting_approval";
  if (input.running) return "running";
  return "idle";
}

/** 从命令上下文推导复合状态（对最小 store 存根鲁棒，测试可传子集）。
 *  缺 ctx / store / thread 时按 idle 处理（门放行，靠命令自身 available）。
 *  门只在能确知"有待审批"时才收紧 —— 未知状态不臆断为阻塞。 */
export function compositeStateFromCtx(
  ctx: CommandContext,
): CompositeState {
  const store = (ctx as {
    store?: {
      getState?: () => { bridgeActive?: boolean; activityState?: string };
      getActiveThreadId?: () => string | null;
      getThread?: (
        id: string,
      ) => { status?: string; pendingPermits?: unknown[] } | null;
    } | null;
  })?.store;
  const s = store?.getState?.() ?? {};
  const threadId = store?.getActiveThreadId?.() ?? null;
  const t = threadId ? store?.getThread?.(threadId) ?? null : null;
  return computeCompositeState({
    bridgeActive: s.bridgeActive !== false,
    running: s.activityState === "running" || t?.status === "running",
    pendingApproval: (t?.pendingPermits?.length ?? 0) > 0,
  });
}

/** 等待审批时唯一放行的命令集（spec §P2）。 */
export const APPROVAL_OK_COMMANDS: ReadonlySet<string> = new Set([
  "status.show",
  "logs.open",
  "run.stop",
  "run.allow",
  "run.deny",
]);

/** 状态门：waiting_approval 时仅放行审批相关命令；其余状态全放行。 */
export function approvalGate(
  ctx: CommandContext,
): (id: string) => boolean {
  if (compositeStateFromCtx(ctx) !== "waiting_approval") {
    return () => true;
  }
  return (id) => APPROVAL_OK_COMMANDS.has(id);
}
