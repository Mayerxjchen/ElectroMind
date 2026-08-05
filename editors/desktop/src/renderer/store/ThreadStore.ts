/** Observable Thread-scoped store.
 *
 * Every piece of state that can differ between threads lives inside
 * ``ThreadState`` keyed by thread id.  Global chrome (theme, sidebar)
 * stays at the top level.
 *
 * The store exposes a simple subscription model so existing vanilla-JS
 * code can react to changes without React or Zustand.  When the React
 * shell is introduced (Milestone 2), this class can be wrapped in a
 * Zustand ``create()`` call with zero logic changes.
 *
 * Usage::
 *
 *   const store = getThreadStore();
 *   store.setActiveThread("thread-abc");
 *   store.updateThread("thread-abc", { status: "running" });
 *
 *   const unsub = store.subscribe((state) => {
 *     renderLeftBar(state.sessions);
 *   });
 */

import type {
  AppState,
  ExecutionContextState,
  ExecutionState,
  InspectorState,
  PermitRequest,
  RunState,
  SandboxStatus,
  SidebarState,
  SkillsState,
  ThreadId,
  ThreadItem,
  ThreadState,
  ThreadSummary,
} from "./types.ts";
import { createInitialInspectorState } from "../inspector-model.ts";

// ---------------------------------------------------------------------------
// Subscriber type
// ---------------------------------------------------------------------------

type Listener = (state: AppState) => void;

// ---------------------------------------------------------------------------
// Initial sidebar defaults
// ---------------------------------------------------------------------------

function initialSidebar(): SidebarState {
  return {
    docked: false,
    pinned: readStored("sidebarPinned", false),
    leftCollapsed: false,
    rightCollapsed: false,
    leftWidth: 280,
    rightWidth: 340,
    activeTab: "project",
    projectPane: "files",
  };
}

function readStored(key: string, fallback: boolean): boolean {
  try {
    const v = window.localStorage.getItem(`electromind-desktop-${key}`);
    return v !== null ? v === "1" : fallback;
  } catch {
    return fallback;
  }
}

function readStoredTheme(): "light" | "dark" {
  try {
    const v = window.localStorage.getItem("electromind-desktop-theme");
    if (v === "light" || v === "dark") return v;
  } catch {
    /* ignore */
  }
  return "dark";
}

// ---------------------------------------------------------------------------
// Factory for a fresh ThreadState
// ---------------------------------------------------------------------------

export function createThreadState(
  id: ThreadId,
  title: string,
): ThreadStateInternal {
  return {
    id,
    title,
    sessionMode: "agent",
    autonomy: "prompt",
    model: { kind: "auto" },
    executionTarget: null,
    status: "idle",
    items: [],
    activeRun: null,
    pendingPermits: [],
    sandboxStatus: null,
    skillsState: null,
    executionContextState: null,
    executionState: null,
    plan: null,
    artifacts: [],
    scrollTop: 0,
    userScrolledUp: false,
    // Protocol v2 fields
    lastEventSeq: -1,
    seenEventIds: new Set(),
    toolCallIndex: {},
    openItems: {},
  };
}

// ---------------------------------------------------------------------------
// Clean ThreadState type: seenEventIds is a Set, not JSON-serializable.
// We extend the public type here so the store internals can use it.
// ---------------------------------------------------------------------------

interface ThreadStateInternal extends ThreadState {
  /** Monotonically increasing event seq from the wire (for recovery). */
  lastEventSeq: number;
  /** Event IDs already rendered (for client-side dedup). */
  seenEventIds: Set<string>;
  /** tool_call_id → ThreadItem id (for ToolResult pairing). */
  toolCallIndex: Record<string, string>;
  /** Open streaming items for TextDelta/ReasoningDelta accumulation,
   *  keyed by ``<run_id>:<kind>``.  Each Run keeps its OWN open item PER
   *  STREAM, so a late delta from an OLD Run accumulates into that old
   *  Run's item, and interleaved text/reasoning deltas of ONE Run keep
   *  two continuous streams instead of splitting them (Gate 1, 二-5). */
  openItems: Record<
    string,
    { kind: "assistant_message" | "reasoning"; itemId: string }
  >;
}

