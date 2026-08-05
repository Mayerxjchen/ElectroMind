/** Core type definitions for the Thread-scoped Agent Workbench store.
 *
 * These types replace the ad-hoc global ``uiState`` with a structured
 * per-thread model.  Every piece of state that can differ between
 * threads lives under ``ThreadState``; only true global chrome
 * (theme, sidebar, project path) stays at the ``AppState`` level.
 */

// ---------------------------------------------------------------------------
// Session / thread identity
// ---------------------------------------------------------------------------

import type { ArtifactManifest, PlanState } from "../../shared/protocol";

export type ThreadId = string;

export type ThreadSummary = {
  id: ThreadId;
  title: string;
  relativeTime: string;
  projectPath: string;
  sandboxBackend: string;
};

export type ThreadMeta = {
  id: ThreadId;
  title: string;
  createdAt: string;
  updatedAt: string;
  messageCount?: number;
  threadPath: string;
  metainfo: Record<string, unknown>;
};

// ---------------------------------------------------------------------------
// Session modes (replaces implicit command_policy + backend guessing)
// ---------------------------------------------------------------------------

export type SessionMode = "ask" | "plan" | "agent" | "review";

export type AutonomyLevel = "prompt" | "auto-safe" | "full-access";

export type ModelSelection =
  | { kind: "auto" }
  | { kind: "named"; modelId: string };

export type ExecutionTarget =
  | { kind: "local" }
  | { kind: "sandbox"; backend: "docker" | "podman" }
  | { kind: "ssh"; host: string; profileId: string };

// ---------------------------------------------------------------------------
// Run state (one per active agent turn)
// ---------------------------------------------------------------------------

export type RunPhase =
  | "idle"
  | "waking_sandbox"
  | "loading_context"
  | "running"
  | "waiting_approval"
  | "completed"
  | "error"
  | "cancelled";

export type RunState = {
  runId: string;
  phase: RunPhase;
  startedAt: number;
  toolCallsIssued: number;
  pendingApprovals: string[];
};

// ---------------------------------------------------------------------------
// Permit / approval state
// ---------------------------------------------------------------------------

export type PermitRequest = {
  toolCallId: string;
  approvalId?: string;
  toolName: string;
  arguments: string;
  threadId: ThreadId;
  runId: string;
  timestamp: number;
};

// ---------------------------------------------------------------------------
// Message / thread items (typed — replaces opaque ChatRenderer items)
// ---------------------------------------------------------------------------

export type ThreadItemKind =
  | "user_message"
  | "assistant_message"
  | "reasoning"
  | "plan"
  | "tool_call"
  | "tool_result"
  | "command"
  | "file_change"
  | "artifact"
  | "approval"
  | "error";

export type ThreadItem = {
  id: string;
  kind: ThreadItemKind;
  threadId: ThreadId;
  timestamp: number;
  payload: Record<string, unknown>;
};

// ---------------------------------------------------------------------------
// Sandbox / execution status (per-thread)
// ---------------------------------------------------------------------------

export type SandboxStatus = {
  threadId: ThreadId;
  backend: string;
  alive: boolean;
  workdir: string;
};

// ---------------------------------------------------------------------------
// Execution context (SSH context documents — per-thread)
// ---------------------------------------------------------------------------

export type ExecutionContextDocument = {
  remote_path: string;
  sha256: string;
  size: number;
  fetched_at: number;
};

export type ExecutionContextState = {
  threadId: ThreadId;
  target: string;
  profileId: string;
  documents: ExecutionContextDocument[];
  diagnostics: SkillDiagnostic[];
};

// ---------------------------------------------------------------------------
// Skills (per-thread)
// ---------------------------------------------------------------------------

export type SkillStateItem = {
  name: string;
  description: string;
  source: string;
  sha256: string;
  status: "available" | "loaded" | "unavailable";
};

export type SkillDiagnostic = {
  code: string;
  message: string;
  path: string;
  severity: "warning" | "error";
};

