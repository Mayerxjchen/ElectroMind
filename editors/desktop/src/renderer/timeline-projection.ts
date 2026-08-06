/** D3.3 TimelineProjection — deterministic Wire/ThreadStore → TimelineItem.
 *
 * Pure fold: ``projectTimeline`` replays a full source stream,
 * ``reduceTimeline`` applies one source event to a projection state.
 * Both run the SAME step function, so full replay and incremental
 * update provably agree — the tests pin this.
 *
 * Rules implemented here (from the D3.3 spec):
 *  - ToolCallBegin / ToolResult / CommandResult / FileChange /
 *    ArtifactProduced fold into an ActivityGroupItem; state changes
 *    UPDATE the existing action / group (never append duplicates).
 *  - The current group ends on: assistant text, user text, approval,
 *    plan proposed, job submitted, run end, run cancelled, tool/command
 *    failure, subagent owner change, thread change.
 *  - A time gap is only a FALLBACK boundary (off by default) — it is
 *    never the primary rule, so history replay stays deterministic.
 *  - IDs never come from Date.now(); they derive from stable source
 *    ids / payload fields, or a deterministic hash as last resort.
 */

import type { ThreadItemKind } from "./store/types";
import type {
  ActivityAction,
  ActivityGroupItem,
  ActivityStatus,
  TimelineItem,
} from "./timeline-types";

// ── Input ─────────────────────────────────────────────────────────────

/** Kinds the projection understands.  ThreadItemKind plus synthesized
 *  boundary sources the store adapter feeds (run lifecycle, jobs,
 *  recovery). */
export type TimelineSourceKind =
  | ThreadItemKind
  | "run_begin"
  | "run_end"
  | "run_cancelled"
  | "job"
  | "recovery"
  | "skill_loaded";

/** One event into the projection.  A snapshot of a ThreadItem (with
 *  the same id re-emitted when the store mutates payload in place) or
 *  a synthesized boundary source. */
export type TimelineSource = {
  id: string;
  kind: TimelineSourceKind;
  threadId: string;
  timestamp: number;
  payload: Record<string, unknown>;
};

export type ProjectionOptions = {
  /** Fallback boundary: close the current group when a tool-ish event
   *  arrives more than this many ms after the previous one.  Default:
   *  disabled — time is never the primary boundary. */
  gapMs?: number;
};

// ── State ─────────────────────────────────────────────────────────────

/** Mutable projection state (internal to this module's reducer). */
export type TimelineProjectionState = {
  threadId: string;
  timeline: TimelineItem[];
  /** Open activity group id, if any. */
  openGroupId: string | null;
  /** Run id the open group belongs to. */
  openRunId?: string;
  /** Owner of the open group ("main" | "subagent:<name>"). */
  openOwner: string;
  /** Timestamp of the last processed source (gap fallback). */
  lastSourceAt: number;
  /** timeline item id → index in `timeline` (stable: no removals). */
  indexById: Map<string, number>;
  /** job id → timeline item id. */
  jobById: Map<string, string>;
  /** plan key (fingerprint|plan_id|version) → timeline item id. */
  planById: Map<string, string>;
  /** artifact key (artifact_id | path) → timeline item id. */
  artifactByKey: Map<string, string>;
  /** All group ids ever created (a run may span several groups —
   *  duplicates get a deterministic :N suffix). */
  createdGroupIds: Set<string>;
};

export function createProjectionState(threadId: string): TimelineProjectionState {
  return {
    threadId,
    timeline: [],
    openGroupId: null,
    openOwner: "main",
    lastSourceAt: 0,
    indexById: new Map(),
    jobById: new Map(),
    planById: new Map(),
    artifactByKey: new Map(),
    createdGroupIds: new Set(),
  };
}

// ── Public API ────────────────────────────────────────────────────────

/** Full replay: fold every source through the same step function used
 *  for incremental updates.  Deterministic for the same input. */
export function projectTimeline(
  sources: readonly TimelineSource[],
  options: ProjectionOptions = {},
  threadId = sources[0]?.threadId ?? "",
): TimelineProjectionState {
  let state = createProjectionState(threadId);
  for (const source of sources) {
    state = reduceTimeline(state, source, options);
  }
  return state;
}