// ---------------------------------------------------------------------------
// The store
// ---------------------------------------------------------------------------

class ThreadStore {
  private state: AppState;
  private listeners: Set<Listener> = new Set();

  constructor() {
    this.state = {
      activeThreadId: null,
      sessions: [],
      threads: {},
      theme: readStoredTheme(),
      sidebar: initialSidebar(),
      inspector: createInitialInspectorState(),
      activityState: "sleeping",
      projectPath: "",
      transport: "wire",
      bridgeActive: false,
      sandboxTree: [],
      projectTreeNodes: [],
      projectLoadedPath: "",
      artifacts: [],
    };
  }

  // ── read ──────────────────────────────────────────────────────────

  getState(): Readonly<AppState> {
    return this.state;
  }

  getActiveThreadId(): ThreadId | null {
    return this.state.activeThreadId;
  }

  getActiveThread(): ThreadState | null {
    const id = this.state.activeThreadId;
    return id ? (this.state.threads[id] ?? null) : null;
  }

  getThread(id: ThreadId): ThreadState | undefined {
    return this.state.threads[id];
  }

  // ── write — app level ─────────────────────────────────────────────

  setActiveThread(id: ThreadId | null): void {
    if (this.state.activeThreadId === id) return;
    this.state.activeThreadId = id;
    this.emit();
  }

  setSessions(sessions: ThreadSummary[]): void {
    this.state.sessions = sessions;
    this.emit();
  }

  setTheme(theme: "light" | "dark"): void {
    this.state.theme = theme;
    try {
      window.localStorage.setItem("electromind-desktop-theme", theme);
    } catch {
      /* ignore */
    }
    this.emit();
  }

  updateSidebar(patch: Partial<SidebarState>): void {
    Object.assign(this.state.sidebar, patch);
    if (patch.pinned !== undefined) {
      try {
        window.localStorage.setItem(
          "electromind-desktop-sidebarPinned",
          patch.pinned ? "1" : "0",
        );
      } catch {
        /* ignore */
      }
    }
    this.emit();
  }

  setActivityState(v: AppState["activityState"]): void {
    this.state.activityState = v;
    this.emit();
  }

  setProjectTreeNodes(nodes: unknown[]): void {
    this.state.projectTreeNodes = nodes;
    this.emit();
  }

  /** D3.2: merge a partial update into the Inspector state.  All
   *  open/pin/tab transitions go through here (single source of truth). */
  setInspector(patch: Partial<InspectorState>): void {
    this.state.inspector = { ...this.state.inspector, ...patch };
    this.emit();
  }

  setProjectPath(p: string): void {
    this.state.projectPath = p;
    this.emit();
  }

  setTransport(t: "wire" | "http"): void {
    this.state.transport = t;
    this.emit();
  }

  setBridgeActive(v: boolean): void {
    this.state.bridgeActive = v;
    this.emit();
  }

  // ── write — thread level ──────────────────────────────────────────

  /** Ensure a thread exists (no-op if already present). */
  ensureThread(id: ThreadId, title = ""): ThreadState {
    let t = this.state.threads[id];
    if (!t) {
      t = createThreadState(id, title);
      this.state.threads[id] = t;
    }
    return t;
  }

  /** Merge a partial update into a thread's state. */
  updateThread(id: ThreadId, patch: Partial<ThreadState>): void {
    const t = this.ensureThread(id);
    Object.assign(t, patch);
    this.emit();
  }

  /** Remove a thread and all its state. */
  removeThread(id: ThreadId): void {
    delete this.state.threads[id];
    if (this.state.activeThreadId === id) {
      this.state.activeThreadId = null;
    }
    this.emit();
  }

  // ── write — thread sub-states (convenience) ───────────────────────

  setThreadSandboxStatus(id: ThreadId, s: SandboxStatus | null): void {
    this.updateThread(id, { sandboxStatus: s });
  }

  setThreadSkillsState(id: ThreadId, s: SkillsState | null): void {
    this.updateThread(id, { skillsState: s });
  }

