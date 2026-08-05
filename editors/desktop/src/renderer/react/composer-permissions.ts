/** D3.4 Composer permission copy — explicit permission text per autonomy
 *  level, plus the one-time Auto risk-note guard.
 *
 *  Spec (docs/superpowers/specs/2026-08-05-desktop-d3-scope-refinement.md
 *  § D3.4): "Permissions: Ask" / "Permissions: Auto for this run" — never
 *  a bare "Auto", never an ambiguous YOLO/lightning icon.  A one-time risk
 *  note is shown when a run gets automatic approval.
 *
 *  Pure module (no React) so it is unit-testable under node --test (which
 *  strips types for .ts but does NOT load .tsx).  The React Composer is a
 *  thin consumer of these helpers.  localStorage access is guarded so the
 *  module is safe in tests and in restricted storage environments.
 */

export type AutonomyLevel = "prompt" | "auto-safe" | "full-access";

/** Explicit permission readout keyed by autonomy level.  The readout is
 *  the WHOLE phrase — it never degrades to a bare level name or an icon. */
export const PERMISSION_TEXT: Record<string, string> = {
  prompt: "Permissions: Ask",
  "auto-safe": "Permissions: Auto for this run",
  "full-access": "Permissions: Full access",
};

/** The explicit permission phrase for a level (unknown → Ask fallback). */
export function permissionText(level: string): string {
  return PERMISSION_TEXT[level] ?? PERMISSION_TEXT["prompt"] as string;
}

/** Levels that grant the run automatic approval — they need the risk note. */
export function autonomyIsRisky(level: string): boolean {
  return level === "auto-safe" || level === "full-access";
}

/** Per-level risk-note copy (only meaningful for risky levels). */
export const RISK_NOTE_TEXT: Record<string, string> = {
  "auto-safe": "Auto-safe 会在本轮运行中自动执行安全操作,不会逐条询问。",
  "full-access": "Full access 会直接执行任意变更,不会逐条询问。",
};

/** Risk-note copy for a level (unknown/Ask → auto-safe fallback). */
export function riskNoteText(level: string): string {
  return RISK_NOTE_TEXT[level] ?? RISK_NOTE_TEXT["auto-safe"] as string;
}

/** localStorage key for the one-time risk-note dismissal. */
export const RISK_NOTE_KEY = "electromind-permission-risk-dismissed";

/** Whether the one-time risk note has already been dismissed. */
export function isRiskDismissed(): boolean {
  try {
    return window.localStorage.getItem(RISK_NOTE_KEY) === "1";
  } catch {
    return false;
  }
}

/** Persist the one-time dismissal (best-effort; never throws). */
export function markRiskDismissed(): void {
  try {
    window.localStorage.setItem(RISK_NOTE_KEY, "1");
  } catch {
    /* storage unavailable — dismissal is session-only */
  }
}