/** Incremental update: apply ONE source event. */
export function reduceTimeline(
  prev: TimelineProjectionState,
  source: TimelineSource,
  options: ProjectionOptions = {},
): TimelineProjectionState {
  // Thread isolation: never mix another thread's events in.
  if (source.threadId !== prev.threadId) {
    return prev;
  }
  const state: TimelineProjectionState = { ...prev };
  const gapBoundary =
    options.gapMs !== undefined &&
    state.lastSourceAt > 0 &&
    source.timestamp - state.lastSourceAt > options.gapMs &&
    state.openGroupId !== null;
  if (gapBoundary) {
    closeGroup(state, "completed", source.timestamp);
  }
  state.lastSourceAt = source.timestamp;

  switch (source.kind) {
    case "user_message":
      closeGroup(state, "completed", source.timestamp);
      upsertMessage(state, source, "user_message");
      break;
    case "assistant_message":
      closeGroup(state, "completed", source.timestamp);
      upsertMessage(state, source, "assistant_message");
      break;
    case "reasoning":
      // Thinking between tool calls is NOT the final text — it must not
      // fragment the current activity group; it renders as the reasoning
      // block via the adapter's `reasoning` marker.
      upsertMessage(state, source, "assistant_message", true);
      break;
    case "tool_call": {
      // Primary path: the store mutates the tool_call item in place, so
      // this same source id arrives again with status done/error.
      ensureGroup(state, source);
      const action = upsertAction(state, source, "tool");
      const status = str(source.payload.status ?? "running");
      if (status === "error") {
        action.status = "failed";
      } else if (status === "done") {
        action.status = "completed";
      } else {
        action.status = "running";
      }
      const seconds = num(source.payload.duration_seconds);
      if (seconds > 0) {
        action.durationMs = seconds * 1000;
      }
      if (source.payload.exit_code !== undefined) {
        action.exitCode = num(source.payload.exit_code);
      }
      const content = str(source.payload.content);
      if (status === "error" && content) {
        action.detail = truncate(content, 400);
      }
      if (status === "error") {
        closeGroup(state, "failed", source.timestamp);
      }
      break;
    }
    case "tool_result": {
      // Defensive path for stores that append separate result items —
      // update the SAME action by tool_call_id, never append a card.
      const failed = source.payload.ok === false;
      const action = findActionByToolCall(state, str(source.payload.tool_call_id));
      if (action) {
        updateAction(action, source);
      }
      if (failed) {
        closeGroup(state, "failed", source.timestamp);
      }
      break;
    }
    case "command": {
      ensureGroup(state, source);
      const action = upsertAction(state, source, "command");
      const ok = source.payload.ok !== false;
      updateAction(action, source);
      if (!ok) {
        action.status = "failed";
        closeGroup(state, "failed", source.timestamp);
      }
      break;
    }
    case "file_change": {
      ensureGroup(state, source);
      const action = upsertAction(state, source, "file_change");
      const p = source.payload;
      action.detail = `+${num(p.additions)} −${num(p.deletions)}`;
      action.status = "completed";
      break;
    }
    case "artifact": {
      ensureGroup(state, source);
      upsertAction(state, source, "artifact");
      upsertArtifact(state, source);
      break;
    }
    case "approval":
      closeGroup(state, "completed", source.timestamp);
      upsertApproval(state, source);
      break;
    case "plan":
      closeGroup(state, "completed", source.timestamp);
      upsertPlan(state, source);
      break;
    case "job":
      closeGroup(state, "completed", source.timestamp);
      upsertJob(state, source);
      break;
    case "run_begin":
      // New run: any leftover group closes; following tool events open
      // a fresh group bound to the new run id.
      closeGroup(state, "completed", source.timestamp);
      break;
    case "run_end":
      closeGroup(state, "completed", source.timestamp);
      break;
    case "run_cancelled":
      closeGroup(state, "cancelled", source.timestamp);
      break;
    case "error":
      closeGroup(state, "completed", source.timestamp);
      pushItem(state, {
        id: source.id || `error:${hash(source.threadId, source.timestamp, source.payload.message)}`,
        kind: "error",
        threadId: source.threadId,
        timestamp: source.timestamp,
        message: str(source.payload.message ?? "未知错误"),
      });
      break;
    case "recovery":
      pushItem(state, {
        id: source.id || `recovery:${hash(source.threadId, source.timestamp, source.payload.message)}`,
        kind: "recovery",
        threadId: source.threadId,
        timestamp: source.timestamp,
        message: str(source.payload.message ?? "连接已恢复"),
      });
      break;
    case "skill_loaded": {
      // P4: /skill 调用记录 —— 同名 Skill upsert（激活/失败更新同一行）。
      const name = str(source.payload.name ?? "skill");
      const id = `skill:${name}`;
      const existingIdx = state.indexById.get(id);
      const patch = {
        id,
        kind: "skill_loaded" as const,
        threadId: source.threadId,
        timestamp: source.timestamp,
        name,
        source: optStr(source.payload.source),
        digest: optStr(source.payload.digest),
        ok: source.payload.ok !== false,
      };
      if (existingIdx !== undefined) {
        const item = state.timeline[existingIdx];
        if (item && item.kind === "skill_loaded") {
          mergePatch(item, patch);
          return state;
        }
      }
      pushItem(state, patch);
      break;
    }
    default:
      // Unknown / future kinds are ignored safely (tests pin this).
      break;
  }
  return state;
}