  setThreadExecutionContextState(
    id: ThreadId,
    s: ExecutionContextState | null,
  ): void {
    this.updateThread(id, { executionContextState: s });
  }

  setThreadExecutionState(id: ThreadId, s: ExecutionState | null): void {
    this.updateThread(id, { executionState: s });
  }

  setThreadActiveRun(id: ThreadId, run: RunState | null): void {
    this.updateThread(id, { activeRun: run });
  }

  appendThreadItem(id: ThreadId, item: ThreadItem): void {
    const t = this.ensureThread(id);
    t.items = [...t.items, item];
    this.emit();
  }

  /** Accumulate a streaming delta into the run's open item (creating one
   *  if needed).  Open items are tracked PER (RUN, STREAM): a late delta
   *  from an OLD Run accumulates into that old Run's own item — it can
   *  never steal the open slot of the CURRENT Run, and interleaved
   *  text/reasoning deltas of ONE Run keep continuous streams (Gate 1,
   *  二-5). */
  private applyDelta(
    threadId: ThreadId,
    runId: string,
    kind: "assistant_message" | "reasoning",
    text: string,
  ): void {
    const t = this.ensureThread(threadId) as ThreadStateInternal;
    const key = `${runId}:${kind}`;
    const open = t.openItems[key];
    if (open) {
      const item = t.items.find((i) => i.id === open.itemId);
      if (item) {
        const prev = String(item.payload.text ?? "");
        item.payload = { ...item.payload, text: prev + text };
        this.emit();
        return;
      }
    }
    const prefix = kind === "reasoning" ? "reas" : "asst";
    const itemId = `${prefix}-${Date.now()}-${t.items.length}`;
    t.openItems[key] = { kind, itemId };
    this.appendThreadItem(threadId, {
      id: itemId,
      kind,
      threadId,
      timestamp: Date.now(),
      payload: { text, streaming: true },
    });
  }

  /** Close every open streaming item owned by *runId* (all kinds). */
  private closeOpenItemsForRun(threadId: ThreadId, runId: string): void {
    const t = this.ensureThread(threadId) as ThreadStateInternal;
    const prefix = `${runId}:`;
    for (const key of Object.keys(t.openItems)) {
      if (key.startsWith(prefix)) delete t.openItems[key];
    }
  }

  // ── Optimistic local input (single source of truth) ─────────────────

  /**
   * Create the optimistic user item BEFORE the wire ACK arrives.  The
   * item id is the stable request_id so retries reuse the same identity.
   */
  addOptimisticInput(threadId: ThreadId, requestId: string, text: string): void {
    const t = this.ensureThread(threadId);
    // Upsert: a retry with the same request_id must not duplicate
    const existing = t.items.find((it) => it.id === requestId);
    if (existing) {
      existing.payload = { text, state: "accepted" };
      this.emit();
      return;
    }
    t.items = [
      ...t.items,
      {
        id: requestId,
        kind: "user_message",
        threadId,
        timestamp: Date.now(),
        payload: { text, state: "accepted" },
      },
    ];
    this.emit();
  }

  /**
   * Reconcile an optimistic input from an input/state ACK.  The real
   * message_id replaces the request_id as the item id; the delivery state
   * is updated (accepted → queued/immediate_pending/applied/deferred/
   * rejected).  Items never silently disappear.
   */
  reconcileInput(
    threadId: ThreadId,
    messageId: string,
    state: string,
    requestId?: string,
  ): void {
    const t = this.ensureThread(threadId);
    const candidates = t.items.filter(
      (it) => it.id === messageId || (requestId && it.id === requestId),
    );
    for (const item of candidates) {
      const payload = { ...(item.payload as Record<string, unknown>), state };
      if (messageId && item.id !== messageId) {
        // Re-key to the real message_id (drop the optimistic entry)
        const idx = t.items.indexOf(item);
        t.items.splice(idx, 1);
        t.items.push({ ...item, id: messageId, payload });
      } else {
        item.payload = payload;
      }
    }
    this.emit();
  }

