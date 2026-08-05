/** D3.4 Composer status helpers — thread-scoped error surfacing near the
 *  input, and connection state for the disconnected handling.
 *
 *  Spec (§ D3.4): "Errors shown near the Composer" — the composer shows the
 *  most recent error item of the active thread, dismissible, so a failed
 *  send/run is visible at the input rather than only in the log.
 *
 *  Pure module (no React) so it is unit-testable under node --test; the
 *  React Composer consumes it.
 */

export type StatusItemLike = {
  kind: string;
  payload?: Record<string, unknown>;
};

/** Most recent error message in the thread's items, or null.  Iterates
 *  from the tail so the latest error wins. */
export function lastErrorFromItems(
  items: readonly StatusItemLike[],
): string | null {
  for (let i = items.length - 1; i >= 0; i--) {
    const it = items[i];
    if (it?.kind === "error") {
      const msg = String(it.payload?.message ?? "");
      if (msg) return msg;
    }
  }
  return null;
}