/** Convenience: map ThreadItems (final snapshots) to sources and replay. */
export function projectThreadItems(
  items: readonly {
    id: string;
    kind: ThreadItemKind;
    threadId: string;
    timestamp: number;
    payload: Record<string, unknown>;
  }[],
  options: ProjectionOptions = {},
): TimelineProjectionState {
  return projectTimeline(
    items.map((it) => ({
      id: it.id,
      kind: it.kind as TimelineSourceKind,
      threadId: it.threadId,
      timestamp: it.timestamp,
      payload: it.payload,
    })),
    options,
  );
}

/** Read-only view helper. */
export function timelineOf(state: TimelineProjectionState): readonly TimelineItem[] {
  return state.timeline;
}

// ── Grouping ──────────────────────────────────────────────────────────

function ensureGroup(
  state: TimelineProjectionState,
  source: TimelineSource,
): ActivityGroupItem {
  const owner = str(source.payload.owner ?? "main");
  const runId = source.payload.run_id !== undefined ? str(source.payload.run_id) : undefined;
  if (state.openGroupId !== null && state.openOwner !== owner) {
    closeGroup(state, "completed", source.timestamp);
  }
  if (state.openGroupId !== null && runId !== undefined && state.openRunId !== runId) {
    closeGroup(state, "completed", source.timestamp);
  }
  if (state.openGroupId !== null) {
    const group = findOpenGroup(state);
    if (group) return group;
  }
  // Deterministic group id: run id, else the first action's tool call
  // id, else the first source item id — never Date.now().  A run can
  // span several groups (text between tool bursts), so a repeat of the
  // base id gets a deterministic :N suffix.
  const toolCallId = str(source.payload.tool_call_id);
  const baseId = runId
    ? `group:${runId}`
    : toolCallId
      ? `group:${toolCallId}`
      : `group:${source.id || hash(source.threadId, source.timestamp, source.kind)}`;
  let groupId = baseId;
  let suffix = 2;
  while (state.createdGroupIds.has(groupId)) {
    groupId = `${baseId}:${suffix++}`;
  }
  state.createdGroupIds.add(groupId);
  const group: ActivityGroupItem = {
    id: groupId,
    kind: "activity_group",
    threadId: source.threadId,
    runId,
    owner,
    status: "running",
    startedAt: source.timestamp,
    actions: [],
  };
  pushItem(state, group);
  state.openGroupId = groupId;
  state.openRunId = runId;
  state.openOwner = owner;
  return group;
}

function closeGroup(
  state: TimelineProjectionState,
  status: ActivityStatus,
  at: number,
): void {
  if (state.openGroupId === null) return;
  const group = findOpenGroup(state);
  if (group) {
    // Terminal statuses win; a running group closes once.
    if (group.status === "running") {
      group.status = status;
      group.endedAt = at;
    }
  }
  state.openGroupId = null;
  state.openRunId = undefined;
}

function findOpenGroup(state: TimelineProjectionState): ActivityGroupItem | null {
  if (state.openGroupId === null) return null;
  const idx = state.indexById.get(state.openGroupId);
  if (idx === undefined) return null;
  const item = state.timeline[idx];
  return item?.kind === "activity_group" ? item : null;
}

// ── Actions ───────────────────────────────────────────────────────────