  /** Record a local error as a thread-scoped item (not a global banner). */
  addErrorItem(threadId: ThreadId, message: string): void {
    this.appendThreadItem(threadId, {
      id: `error-${Date.now()}`,
      kind: "error",
      threadId,
      timestamp: Date.now(),
      payload: { message },
    });
  }

  updateThreadScroll(id: ThreadId, scrollTop: number, userScrolledUp: boolean): void {
    this.updateThread(id, { scrollTop, userScrolledUp });
  }

  // ── scoped event helpers ──────────────────────────────────────────

  /**
   * Apply an incoming wire event to the correct thread.
   *
   * Protocol v2: every event carries ``thread_id``, ``seq``, and
   * ``event_id``.  Events with a ``seq`` <= the thread's ``lastEventSeq``
   * are skipped (duplicate detection).  Events with a duplicate
   * ``event_id`` are also skipped (idempotent replay).
   *
   * Returns true if the event was consumed.
   */
  applyWireEvent(
    method: string,
    params: Record<string, unknown>,
  ): boolean {
    const threadId = String(params.thread_id ?? params.threadId ?? "");
    if (!threadId) return false;

    const t = this.ensureThread(threadId) as ThreadStateInternal;

    // ── Snapshot recovery (bypasses dedup — applySnapshot handles events) ─
    if (method === "thread/snapshot") {
      this.applySnapshot(params);
      return true;
    }

    // ── Protocol v2 dedup ──────────────────────────────────────────
    const eventId = String(params.event_id ?? "");
    const seq = Number(params.seq ?? -1);

    if (eventId && t.seenEventIds.has(eventId)) {
      return true; // Already processed — idempotent
    }
    if (seq >= 0 && seq <= t.lastEventSeq) {
      return true; // Already seen this seq — duplicate
    }
    if (eventId) {
      t.seenEventIds.add(eventId);
    }
    if (seq > t.lastEventSeq) {
      t.lastEventSeq = seq;
    }

    // ── Existing wire events ───────────────────────────────────────

    switch (method) {
      case "SkillsState":
        this.setThreadSkillsState(threadId, params as unknown as SkillsState);
        return true;
      case "ExecutionContextState":
        this.setThreadExecutionContextState(
          threadId,
          params as unknown as ExecutionContextState,
        );
        return true;
      case "ExecutionState":
        this.setThreadExecutionState(
          threadId,
          params as unknown as ExecutionState,
        );
        return true;

      // ── Protocol v2: input/state ──────────────────────────────────
      case "input/state":
        // Update thread status based on input delivery state
        this.updateThread(threadId, {
          status: params.state === "applied" ? "running" : t.status,
        });
        return true;

      // ── Protocol v2: run/* ────────────────────────────────────────
      case "run/started": {
        const runId = String(params.run_id ?? "");
        this.setThreadActiveRun(threadId, {
          runId,
          phase: "running",
          startedAt: Date.now(),
          toolCallsIssued: 0,
          pendingApprovals: [],
        });
        this.updateThread(threadId, { status: "running" });
        return true;
      }
      case "run/completed": {
        this.updateThread(threadId, {
          activeRun: null,
          status: "idle",
        });
        return true;
      }

      // ── Protocol v2: item/* ──────────────────────────────────────
      case "item/started":
      case "item/completed":
      case "item/failed": {
        const itemId = String(params.item_id ?? "");
        const itemKind = String(params.kind ?? "assistant_message");
        if (itemId) {
          this.appendThreadItem(threadId, {
            id: itemId,
            kind: itemKind as ThreadItem["kind"],
            threadId,
            timestamp: Date.now(),
            payload: params.payload as Record<string, unknown> ?? params,
          });
        }
        return true;
      }

      // ── Protocol v2: FileChange (Changes panel) ──────────────────
      case "FileChange": {
        const path = String(params.path ?? "");
        if (path) {
          const fcId = `file-${threadId}-${path}-${params.seq ?? Date.now()}`;
          this.appendThreadItem(threadId, {
            id: fcId,
            kind: "file_change",
            threadId,
            timestamp: Date.now(),
            payload: {
              path,
              status: String(params.status ?? "modified"),
              additions: Number(params.additions ?? 0),
              deletions: Number(params.deletions ?? 0),
              run_id: String(params.run_id ?? ""),
              tool_call_id: String(params.tool_call_id ?? ""),
              // Real diff hunks from the backend (actual old/new text)
              hunks: Array.isArray(params.hunks) ? params.hunks : [],
            },
          });
        }
        return true;
      }

      // ── Protocol v2: approval/* ──────────────────────────────────
      case "approval/requested":
      case "PermitRequest": {
        const toolCallId = String(params.tool_call_id ?? "");
        const aprRunId = String(params.run_id ?? "");
        const aprId = String(params.approval_id ?? "");
        if (toolCallId) {
          const permit: PermitRequest = {
            toolCallId,
            approvalId: aprId || undefined,
            toolName: String(params.name ?? params.tool_name ?? ""),
            arguments: String(params.arguments ?? "{}"),
            threadId,
            runId: aprRunId,
            timestamp: Date.now(),
          };
          const t2 = this.ensureThread(threadId);
          t2.pendingPermits = [...t2.pendingPermits, permit];
          this.emit();
        }
        return true;
      }
      case "approval/resolved": {
        const resolvedToolCallId = String(params.tool_call_id ?? "");
        const t3 = this.ensureThread(threadId);
        t3.pendingPermits = t3.pendingPermits.filter(
          (p) => p.toolCallId !== resolvedToolCallId,
        );
        this.emit();
        return true;
      }

      // ── G1: Plan / Artifact 领域状态 ─────────────────────────────
      case "plan/state": {
        const rawPlan = params.plan as Record<string, unknown> | null | undefined;
        t.plan = rawPlan ? (rawPlan as ThreadState["plan"]) : null;
        this.emit();
        return true;
      }
      case "artifact/state": {
        const rawArtifacts = params.artifacts as Array<Record<string, unknown>> | undefined;
        t.artifacts = Array.isArray(rawArtifacts)
          ? (rawArtifacts as ThreadState["artifacts"])
          : [];
        this.emit();
        return true;
      }

      // ── Protocol v2: thread/snapshot ──────────────────────────────
      case "thread/snapshot":
        this.applySnapshot(params);
        return true;

      // ── ACP event stream (real wire output) ───────────────────────
      case "RunBegin": {
        const runId = String(params.run_id ?? "");
        this.setThreadActiveRun(threadId, {
          runId,
          phase: "running",
          startedAt: Date.now(),
          toolCallsIssued: 0,
          pendingApprovals: [],
        });
        this.updateThread(threadId, { status: "running" });
        return true;
      }
      case "TextDelta": {
        const text = String(params.text ?? "");
        const runId = String(params.run_id ?? t.activeRun?.runId ?? "");
        this.applyDelta(threadId, runId, "assistant_message", text);
        return true;
      }
      case "ReasoningDelta": {
        const text = String(params.text ?? "");
        const runId = String(params.run_id ?? t.activeRun?.runId ?? "");
        this.applyDelta(threadId, runId, "reasoning", text);
        return true;
      }
      case "ToolCallBegin": {
        const toolCallId = String(params.tool_call_id ?? "");
        const itemId = `tool-${toolCallId}`;
        t.toolCallIndex[toolCallId] = itemId;
        this.appendThreadItem(threadId, {
          id: itemId,
          kind: "tool_call",
          threadId,
          timestamp: Date.now(),
          payload: {
            tool_call_id: toolCallId,
            name: String(params.name ?? ""),
            arguments: String(params.arguments ?? ""),
            status: "running",
          },
        });
        return true;
      }
      case "ToolResult": {
        const toolCallId = String(params.tool_call_id ?? "");
        const itemId = t.toolCallIndex[toolCallId] ?? "";
        const item = itemId ? t.items.find((i) => i.id === itemId) : undefined;
        if (item) {
          item.payload = {
            ...item.payload,
            status: params.ok === false ? "error" : "done",
            content: String(params.content ?? ""),
            exit_code: Number(params.exit_code ?? 0),
            duration_seconds: Number(params.duration_seconds ?? 0),
          };
          delete t.toolCallIndex[toolCallId];
          this.emit();
        }
        return true;
      }
      case "RunEnd": {
        const runId = String(params.run_id ?? "");
        if (runId) {
          // Close only THIS run's open items; a late RunEnd from an OLD
          // run must not clear the CURRENT run's stream or active marker.
          this.closeOpenItemsForRun(threadId, runId);
          if (!t.activeRun || t.activeRun.runId === runId) {
            this.updateThread(threadId, {
              activeRun: null,
              status: "idle",
            });
          }
        } else {
          // Legacy RunEnd without run_id — clear everything
          t.openItems = {};
          this.updateThread(threadId, {
            activeRun: null,
            status: "idle",
          });
        }
        this.emit();
        return true;
      }
      case "Error": {
        const message = String(params.message ?? params.error ?? "未知错误");
        this.appendThreadItem(threadId, {
          id: `err-${Date.now()}-${t.items.length}`,
          kind: "error",
          threadId,
          timestamp: Date.now(),
          payload: { message },
        });
        return true;
      }

      // ── HistoryReplay: rebuild the thread timeline from history ──
      case "HistoryReplay": {
        const messages = params.messages as Array<Record<string, unknown>> | undefined;
        if (Array.isArray(messages)) {
          t.items = messages.map((m, i) =>
            this.historyToItem(threadId, m, i),
          );
          t.toolCallIndex = {};
          t.openItems = {};
        }
        this.emit();
        return true;
      }

      default:
        return false;
    }
  }

