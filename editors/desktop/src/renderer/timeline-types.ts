/** D3.3 Timeline domain types — task-level truth.
 *
 * Wire events are transport facts; TimelineItems are the user-facing
 * task facts.  They are intentionally NOT 1:1.  A ToolCallBegin +
 * ToolResult pair collapses into one ActivityAction inside an
 * ActivityGroupItem; jobs, plans and artifacts are first-class items
 * whose state updates mutate ONE timeline item instead of appending
 * cards.
 *
 * All IDs here are stable and replayable — the projection never
 * invents timestamps; IDs derive from source ids / stable payload
 * fields (tool_call_id, run_id, job_id, artifact path, plan
 * fingerprint) or from a deterministic hash.
 */

export type ActivityStatus = "running" | "completed" | "failed" | "cancelled";

export type TimelineItemKind =
  | "user_message"
  | "assistant_message"
  | "activity_group"
  | "approval"
  | "plan"
  | "job"
  | "artifact"
  | "recovery"
  | "error";

export type TimelineItem =
  | UserMessageItem
  | AssistantMessageItem
  | ActivityGroupItem
  | ApprovalItem
  | PlanItem
  | JobItem
  | ArtifactItem
  | RecoveryItem
  | ErrorItem;

/** One discrete action inside an activity group. */
export type ActivityAction = {
  id: string;
  /** Original tool call id when the action came from a tool. */
  toolCallId?: string;
  kind: "tool" | "command" | "file_change" | "artifact";
  title: string;
  status: ActivityStatus;
  /** Failure / result excerpt shown on demand. */
  detail?: string;
  durationMs?: number;
  exitCode?: number;
};

/** Consecutive tool/command/file/artifact events grouped into one
 *  user-readable activity. */
export type ActivityGroupItem = {
  id: string;
  kind: "activity_group";
  threadId: string;
  runId?: string;
  /** "main" or `subagent:<name>` — actions never mix owners in a group. */
  owner: string;
  status: ActivityStatus;
  startedAt: number;
  endedAt?: number;
  actions: ActivityAction[];
};

export type UserMessageItem = {
  id: string;
  kind: "user_message";
  threadId: string;
  timestamp: number;
  text: string;
};

export type AssistantMessageItem = {
  id: string;
  kind: "assistant_message";
  threadId: string;
  timestamp: number;
  text: string;
  /** True while the text is still streaming (deltas keep appending). */
  streaming?: boolean;
  /** True when this is an intermediate "thinking" stream (renders as the
   *  collapsible reasoning block — never part of the final answer). */
  reasoning?: boolean;
};

export type ApprovalItem = {
  id: string;
  kind: "approval";
  threadId: string;
  timestamp: number;
  toolCallId: string;
  toolName: string;
  status: "pending" | "approved" | "denied";
  target?: string;
  workdir?: string;
  risk?: string;
  summary?: string;
};

export type PlanItem = {
  id: string;
  kind: "plan";
  threadId: string;
  timestamp: number;
  planId: string;
  version: number;
  status: string;
  objective: string;
  steps: Array<{ id: string; title: string; status: string }>;
};

export type JobItem = {
  id: string;
  kind: "job";
  threadId: string;
  timestamp: number;
  jobId: string;
  state: string;
  detail?: string;
  runId?: string;
};

export type ArtifactItem = {
  id: string;
  kind: "artifact";
  threadId: string;
  timestamp: number;
  /** artifact_id when present, else the path. */
  artifactId: string;
  path: string;
  name?: string;
  size?: number;
  status: string;
};

export type RecoveryItem = {
  id: string;
  kind: "recovery";
  threadId: string;
  timestamp: number;
  message: string;
};

export type ErrorItem = {
  id: string;
  kind: "error";
  threadId: string;
  timestamp: number;
  message: string;
};
