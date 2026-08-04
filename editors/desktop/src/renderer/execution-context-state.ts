/** Pure state-transition logic for ExecutionContextState wire events.
 *
 *  Extracted from renderer/main.ts so the transition rules can be tested
 *  directly (compiled + imported) rather than regex-matched against source.
 *
 *  This module has zero DOM / Electron dependencies — it only computes
 *  what the new execution context state should be given an incoming event
 *  and the active thread id.
 */

import type { ExecutionContextStatePayload } from "../shared/protocol";

// ---------------------------------------------------------------------------
// ExecutionContextState transition
// ---------------------------------------------------------------------------

export type ExecContextTransition =
  | { kind: "noop" }        // thread_id mismatch — ignore, leave state unchanged
  | { kind: "clear" }       // empty payload — clear to null
  | { kind: "apply"; state: ExecutionContextStatePayload }; // apply this state

/**
 * Given an incoming ExecutionContextState payload and the currently active
 * thread id, return the transition that should be applied to uiState.
 *
 * Rules (must match the behavior previously inlined in the wire handler):
 * 1. Non-empty thread_id that doesn't match the active thread → noop (stale event)
 * 2. No target AND no documents AND no diagnostics → clear
 * 3. Otherwise → apply the new state
 */
export function computeExecutionContextTransition(
  state: ExecutionContextStatePayload,
  currentThreadId: string,
): ExecContextTransition {
  if (state.thread_id && state.thread_id !== currentThreadId) {
    return { kind: "noop" };
  }
  if (!state.target && !state.documents?.length && !state.diagnostics?.length) {
    return { kind: "clear" };
  }
  return { kind: "apply", state };
}

// ---------------------------------------------------------------------------
// HistoryReplay clear predicate
// ---------------------------------------------------------------------------

/**
 * Whether an incoming HistoryReplay should clear the execution context state.
 *
 * Rules:
 * - Empty thread_id (synthetic/fallback replay) → do NOT clear
 * - Non-empty thread_id matching active thread → clear
 * - Non-empty thread_id NOT matching active thread → do NOT clear
 */
export function shouldClearExecutionContextOnReplay(
  replayedThreadId: string,
  currentThreadId: string,
): boolean {
  return replayedThreadId !== "" && replayedThreadId === currentThreadId;
}