  /** Map a HistoryReplay message record to a ThreadItem. */
  private historyToItem(
    threadId: ThreadId,
    m: Record<string, unknown>,
    index: number,
  ): ThreadItem {
    const kind = String(m.kind ?? "");
    const role = String(m.role ?? "");
    const base = {
      threadId,
      timestamp: Date.now(),
    };
    switch (kind) {
      case "text":
        return {
          ...base,
          id: `hist-${index}`,
          kind: role === "user" ? "user_message" : "assistant_message",
          payload: { text: String(m.text ?? "") },
        };
      case "thinking":
        return {
          ...base,
          id: `hist-${index}`,
          kind: "reasoning",
          payload: { text: String(m.text ?? "") },
        };
      case "tool_call":
        return {
          ...base,
          id: `hist-${index}`,
          kind: "tool_call",
          payload: {
            tool_call_id: String(m.tool_call_id ?? ""),
            name: String(m.name ?? ""),
            arguments: String(m.arguments ?? ""),
            status: "done",
          },
        };
      case "tool_result":
        return {
          ...base,
          id: `hist-${index}`,
          kind: "tool_result",
          payload: {
            tool_call_id: String(m.tool_call_id ?? ""),
            content: String(m.content ?? ""),
            status: "done",
          },
        };
      default:
        return {
          ...base,
          id: `hist-${index}`,
          kind: "assistant_message",
          payload: { text: String(m.text ?? "") },
        };
    }
  }