export type SkillsState = {
  threadId: ThreadId;
  fingerprint: string;
  generation: number;
  digest: string;
  skills: SkillStateItem[];
  loaded: string[];
  loadedThisRun: string[];
  diagnostics: SkillDiagnostic[];
};

// ---------------------------------------------------------------------------
// Execution mode state (per-thread)
// ---------------------------------------------------------------------------

export type ExecutionState = {
  mode: "local" | "sandbox" | "ssh" | null;
  resolvedBackend: "local" | "docker" | "podman" | "ssh" | null;
  isolated: boolean;
  warning: string | null;
  diagnostics: Array<{ code: string; severity: string; message: string }>;
};

// ---------------------------------------------------------------------------
// Per-thread state — the core unit of the store
// ---------------------------------------------------------------------------

export type ThreadState = {
  id: ThreadId;
  title: string;
  sessionMode: SessionMode;
  autonomy: AutonomyLevel;
  model: ModelSelection;
  executionTarget: ExecutionTarget | null;
  status: "idle" | "running" | "error";

  /** Ordered list of typed thread items (messages, tool calls, plans, …). */
  items: ThreadItem[];

  /** Active run, if an agent turn is in-flight. */
  activeRun: RunState | null;

  /** Pending permit requests for this thread. */
  pendingPermits: PermitRequest[];

  /** Sub-states — each one is thread-scoped. */
  sandboxStatus: SandboxStatus | null;
  skillsState: SkillsState | null;
  executionContextState: ExecutionContextState | null;
  executionState: ExecutionState | null;

  /** G1: 当前 Plan（无则 null；plan/state 事件与快照恢复）。 */
  plan: PlanState | null;
  /** G1: Artifact 清单（artifact/state 事件与快照恢复）。 */
  artifacts: ArtifactManifest[];

  /** Scroll position in the message list (preserved across switches). */
  scrollTop: number;
  /** Whether the user has scrolled up (pause auto-scroll). */
  userScrolledUp: boolean;

  /** Protocol v2: last known event seq (for snapshot recovery). */
  lastEventSeq?: number;
  /** Protocol v2: rendered event IDs (for client-side dedup). */
  seenEventIds?: Set<string>;
};

// ---------------------------------------------------------------------------
// Global app state (true cross-thread chrome)
// ---------------------------------------------------------------------------

export type SidebarState = {
  docked: boolean;
  pinned: boolean;
  leftCollapsed: boolean;
  rightCollapsed: boolean;
  leftWidth: number;
  rightWidth: number;
  activeTab: string;
  projectPane: string;
};

/** D3.2: on-demand Inspector — default closed, contextually triggered,
 *  pinnable.  The open/close rules live in inspector-model.ts. */
export type InspectorTab =
  | "plan"
  | "changes"
  | "files"
  | "artifacts"
  | "jobs"
  | "runtime"
  | "logs";

export type InspectorState = {
  open: boolean;
  pinned: boolean;
  activeTab: InspectorTab;
  selectedResourceId?: string;
  triggerId?: string;
};

export type AppState = {
  /** Currently visible thread id. */
  activeThreadId: ThreadId | null;

  /** All known thread summaries (the session list). */
  sessions: ThreadSummary[];

  /** Per-thread state keyed by thread id. */
  threads: Record<ThreadId, ThreadState>;

  /** Global chrome — same across all threads. */
  theme: "light" | "dark";
  sidebar: SidebarState;
  /** D3.2 Inspector open/pin/tab state — single source of truth. */
  inspector: InspectorState;
  activityState: "running" | "sleeping" | "error";
  projectPath: string;
  transport: "wire" | "http";
  bridgeActive: boolean;

  /** Tree data (shared across threads for now). */
  sandboxTree: unknown[];
  projectTreeNodes: unknown[];
  projectLoadedPath: string;
  artifacts: unknown[];
};