function upsertAction(
  state: TimelineProjectionState,
  source: TimelineSource,
  kind: ActivityAction["kind"],
): ActivityAction {
  const group = ensureGroup(state, source);
  const toolCallId = str(source.payload.tool_call_id);
  const actionId =
    toolCallId !== ""
      ? `action:${toolCallId}`
      : `action:${source.id || hash(source.threadId, source.timestamp, kind)}`;
  let action = group.actions.find((a) => a.id === actionId);
  if (!action) {
    action = {
      id: actionId,
      toolCallId: toolCallId || undefined,
      kind,
      title: actionTitle(source, kind),
      status: "running",
    };
    group.actions.push(action);
  }
  return action;
}

/** Find an action created from an item whose payload later mutated
 *  (same tool_call_id) — e.g. separate tool_result events. */
function findActionByToolCall(
  state: TimelineProjectionState,
  toolCallId: string,
): ActivityAction | null {
  if (!toolCallId) return null;
  for (const item of state.timeline) {
    if (item.kind !== "activity_group") continue;
    const action = item.actions.find((a) => a.toolCallId === toolCallId);
    if (action) return action;
  }
  return null;
}

/** Apply status/duration/exit/detail from a result-ish source to an
 *  action (updates in place — never a new card). */
function updateAction(action: ActivityAction, source: TimelineSource): void {
  const ok = source.payload.ok !== false && source.payload.status !== "error";
  action.status = ok ? "completed" : "failed";
  const seconds = num(source.payload.duration_seconds);
  if (seconds > 0) {
    action.durationMs = seconds * 1000;
  }
  const exit = num(source.payload.exit_code);
  if (exit !== 0 || source.payload.exit_code !== undefined) {
    action.exitCode = exit;
  }
  const content = str(source.payload.content);
  if (!ok && content) {
    action.detail = truncate(content, 400);
  }
  if (!ok && str(source.payload.stderr)) {
    action.detail = truncate(str(source.payload.stderr), 400);
  }
}

function actionTitle(source: TimelineSource, kind: ActivityAction["kind"]): string {
  switch (kind) {
    case "tool":
      return str(source.payload.name ?? source.payload.tool_name ?? "tool");
    case "command":
      return summarizeCommand(str(source.payload.command ?? "run_command"));
    case "file_change":
      return str(source.payload.path ?? "file change");
    case "artifact":
      return str(source.payload.name ?? source.payload.path ?? "artifact");
  }
}

function summarizeCommand(command: string): string {
  const oneLine = command.replace(/\s+/g, " ").trim();
  return oneLine.length > 80 ? `${oneLine.slice(0, 80)}…` : oneLine;
}

// ── First-class items ─────────────────────────────────────────────────

function upsertMessage(
  state: TimelineProjectionState,
  source: TimelineSource,
  kind: "user_message" | "assistant_message",
  reasoning = false,
): void {
  const existingIdx = state.indexById.get(source.id);
  const text = str(source.payload.text ?? "");
  if (existingIdx !== undefined) {
    const item = state.timeline[existingIdx];
    if (item && item.kind === kind) {
      // In-place payload mutation — creation time stays stable so full
      // replay of the persisted item list converges with the live feed.
      item.text = text;
      return;
    }
  }
  pushItem(state, {
    id: source.id || `${kind}:${hash(source.threadId, source.timestamp, text)}`,
    kind,
    threadId: source.threadId,
    timestamp: source.timestamp,
    text,
    streaming: source.payload.streaming === true,
    reasoning,
  });
}

function upsertApproval(state: TimelineProjectionState, source: TimelineSource): void {
  const toolCallId = str(source.payload.tool_call_id);
  const key = toolCallId || source.id;
  const id = `approval:${key}`;
  const existingIdx = state.indexById.get(id);
  const status = str(source.payload.status ?? "pending");
  const approvalStatus: "pending" | "approved" | "denied" =
    status === "approved" || status === "denied" ? status : "pending";
  const patch = {
    id,
    kind: "approval" as const,
    threadId: source.threadId,
    timestamp: source.timestamp,
    toolCallId: key,
    toolName: str(source.payload.name ?? source.payload.tool_name ?? "tool"),
    status: approvalStatus,
    target: optStr(source.payload.target),
    workdir: optStr(source.payload.workdir),
    risk: optStr(source.payload.risk),
    summary: optStr(source.payload.summary),
  };
  if (existingIdx !== undefined) {
    const item = state.timeline[existingIdx];
    if (item && item.kind === "approval") {
      mergePatch(item, patch);
      return;
    }
  }
  pushItem(state, patch);
}