  // ── Snapshot recovery ──────────────────────────────────────────────

  /**
   * Recover thread state from a ``thread/snapshot`` response.
   * Called after client reconnection or page refresh.
   *
   * Events are applied BEFORE the cursor is advanced so they are not
   * skipped by the dedup logic.
   */
  applySnapshot(params: Record<string, unknown>): void {
    const threadId = String(params.thread_id ?? "");
    if (!threadId) return;

    const t = this.ensureThread(threadId) as ThreadStateInternal;

    // 1. Apply batched events FIRST (with old cursor still in place).
    //    Backend sends {method, payload, thread_id, seq, event_id, run_id}.
    const events = params.events as Array<Record<string, unknown>> | undefined;
    if (Array.isArray(events)) {
      for (const evt of events) {
        const evtMethod = String(evt.method ?? "");
        const evtParams = (evt.payload ?? evt.params ?? evt) as Record<string, unknown>;
        // Merge thread_id/seq/event_id/run_id into params for dedup
        if (evt.thread_id) (evtParams as any).thread_id = String(evt.thread_id);
        if (evt.seq !== undefined) (evtParams as any).seq = Number(evt.seq);
        if (evt.event_id) (evtParams as any).event_id = String(evt.event_id);
        if (evt.run_id) (evtParams as any).run_id = String(evt.run_id);
        this.applyWireEvent(evtMethod, evtParams);
      }
    }

    // 2. THEN advance the cursor (so events above are not dedup'ed)
    t.lastEventSeq = Number(
      params.last_seq ?? params.event_seq ?? t.lastEventSeq,
    );

    if (params.active_run_id) {
      t.activeRun = {
        runId: String(params.active_run_id),
        phase: String(params.active_run_phase ?? "running") as RunState["phase"],
        startedAt: Date.now(),
        toolCallsIssued: 0,
        pendingApprovals: [],
      };
    } else {
      t.activeRun = null; // Snapshot says no active run — clear stale state
    }

    // Restore pending approvals from snapshot (with approval_id)
    const approvals = params.pending_approvals as Array<Record<string, unknown>> | undefined;
    if (Array.isArray(approvals)) {
      t.pendingPermits = approvals.map((a) => ({
        toolCallId: String(a.tool_call_id ?? ""),
        approvalId: String(a.approval_id ?? a.tool_call_id ?? ""),
        toolName: String(a.summary ?? a.tool_name ?? ""),
        arguments: "{}",
        threadId,
        runId: String(a.run_id ?? params.active_run_id ?? ""),
        timestamp: Date.now(),
      }));
    }

    // G1: 恢复 Plan / Artifact 领域状态（重启后 Thread/Run/Plan/Approval/
    // Artifact 五态完整恢复；快照里 plan=null 表示无计划，不覆盖旧值）
    if (params.plan) {
      t.plan = params.plan as ThreadState["plan"];
    }
    const snapArtifacts = params.artifacts as Array<Record<string, unknown>> | undefined;
    if (Array.isArray(snapArtifacts)) {
      t.artifacts = snapArtifacts as ThreadState["artifacts"];
    }

    // Durable timeline: rebuild items from the snapshot's history list
    // FIRST, then append queued-input placeholders so they survive.
    const items = params.items as Array<Record<string, unknown>> | undefined;
    if (Array.isArray(items)) {
      t.items = items.map((m, i) => this.historyToItem(threadId, m, i));
      t.toolCallIndex = {};
      t.openItems = {};
    }

    // Restore queued inputs — atomically sync snapshot-owned items.
    const queued = params.queued_inputs as Array<Record<string, unknown>> | undefined;
    if (Array.isArray(queued)) {
      t.items = t.items.filter(
        (it) => !(it.payload && (it.payload as any).state === "queued"),
      );
      for (const q of queued) {
        const mid = String(q.message_id ?? "");
        if (!mid) continue;
        t.items.push({
          id: mid,
          kind: "user_message" as ThreadItem["kind"],
          threadId,
          timestamp: Date.now(),
          payload: {
            text: String(q.text ?? ""),
            delivery: String(q.delivery ?? "enqueue"),
            state: "queued",
          },
        });
      }
    }

    t.status =
      String(params.status ?? "") === "running" ? "running" : "idle";

    this.emit();
  }

  /**
   * Get the last known event seq for a thread (for after_seq recovery).
   */
  getLastEventSeq(threadId: ThreadId): number {
    const t = this.state.threads[threadId] as ThreadStateInternal | undefined;
    return t?.lastEventSeq ?? -1;
  }

  // ── reactivity ────────────────────────────────────────────────────

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    // Push initial state immediately
    fn(this.state);
    return () => {
      this.listeners.delete(fn);
    };
  }

  private emit(): void {
    const snap = this.state;
    for (const fn of this.listeners) {
      try {
        fn(snap);
      } catch {
        /* subscriber errors must not break other subscribers */
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Singleton
// ---------------------------------------------------------------------------

let _store: ThreadStore | null = null;

export function getThreadStore(): ThreadStore {
  if (!_store) {
    _store = new ThreadStore();
  }
  return _store;
}

/** Reset the singleton (for tests). */
export function resetThreadStore(): void {
  _store = null;
}
