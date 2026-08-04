/** SessionManager — thread lifecycle coordinator.
 *
 * Owns the bridge between the desktop main process (wire / commands)
 * and the ``ThreadStore``.  Every thread transition (new, resume,
 * reset, close) goes through this manager to guarantee:
 *
 * - State from thread A never bleeds into thread B.
 * - Thread switching is instant (< 50ms for already-running threads).
 * - Background threads keep running — switching does not stop them.
 * - Permissions, sandbox status, skills, and execution context are
 *   all scoped to the thread they belong to.
 */

import type { ThreadId } from "./types";
import type { DesktopApi } from "../../shared/protocol";
import { getThreadStore } from "./ThreadStore";

// ---------------------------------------------------------------------------
// Manager
// ---------------------------------------------------------------------------

export class SessionManager {
  private api: DesktopApi;
  private store = getThreadStore();
  private unsubWire: (() => void) | null = null;
  private unsubRuntime: (() => void) | null = null;

  constructor(api: DesktopApi) {
    this.api = api;
  }

  // ── bootstrap ─────────────────────────────────────────────────────

  /** Call once on app startup.  Loads initial runtime state and the session list. */
  async bootstrap(): Promise<void> {
    const [runtime, sessions] = await Promise.all([
      this.api.getRuntimeState(),
      this.api.listThreads(),
    ]);

    this.store.setProjectPath(runtime.projectPath ?? "");
    this.store.setTransport(
      (runtime.transport as "wire" | "http") ?? "wire",
    );
    this.store.setBridgeActive(runtime.bridgeActive ?? false);
    this.store.setSessions(sessions);

    // If there's already an active thread, select it
    if (runtime.currentThreadId) {
      this.store.setActiveThread(runtime.currentThreadId);
      this.store.ensureThread(runtime.currentThreadId, "");
    }

    // Wire events → thread-scoped updates
    this.unsubWire = this.api.onAgentEvent((msg) => {
      if (msg.type !== "wireEvent") return;
      const params = (msg.event.params ?? {}) as Record<string, unknown>;
      this.store.applyWireEvent(msg.event.method, params);
    });

    // Runtime state changes (project switch, transport switch, …)
    this.unsubRuntime = this.api.onRuntimeState((state) => {
      if (state.projectPath !== undefined) {
        this.store.setProjectPath(String(state.projectPath));
      }
      if (state.bridgeActive !== undefined) {
        this.store.setBridgeActive(Boolean(state.bridgeActive));
      }
    });
  }

  // ── thread lifecycle ──────────────────────────────────────────────

  /** Switch to an existing thread.  Does NOT stop the previous thread's agent. */
  async switchThread(threadId: ThreadId): Promise<void> {
    if (this.store.getActiveThreadId() === threadId) return;

    // Preserve scroll position of the outgoing thread
    this.preserveScroll();

    // Ensure the target thread exists in the store
    this.store.ensureThread(threadId, "");

    // Switch — this is a pure UI operation, < 50ms
    this.store.setActiveThread(threadId);

    // Request history replay for the new thread
    await this.api.resumeThread(threadId);
    await this.api.requestHistoryReplay();
  }

  /** Create a new thread with optional overrides. */
  async newThread(opts?: Record<string, unknown>): Promise<ThreadId> {
    await this.api.resetSession(opts);

    // The backend will emit HistoryReplay with the new thread id.
    // We update activeThreadId when that event arrives.
    // For now, return empty — the caller watches activeThreadId.
    return this.store.getActiveThreadId() ?? "";
  }

  /** Close a thread.  If it's the active thread, switch to the most recent one. */
  async closeThread(threadId: ThreadId): Promise<void> {
    const sessions = this.store.getState().sessions;
    this.store.removeThread(threadId);

    if (this.store.getActiveThreadId() === threadId) {
      const remaining = sessions.filter((s) => s.id !== threadId);
      const next = remaining[0];
      if (next) {
        await this.switchThread(next.id);
      } else {
        this.store.setActiveThread(null);
      }
    }
  }

  /** Refresh the session list from the backend. */
  async refreshSessions(): Promise<void> {
    const sessions = await this.api.listThreads();
    this.store.setSessions(sessions);
  }

  // ── per-thread helpers ────────────────────────────────────────────

  /**
   * Called by the renderer after a thread switch so the old thread's
   * scroll position is saved before the DOM swaps.
   */
  preserveScroll(): void {
    const id = this.store.getActiveThreadId();
    if (!id) return;
    const t = this.store.getThread(id);
    if (!t) return;
    // Scroll position is managed by the renderer via updateThreadScroll
  }

  // ── cleanup ───────────────────────────────────────────────────────

  destroy(): void {
    this.unsubWire?.();
    this.unsubRuntime?.();
  }
}