function upsertPlan(state: TimelineProjectionState, source: TimelineSource): void {
  const planId = str(source.payload.plan_id);
  const fingerprint = str(source.payload.fingerprint);
  const version = num(source.payload.version);
  const key = fingerprint || planId || `v${version}`;
  const id = `plan:${key}`;
  const existingIdx = state.indexById.get(id);
  const steps = Array.isArray(source.payload.steps)
    ? (source.payload.steps as Array<Record<string, unknown>>).map((s) => ({
        id: str(s.id),
        title: str(s.title ?? "步骤"),
        status: str(s.status ?? "pending"),
      }))
    : [];
  const patch = {
    id,
    kind: "plan" as const,
    threadId: source.threadId,
    timestamp: source.timestamp,
    planId,
    version,
    status: str(source.payload.status ?? "proposed"),
    objective: str(source.payload.objective ?? ""),
    steps,
  };
  if (existingIdx !== undefined) {
    const item = state.timeline[existingIdx];
    if (item && item.kind === "plan") {
      mergePatch(item, patch);
      return;
    }
  }
  pushItem(state, patch);
}

function upsertJob(state: TimelineProjectionState, source: TimelineSource): void {
  const jobId = str(source.payload.job_id);
  const key = jobId || source.id;
  const id = `job:${key}`;
  const existingIdx = state.indexById.get(id);
  const patch = {
    id,
    kind: "job" as const,
    threadId: source.threadId,
    timestamp: source.timestamp,
    jobId: key,
    state: str(source.payload.state ?? "PENDING"),
    detail: optStr(source.payload.detail),
    runId: optStr(source.payload.run_id),
  };
  if (existingIdx !== undefined) {
    const item = state.timeline[existingIdx];
    if (item && item.kind === "job") {
      mergePatch(item, patch);
      return;
    }
  }
  pushItem(state, patch);
  state.jobById.set(key, id);
}

function upsertArtifact(state: TimelineProjectionState, source: TimelineSource): void {
  const artifactId = str(source.payload.artifact_id);
  const path = str(source.payload.path);
  // Path-first: ArtifactProduced events carry path but no artifact_id,
  // while later artifact/state events carry both — both must upsert the
  // SAME timeline item.
  const key = path || artifactId;
  const id = `artifact:${key}`;
  const existingIdx = state.indexById.get(id);
  const patch = {
    id,
    kind: "artifact" as const,
    threadId: source.threadId,
    timestamp: source.timestamp,
    artifactId: key,
    path,
    name: optStr(source.payload.name),
    size: source.payload.size !== undefined ? num(source.payload.size) : undefined,
    status: str(source.payload.status ?? source.payload.acceptance_status ?? "created"),
  };
  if (existingIdx !== undefined) {
    const item = state.timeline[existingIdx];
    if (item && item.kind === "artifact") {
      mergePatch(item, patch);
      return;
    }
  }
  pushItem(state, patch);
  state.artifactByKey.set(key, id);
}

// ── Plumbing ──────────────────────────────────────────────────────────

function pushItem(state: TimelineProjectionState, item: TimelineItem): void {
  state.timeline.push(item);
  state.indexById.set(item.id, state.timeline.length - 1);
}

// ── Small helpers (pure, deterministic) ───────────────────────────────

/** Merge only present fields — updates must never clobber existing
 *  values with undefined (e.g. a COMPLETED job event without detail),
 *  and never rewrite the creation timestamp (creation time is stable so
 *  full replay of the persisted item list converges with the live feed). */
function mergePatch(target: Record<string, unknown>, patch: Record<string, unknown>): void {
  for (const [key, value] of Object.entries(patch)) {
    if (value !== undefined && key !== "timestamp") {
      target[key] = value;
    }
  }
}

function str(value: unknown): string {
  return value === undefined || value === null ? "" : String(value);
}

function optStr(value: unknown): string | undefined {
  const s = str(value);
  return s === "" ? undefined : s;
}

function num(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

/** FNV-1a — deterministic hash for fallback IDs. */
export function hash(...parts: unknown[]): string {
  let h = 0x811c9dc5;
  const input = parts.map(str).join(" ");
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(16);
}
