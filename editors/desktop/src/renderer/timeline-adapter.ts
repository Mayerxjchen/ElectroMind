/** D3.3 renderer adapter — projected TimelineItem[] → the item shapes the
 *  existing MessageRenderer already draws.
 *
 *  Visual parity by construction: this mapping renders nothing new and
 *  hides nothing that exists today.  Group actions become the same cards
 *  the raw item stream produced (tool cards with spinner→result upgrade,
 *  file-change rows via the default path, reasoning blocks).  One-level
 *  plan/job/artifact/approval/recovery items are skipped for now — they
 *  have no card in the current renderer, and D3.4 owns their visuals.
 *
 *  Gate: TIMELINE_PROJECTION_V2 (localStorage "desktop.timelineProjection"
 *  = "v1" opts out).  The dual path is a development scaffold — remove it
 *  before release so the renderer reads ONE source of truth.
 */

import type { ThreadItem } from "./store/types";
import type { TimelineItem } from "./timeline-types";

export const TIMELINE_PROJECTION_V2 = true;

/** Feature gate — v2 by default; localStorage "desktop.timelineProjection"
 *  set to "v1" falls back to the raw items path. */
export function timelineProjectionEnabled(): boolean {
  try {
    const v = window.localStorage.getItem("desktop.timelineProjection");
    if (v === "v1" || v === "v2") {
      return v === "v2";
    }
  } catch {
    /* storage unavailable — keep the default */
  }
  return TIMELINE_PROJECTION_V2;
}

/** Map the projected timeline onto the renderer's item stream. */
export function timelineToRenderItems(
  timeline: readonly TimelineItem[],
): ThreadItem[] {
  const out: ThreadItem[] = [];
  for (const item of timeline) {
    switch (item.kind) {
      case "user_message":
        out.push({
          id: item.id,
          kind: "user_message",
          threadId: item.threadId,
          timestamp: item.timestamp,
          payload: { text: item.text },
        });
        break;
      case "assistant_message":
        if (item.reasoning) {
          out.push({
            id: item.id,
            kind: "reasoning",
            threadId: item.threadId,
            timestamp: item.timestamp,
            payload: { text: item.text },
          });
        } else {
          out.push({
            id: item.id,
            kind: "assistant_message",
            threadId: item.threadId,
            timestamp: item.timestamp,
            payload: { text: item.text, streaming: item.streaming },
          });
        }
        break;
      case "activity_group":
        for (const action of item.actions) {
          switch (action.kind) {
            case "tool":
            case "command":
              out.push({
                // action ids are stable → the tool-card upgrade refresh
                // (renderedIds/renderedDoneIds) keeps working.
                id: action.id,
                kind: "tool_call",
                threadId: item.threadId,
                timestamp: item.startedAt,
                payload: {
                  tool_call_id: action.toolCallId ?? action.id,
                  name: action.title,
                  status:
                    action.status === "failed"
                      ? "error"
                      : action.status === "completed"
                        ? "done"
                        : "running",
                  content: action.detail,
                  duration_seconds:
                    action.durationMs !== undefined
                      ? action.durationMs / 1000
                      : undefined,
                  exit_code: action.exitCode,
                },
              });
              break;
            case "file_change":
              out.push({
                id: action.id,
                kind: "file_change",
                threadId: item.threadId,
                timestamp: item.startedAt,
                payload: { path: action.title },
              });
              break;
            case "artifact":
              // No artifact card in the current renderer — keep today's
              // "nothing" (D3.4 renders these).
              break;
          }
        }
        break;
      case "plan":
      case "job":
      case "artifact":
      case "approval":
      case "recovery":
        // No dedicated card in the current renderer (approvals arrive via
        // pendingPermits; plans/artifacts via the Inspector).  Skipping
        // keeps today's visuals exactly.
        break;
      case "error":
        out.push({
          id: item.id,
          kind: "error",
          threadId: item.threadId,
          timestamp: item.timestamp,
          payload: { message: item.message },
        });
        break;
    }
  }
  return out;
}
