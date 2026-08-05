/** Zustand wrapper around the vanilla ThreadStore.
 *
 * This thin adapter lets React components subscribe to fine-grained
 * slices of the store without re-rendering on unrelated changes.
 * The underlying ThreadStore remains the single source of truth —
 * vanilla JS code continues to read/write it directly.
 */

import { create } from "zustand";
import { getThreadStore } from "../store/ThreadStore";
import type {
  AppState,
  ExecutionContextState,
  RunState,
  SandboxStatus,
  SkillsState,
  ThreadId,
  ThreadState,
  ThreadSummary,
} from "../store/types";

// Re-export types for convenience
export type {
  AppState,
  SessionMode,
  ThreadId,
  ThreadState,
  ThreadSummary,
  RunState,
} from "../store/types";

// ── Store binding ────────────────────────────────────────────────────

function snapshot(): AppState {
  return getThreadStore().getState();
}

export const useAppStore = create<AppState>(() => snapshot());

// Keep the Zustand store in sync with the vanilla ThreadStore
getThreadStore().subscribe((state) => {
  useAppStore.setState({ ...state }, true);
});

// ── Selectors ────────────────────────────────────────────────────────

export function useActiveThreadId(): ThreadId | null {
  return useAppStore((s) => s.activeThreadId);
}

export function useSessions(): ThreadSummary[] {
  return useAppStore((s) => s.sessions);
}

export function useActiveThread(): ThreadState | null {
  return useAppStore((s) => {
    const id = s.activeThreadId;
    return id ? (s.threads[id] ?? null) : null;
  });
}

/** Reactive per-thread snapshot — a NEW object every store emit, so
 *  components re-render when the active thread's fields change in place
 *  (ThreadStore mutates the thread object; its stable ref would otherwise
 *  make ``useActiveThread`` skip re-render).  The Composer uses this so
 *  mode/model/autonomy selects, the permission readout and the error
 *  surface update live.  Shallow — nested arrays/maps keep their refs. */
export function useActiveThreadSnapshot(): ThreadState | null {
  return useAppStore((s) => {
    const id = s.activeThreadId;
    const t = id ? (s.threads[id] ?? null) : null;
    return t ? { ...t } : null;
  });
}

export function useThread(id: ThreadId): ThreadState | undefined {
  return useAppStore((s) => s.threads[id]);
}

export function useActivityState(): AppState["activityState"] {
  return useAppStore((s) => s.activityState);
}

/** D3.4: bridge liveness — false ⇒ composer disabled + reconnect entry. */
export function useBridgeActive(): boolean {
  return useAppStore((s) => s.bridgeActive);
}

export function useSandboxStatus(): SandboxStatus | null {
  return useAppStore((s) => {
    const id = s.activeThreadId;
    if (!id) return null;
    return s.threads[id]?.sandboxStatus ?? null;
  });
}

export function useSkillsState(): SkillsState | null {
  return useAppStore((s) => {
    const id = s.activeThreadId;
    if (!id) return null;
    return s.threads[id]?.skillsState ?? null;
  });
}

export function useExecutionContextState(): ExecutionContextState | null {
  return useAppStore((s) => {
    const id = s.activeThreadId;
    if (!id) return null;
    return s.threads[id]?.executionContextState ?? null;
  });
}

export function useActiveRun(): RunState | null {
  return useAppStore((s) => {
    const id = s.activeThreadId;
    if (!id) return null;
    return s.threads[id]?.activeRun ?? null;
  });
}

export function useTheme(): "light" | "dark" {
  return useAppStore((s) => s.theme);
}
