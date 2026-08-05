/** Desktop-native message renderer — replaces the shared VS Code ChatRenderer.
 *
 * Supports typed ThreadItems instead of raw wire events.  Preserves
 * scroll position per thread and renders each item type with
 * appropriate formatting (code blocks, tool cards, diff cards, etc.).
 *
 * Public API mirrors ChatRenderer for drop-in compatibility::
 *
 *   const renderer = new MessageRenderer(container, onPermit);
 *   renderer.addUser("text");
 *   renderer.handleEvent({ method, params });
 *   renderer.showHistorySkeleton();
 *   renderer.showError("message");
 *   renderer.clear();
 */

import { installCopyButtons, installMessageActions, renderToolCard } from "./copy.ts";
import { VirtualList } from "./VirtualList.ts";
import { renderIcon, type DesktopIconName } from "./icons.ts";
import type { ThreadItem } from "./store/types.ts";
import type {
  ActivityAction,
  ActivityGroupItem,
  ApprovalItem,
  ArtifactItem,
  JobItem,
  PlanItem,
  TimelineItem,
} from "./timeline-types.ts";

// ── Types ────────────────────────────────────────────────────────────

export interface WireEventMessage {
  method: string;
  params: Record<string, unknown>;
}

type PermitCallback = (toolCallId: string, approved: boolean) => void;

/** Item kinds that are projection facts only — never rendered directly
 *  (the v1 fallback path skips them; v2 renders via syncTimeline). */
const NON_RENDERED_KINDS = new Set<ThreadItem["kind"]>([
  "run_begin",
  "run_end",
  "run_cancelled",
  "approval",
]);

// ── MessageRenderer ──────────────────────────────────────────────────

export class MessageRenderer {
  private container: HTMLElement;
  private onPermit: PermitCallback;
  private userScrolledUp = false;
  private skeletonVisible = false;
  private toolCards = new Map<string, HTMLElement>();
  private permitPrompts = new Map<string, HTMLElement>();
  private items: ThreadItem[] = [];
  // D3.3/D3.4: projected-timeline path (single source of truth).
  private timeline: TimelineItem[] = [];
  private timelineMode = false;
  private lastSyncKey = "";
  /** User expansion overrides for activity groups (default by status). */
  private groupOverrides = new Map<string, boolean>();
  private virtualList: VirtualList;

  constructor(container: HTMLElement, onPermit: PermitCallback) {
    this.container = container;
    this.onPermit = onPermit;
    this.bindScroll();
    // Virtual scrolling: only viewport-visible items are mounted (Section
    // IX: 5000 RenderItems must scroll and switch without DOM growth).
    this.virtualList = new VirtualList(container, {
      itemCount: 0,
      renderItem: (index, el) => {
        el.innerHTML = "";
        el.appendChild(
          this.timelineMode
            ? this.buildTimelineElement(this.timeline[index])
            : this.buildItemElement(this.items[index]),
        );
      },
      estimateHeight: () => 80,
      overscan: 4,
    });
  }

  // ── ThreadStore-driven rendering ──────────────────────────────────

  private renderedIds = new Set<string>();
  private renderedDoneIds = new Set<string>();

  /**
   * Render a thread's items from ThreadStore.  Incremental: new items are
   * added to the virtual list; tool cards are upgraded (re-render visible
   * window) when their result arrives.  Single rendering path for the
   * active thread.
   */
  syncItems(items: ThreadItem[]): void {
    this.hideSkeleton();
    this.timelineMode = false;
    const prevCount = this.items.length;
    // D3.3.1: lifecycle kinds are projection facts, not renderable items
    // — the v1 path keeps its exact previous visuals.
    this.items = items.filter((it) => !NON_RENDERED_KINDS.has(it.kind));

    // Detect tool-call results that arrived for already-rendered items
    let needRefresh = false;
    for (const item of items) {
      if (item.kind === "tool_call") {
        const status = String(item.payload.status ?? "running");
        if ((status === "done" || status === "error") && this.renderedIds.has(item.id)) {
          if (!this.renderedDoneIds.has(item.id)) {
            this.renderedDoneIds.add(item.id);
            needRefresh = true;
          }
        }
      }
    }

    if (this.items.length !== prevCount || needRefresh) {
      this.virtualList.setCount(this.items.length);
      if (needRefresh) this.virtualList.refresh();
    }
    for (const item of items) {
      this.renderedIds.add(item.id);
    }

    // Follow the tail unless the user scrolled up
    if (!this.userScrolledUp) {
      this.virtualList.scrollToBottom();
    }
  }

  /** Remove rendered state (called on thread switch or clear). */
  resetRendered(): void {
    this.renderedIds.clear();
    this.renderedDoneIds.clear();
    this.toolCards.clear();
    this.permitPrompts.clear();
    this.groupOverrides.clear();
    this.lastSyncKey = "";
  }

  // ── D3.4: projected timeline rendering (v2 path) ──────────────────

  /**
   * Render the PROJECTED task timeline (single source of truth).  Each
   * TimelineItem is drawn by buildTimelineElement; in-place status
   * changes (action completed, job state, approval resolution) trigger
   * a virtual-list refresh via a cheap content fingerprint.
   */
  syncTimeline(timeline: TimelineItem[]): void {
    this.hideSkeleton();
    this.timelineMode = true;
    const prevCount = this.timeline.length;
    this.timeline = timeline;
    const key = this.timelineKey(timeline);
    const changed = key !== this.lastSyncKey;
    this.lastSyncKey = key;
    if (this.timeline.length !== prevCount || changed) {
      this.virtualList.setCount(this.timeline.length);
      if (changed && this.timeline.length === prevCount) {
        this.virtualList.refresh();
      }
    }
    if (!this.userScrolledUp) {
      this.virtualList.scrollToBottom();
    }
  }

  /** Fingerprint of the timeline — detects in-place mutations that need
   *  a re-render even when the item count is unchanged. */
  private timelineKey(timeline: readonly TimelineItem[]): string {
    let key = "";
    for (const item of timeline) {
      key += item.id;
      switch (item.kind) {
        case "activity_group":
          key += `:${item.status}`;
          for (const a of item.actions) {
            key += `:${a.status}${a.durationMs ?? 0}`;
          }
          break;
        case "user_message":
        case "assistant_message":
          key += `:${item.text.length}`;
          break;
        case "approval":
          key += `:${item.status}`;
          break;
        case "job":
          key += `:${item.state}`;
          break;
        case "artifact":
          key += `:${item.status}`;
          break;
        case "plan":
          key += `:${item.status}${item.version}`;
          break;
        default:
          break;
      }
    }
    return key;
  }

  /** Build the DOM block for one projected timeline item. */
  private buildTimelineElement(item: TimelineItem): HTMLElement {
    switch (item.kind) {
      case "user_message": {
        const el = this.createBlock("user-message");
        el.textContent = item.text;
        return el;
      }
      case "assistant_message": {
        if (item.reasoning) {
          const el = this.createBlock("reasoning-block");
          const summary = document.createElement("summary");
          summary.textContent = "思考过程";
          const details = document.createElement("details");
          details.appendChild(summary);
          const body = document.createElement("div");
          body.className = "reasoning-body";
          body.textContent = item.text;
          details.appendChild(body);
          el.appendChild(details);
          return el;
        }
        const el = this.createBlock("assistant-message");
        el.innerHTML = this.markdownToHtml(item.text);
        installCopyButtons(el);
        installMessageActions(el);
        return el;
      }
      case "activity_group":
        return this.buildActivityGroup(item);
      case "approval":
        return this.buildApprovalItem(item);
      case "plan":
        return this.buildPlanItem(item);
      case "job":
        return this.buildJobItem(item);
      case "artifact":
        return this.buildArtifactItem(item);
      case "recovery": {
        const el = this.createBlock("recovery-row");
        el.textContent = item.message;
        return el;
      }
      case "error": {
        const el = this.createBlock("error-banner");
        el.textContent = item.message;
        return el;
      }
    }
  }

  /**
   * Activity group — one Codex-style block per run segment.
   * Expand rules: running → expanded; completed → collapsed;
   * failed / cancelled → expanded (reason visible).
   */
  private buildActivityGroup(group: ActivityGroupItem): HTMLElement {
    const el = this.createBlock("activity-group");
    el.dataset.groupId = group.id;
    const expanded = this.groupOverrides.get(group.id) ?? this.groupDefaultExpanded(group);
    el.classList.toggle("expanded", expanded);

    const header = document.createElement("button");
    header.type = "button";
    header.className = "activity-header";
    header.setAttribute("aria-expanded", String(expanded));

    const icon = document.createElement("span");
    icon.className = `activity-icon activity-icon-${group.status}`;
    icon.setAttribute("aria-hidden", "true");
    icon.innerHTML = renderIcon(this.groupIcon(group.status));

    const summary = document.createElement("span");
    summary.className = "activity-summary";
    summary.textContent = this.activitySummary(group);

    const chevron = document.createElement("span");
    chevron.className = "activity-chevron";
    chevron.setAttribute("aria-hidden", "true");
    chevron.innerHTML = renderIcon("chevron-right");

    header.appendChild(icon);
    header.appendChild(summary);
    header.appendChild(chevron);

    const actions = document.createElement("div");
    actions.className = "activity-actions";
    actions.classList.toggle("collapsed", !expanded);
    for (const action of group.actions) {
      actions.appendChild(this.buildActionRow(action));
    }

    header.addEventListener("click", () => {
      const next = !(this.groupOverrides.get(group.id) ?? this.groupDefaultExpanded(group));
      this.groupOverrides.set(group.id, next);
      el.classList.toggle("expanded", next);
      header.setAttribute("aria-expanded", String(next));
      actions.classList.toggle("collapsed", !next);
    });

    el.appendChild(header);
    el.appendChild(actions);
    return el;
  }

  private groupDefaultExpanded(group: ActivityGroupItem): boolean {
    return group.status !== "completed";
  }

  private groupIcon(status: ActivityGroupItem["status"]): DesktopIconName {
    switch (status) {
      case "running":
        return "loader-circle";
      case "failed":
        return "x";
      case "cancelled":
        return "pause";
      default:
        return "check";
    }
  }

  private activitySummary(group: ActivityGroupItem): string {
    const n = group.actions.length;
    const word = n === 1 ? "action" : "actions";
    const elapsed =
      group.endedAt !== undefined
        ? Math.max(0, Math.round((group.endedAt - group.startedAt) / 1000))
        : 0;
    switch (group.status) {
      case "running":
        return `Working… ${n} ${word}`;
      case "completed":
        return `Worked for ${elapsed}s · ${n} ${word}`;
      case "failed":
        return `Failed after ${elapsed}s · ${n} ${word}`;
      case "cancelled":
        return `Cancelled after ${elapsed}s · ${n} ${word}`;
    }
  }

  private buildActionRow(action: ActivityAction): HTMLElement {
    const row = document.createElement("div");
    row.className = `activity-action activity-action-${action.status}`;
    // D3.2 inspector triggers: clicking a file/artifact action opens the
    // matching Inspector tab.
    if (action.kind === "file_change" || action.kind === "artifact") {
      row.dataset.inspectorTab = action.kind === "file_change" ? "changes" : "artifacts";
      row.dataset.inspectorTrigger = action.id;
      if (action.kind === "artifact") {
        row.dataset.inspectorResource = String(action.title);
      }
    }
    const icon = document.createElement("span");
    icon.className = "activity-action-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.innerHTML = renderIcon(this.actionIcon(action));

    const title = document.createElement("span");
    title.className = "activity-action-title";
    title.textContent = action.title;
    title.title = action.title;

    const meta = document.createElement("span");
    meta.className = "activity-action-meta";
    const metaParts: string[] = [];
    if (action.durationMs !== undefined) {
      metaParts.push(`${(action.durationMs / 1000).toFixed(1)}s`);
    }
    if (action.exitCode !== undefined) {
      metaParts.push(`exit ${action.exitCode}`);
    }
    meta.textContent = metaParts.join(" · ");

    row.appendChild(icon);
    row.appendChild(title);
    if (metaParts.length) row.appendChild(meta);

    // Failed actions auto-expand their detail.
    if (action.status === "failed" && action.detail) {
      const detail = document.createElement("div");
      detail.className = "activity-action-detail";
      detail.textContent = action.detail;
      row.appendChild(detail);
    }
    return row;
  }

  private actionIcon(action: ActivityAction): DesktopIconName {
    switch (action.kind) {
      case "command":
        return "terminal";
      case "file_change":
        return "file";
      case "artifact":
        return "box";
      default:
        return "wrench";
    }
  }

  /**
   * Inline approval — never requires opening the Inspector.
   * Pending: [Deny] [Allow once]; resolved: a quiet status row.
   */
  private buildApprovalItem(item: ApprovalItem): HTMLElement {
    const el = this.createBlock("approval-card");
    if (item.status !== "pending") {
      const icon = document.createElement("span");
      icon.className = "approval-icon";
      icon.setAttribute("aria-hidden", "true");
      icon.innerHTML = renderIcon(item.status === "approved" ? "check" : "x");
      const label = document.createElement("span");
      label.className = "approval-resolved-label";
      label.textContent =
        item.status === "approved"
          ? `已批准：${item.toolName}`
          : `已拒绝：${item.toolName}`;
      el.appendChild(icon);
      el.appendChild(label);
      return el;
    }
    const head = document.createElement("div");
    head.className = "approval-head";
    head.textContent = "Approval required";
    el.appendChild(head);

    const tool = document.createElement("div");
    tool.className = "approval-tool";
    tool.textContent = item.toolName;
    el.appendChild(tool);

    const meta = document.createElement("div");
    meta.className = "approval-meta";
    const metaParts: string[] = [];
    if (item.target) metaParts.push(item.target);
    if (item.workdir) metaParts.push(item.workdir);
    if (item.risk) metaParts.push(`${item.risk} risk`);
    meta.textContent = metaParts.join(" · ");
    if (metaParts.length) el.appendChild(meta);
    if (item.summary) {
      const summary = document.createElement("div");
      summary.className = "approval-summary";
      summary.textContent = item.summary;
      el.appendChild(summary);
    }

    const actions = document.createElement("div");
    actions.className = "approval-actions";
    const deny = document.createElement("button");
    deny.type = "button";
    deny.className = "approval-deny";
    deny.textContent = "Deny";
    const allow = document.createElement("button");
    allow.type = "button";
    allow.className = "approval-allow";
    allow.textContent = "Allow once";
    deny.addEventListener("click", () => this.onPermit(item.toolCallId, false));
    allow.addEventListener("click", () => this.onPermit(item.toolCallId, true));
    actions.appendChild(deny);
    actions.appendChild(allow);
    el.appendChild(actions);
    return el;
  }

  /** Compact plan summary — click opens the Inspector plan tab. */
  private buildPlanItem(item: PlanItem): HTMLElement {
    const el = this.createBlock("plan-card");
    el.dataset.inspectorTab = "plan";
    el.dataset.inspectorTrigger = item.id;
    const done = item.steps.filter((s) => s.status === "completed" || s.status === "done").length;
    const head = document.createElement("div");
    head.className = "plan-card-head";
    const label = document.createElement("span");
    label.className = "plan-card-label";
    label.textContent = `Plan · ${done}/${item.steps.length} completed`;
    const status = document.createElement("span");
    status.className = `plan-card-status status-${this.cssClass(item.status)}`;
    status.textContent = item.status;
    head.appendChild(label);
    head.appendChild(status);
    el.appendChild(head);
    if (item.objective) {
      const objective = document.createElement("div");
      objective.className = "plan-card-objective";
      objective.textContent = item.objective;
      el.appendChild(objective);
    }
    return el;
  }

  /** Compact job row — state updates re-render this SAME item in place. */
  private buildJobItem(item: JobItem): HTMLElement {
    const el = this.createBlock("job-row");
    const icon = document.createElement("span");
    icon.className = "job-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.innerHTML = renderIcon("server");
    const body = document.createElement("span");
    body.className = "job-body";
    const title = document.createElement("span");
    title.className = "job-title";
    title.textContent = `Slurm job ${item.jobId}`;
    const state = document.createElement("span");
    state.className = `job-state status-${this.cssClass(item.state)}`;
    state.textContent = item.state;
    body.appendChild(title);
    body.appendChild(state);
    if (item.detail) {
      const detail = document.createElement("span");
      detail.className = "job-detail";
      detail.textContent = item.detail;
      body.appendChild(detail);
    }
    el.appendChild(icon);
    el.appendChild(body);
    return el;
  }

  /** Compact artifact row — click opens the Inspector artifacts tab. */
  private buildArtifactItem(item: ArtifactItem): HTMLElement {
    const el = this.createBlock("artifact-row");
    el.dataset.inspectorTab = "artifacts";
    el.dataset.inspectorTrigger = item.id;
    el.dataset.inspectorResource = item.path;
    const icon = document.createElement("span");
    icon.className = "artifact-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.innerHTML = renderIcon("box");
    const body = document.createElement("span");
    body.className = "artifact-row-body";
    const name = document.createElement("span");
    name.className = "artifact-row-name";
    name.textContent = item.name ?? item.path.split("/").pop() ?? item.path;
    const meta = document.createElement("span");
    meta.className = "artifact-row-meta";
    const metaParts: string[] = [];
    if (item.status) metaParts.push(String(item.status));
    if (item.size !== undefined) metaParts.push(this.formatBytes(item.size));
    meta.textContent = metaParts.join(" · ");
    body.appendChild(name);
    if (metaParts.length) body.appendChild(meta);
    el.appendChild(icon);
    el.appendChild(body);
    return el;
  }

  private cssClass(value: unknown): string {
    return String(value ?? "")
      .toLowerCase()
      .replace(/[^a-z0-9-]+/g, "-");
  }

  /** Build a detached block element for one ThreadItem (virtual list
   *  renderItem mounts it into the visible window). */
  private buildItemElement(item: ThreadItem): HTMLElement {
    switch (item.kind) {
      case "user_message": {
        const el = this.createBlock("user-message");
        el.textContent = String(item.payload.text ?? "");
        return el;
      }
      case "assistant_message": {
        const el = this.createBlock("assistant-message");
        el.innerHTML = this.markdownToHtml(String(item.payload.text ?? ""));
        installCopyButtons(el);
        installMessageActions(el);
        return el;
      }
      case "reasoning": {
        const el = this.createBlock("reasoning-block");
        const summary = document.createElement("summary");
        summary.textContent = "思考过程";
        const details = document.createElement("details");
        details.appendChild(summary);
        const body = document.createElement("div");
        body.className = "reasoning-body";
        body.textContent = String(item.payload.text ?? "");
        details.appendChild(body);
        el.appendChild(details);
        return el;
      }
      case "tool_call": {
        const id = String(item.payload.tool_call_id ?? "");
        const name = String(item.payload.name ?? "");
        const args = String(item.payload.arguments ?? "");
        const status = String(item.payload.status ?? "running");
        if (status === "done" || status === "error") {
          const card = this.buildToolResultCard(
            name,
            String(item.payload.content ?? ""),
            status === "error",
            Number(item.payload.duration_seconds ?? 0),
            Number(item.payload.exit_code ?? 0),
          );
          return card;
        }
        const el = this.createBlock("tool-call-begin");
        el.dataset.toolCallId = id;
        const header = document.createElement("div");
        header.className = "tool-call-header";
        header.innerHTML = `<span class="tool-call-name">${this.escape(name)}</span><span class="tool-call-spinner">◉</span>`;
        if (args) {
          const pre = document.createElement("pre");
          pre.className = "tool-call-args";
          pre.textContent = args;
          el.appendChild(pre);
        }
        el.appendChild(header);
        this.toolCards.set(id, el);
        return el;
      }
      case "tool_result": {
        return this.buildToolResultCard(
          String(item.payload.name ?? ""),
          String(item.payload.content ?? ""),
          false,
          Number(item.payload.duration_seconds ?? 0),
          Number(item.payload.exit_code ?? 0),
        );
      }
      case "error": {
        const el = this.createBlock("error-banner");
        el.textContent = String(item.payload.message ?? "未知错误");
        return el;
      }
      default: {
        const el = this.createBlock("assistant-message");
        // D3.2: contextual Inspector triggers.  file_change items exist
        // today; plan/artifact items arrive with the D3.3 activity
        // grouping — the attrs are cheap to carry now.
        if (item.kind === "plan" || item.kind === "file_change" || item.kind === "artifact") {
          el.dataset.inspectorTab =
            item.kind === "plan" ? "plan" : item.kind === "file_change" ? "changes" : "artifacts";
          el.dataset.inspectorTrigger = item.id;
          if (item.kind === "artifact") {
            el.dataset.inspectorResource = String(item.payload.path ?? "");
          }
        }
        el.innerHTML = this.markdownToHtml(String(item.payload.text ?? ""));
        installCopyButtons(el);
        return el;
      }
    }
  }

  private buildToolResultCard(
    name: string,
    content: string,
    error: boolean,
    durationMs: number,
    exitCode: number,
  ): HTMLElement {
    return renderToolCard({
      tool: name,
      status: error ? "error" : "ok",
      elapsedMs: durationMs,
      exitCode: exitCode || 0,
      stdout: content.slice(0, 4000),
      fullLogAvailable: content.length > 4000,
    });
  }

  // ── Public API (ChatRenderer-compatible) ──────────────────────────

  addUser(text: string): void {
    this.hideSkeleton();
    // Route through the ACTIVE rendering path (single rendering path).
    if (this.timelineMode) {
      this.syncTimeline([
        ...this.timeline,
        {
          id: `user-${Date.now()}`,
          kind: "user_message",
          threadId: "",
          timestamp: Date.now(),
          text,
        },
      ]);
      return;
    }
    this.syncItems([
      ...this.items,
      {
        id: `user-${Date.now()}`,
        kind: "user_message",
        threadId: "",
        timestamp: Date.now(),
        payload: { text },
      },
    ]);
  }

  showHistorySkeleton(): void {
    this.clear();
    this.skeletonVisible = true;
    const el = document.createElement("div");
    el.className = "history-skeleton";
    el.innerHTML =
      '<div class="skeleton-pulse" style="height:60px;margin:8px 0"></div><div class="skeleton-pulse" style="height:40px;margin:8px 0"></div><div class="skeleton-pulse" style="height:80px;margin:8px 0"></div>';
    this.container.appendChild(el);
  }

  clear(): void {
    this.items = [];
    this.timeline = [];
    this.timelineMode = false;
    this.virtualList.setCount(0);
    this.toolCards.clear();
    this.permitPrompts.clear();
    this.renderedIds.clear();
    this.renderedDoneIds.clear();
    this.groupOverrides.clear();
    this.lastSyncKey = "";
    this.skeletonVisible = false;
  }

  showError(message: string): void {
    this.hideSkeleton();
    // Route through the ACTIVE rendering path (single rendering path).
    if (this.timelineMode) {
      this.syncTimeline([
        ...this.timeline,
        {
          id: `error-${Date.now()}`,
          kind: "error",
          threadId: "",
          timestamp: Date.now(),
          message,
        },
      ]);
      return;
    }
    this.syncItems([
      ...this.items,
      {
        id: `error-${Date.now()}`,
        kind: "error",
        threadId: "",
        timestamp: Date.now(),
        payload: { message },
      },
    ]);
  }

  /** Handle a wire event and render the appropriate block. */
  handleEvent(event: WireEventMessage): void {
    this.hideSkeleton();
    const { method, params } = event;

    switch (method) {
      case "AssistantMessage":
        this.renderAssistant(String(params.content ?? ""));
        break;
      case "ReasoningMessage":
        this.renderReasoning(String(params.content ?? ""));
        break;
      case "ToolCallBegin":
        this.renderToolCallBegin(
          String(params.tool_call_id ?? ""),
          String(params.name ?? ""),
          String(params.arguments ?? ""),
        );
        break;
      case "ToolResult":
        this.renderToolResult(
          String(params.tool_call_id ?? ""),
          String(params.name ?? ""),
          String(params.content ?? ""),
          Boolean(params.ok),
          Number(params.duration_seconds ?? 0),
          Number(params.exit_code ?? 0),
        );
        break;
      case "CommandResult":
        this.renderCommand(
          String(params.command ?? ""),
          String(params.target ?? ""),
          String(params.cwd ?? ""),
          String(params.stdout ?? ""),
          String(params.stderr ?? ""),
          Boolean(params.ok),
          Number(params.duration_seconds ?? 0),
          Number(params.exit_code ?? 0),
        );
        break;
      case "FileChange":
        this.renderFileChange(
          String(params.path ?? ""),
          String(params.status ?? "modified"),
          Number(params.additions ?? 0),
          Number(params.deletions ?? 0),
        );
        break;
      case "PermitRequest":
        this.renderPermitRequest(
          String(params.tool_call_id ?? ""),
          String(params.tool_name ?? params.name ?? ""),
          String(params.arguments ?? "{}"),
          String(params.summary ?? ""),
          String(params.target ?? ""),
          String(params.workdir ?? ""),
          String(params.risk ?? ""),
        );
        break;
      case "PlanProposed":
        this.renderPlanProposed(params);
        break;
      case "PlanStepChanged":
        this.renderPlanStepChanged(
          String(params.step_id ?? ""),
          String(params.status ?? "pending"),
        );
        break;
      case "ArtifactProduced":
        this.renderArtifact(
          String(params.name ?? ""),
          String(params.path ?? ""),
          Number(params.size ?? 0),
        );
        break;
      case "Error":
        this.showError(String(params.message ?? "未知错误"));
        break;
      default:
        // Unknown events are rendered as generic info blocks
        if (method.endsWith("Message")) {
          this.renderAssistant(String(params.content ?? ""));
        }
    }
  }

  // ── Block renderers ────────────────────────────────────────────────

  private renderAssistant(content: string): void {
    const el = this.createBlock("assistant-message");
    el.innerHTML = this.markdownToHtml(content);
    installCopyButtons(el);
    installMessageActions(el);
    this.append(el);
  }

  private renderReasoning(content: string): void {
    const el = this.createBlock("reasoning-block");
    const summary = document.createElement("summary");
    summary.textContent = "思考过程";
    const details = document.createElement("details");
    details.appendChild(summary);
    const body = document.createElement("div");
    body.className = "reasoning-body";
    body.textContent = content;
    details.appendChild(body);
    el.appendChild(details);
    this.append(el);
  }

  private renderToolCallBegin(id: string, name: string, args: string): void {
    const el = this.createBlock("tool-call-begin");
    el.dataset.toolCallId = id;
    const header = document.createElement("div");
    header.className = "tool-call-header";
    header.innerHTML = `<span class="tool-call-name">${this.escape(name)}</span><span class="tool-call-spinner">◉</span>`;
    if (args) {
      const pre = document.createElement("pre");
      pre.className = "tool-call-args";
      pre.textContent = args;
      el.appendChild(pre);
    }
    el.appendChild(header);
    this.toolCards.set(id, el);
    this.append(el);
  }

  private renderToolResult(
    id: string,
    name: string,
    content: string,
    ok: boolean,
    elapsedMs: number,
    exitCode: number,
  ): void {
    // Replace the placeholder with a proper tool card
    const placeholder = this.toolCards.get(id);
    const card = renderToolCard({
      tool: name,
      status: ok ? "ok" : "error",
      elapsedMs,
      exitCode: exitCode || 0,
      stdout: content.slice(0, 4000),
      fullLogAvailable: content.length > 4000,
    });
    if (placeholder) {
      placeholder.replaceWith(card);
      this.toolCards.delete(id);
    } else {
      this.append(card);
    }
  }

  private renderCommand(
    command: string,
    target: string,
    cwd: string,
    stdout: string,
    stderr: string,
    ok: boolean,
    elapsedMs: number,
    exitCode: number,
  ): void {
    const output = stderr
      ? `STDOUT:\n${stdout.slice(0, 2000)}\n\nSTDERR:\n${stderr.slice(0, 2000)}`
      : stdout.slice(0, 4000);
    const card = renderToolCard({
      tool: "run_command",
      target: target || undefined,
      cwd: cwd || undefined,
      command,
      status: ok ? "ok" : "error",
      elapsedMs,
      exitCode: exitCode || 0,
      stdout: output,
      fullLogAvailable: (stdout + stderr).length > 4000,
    });
    this.append(card);
  }

  private renderFileChange(
    path: string,
    status: string,
    additions: number,
    deletions: number,
  ): void {
    const el = this.createBlock("file-change");
    const statusClass =
      status === "added"
        ? "added"
        : status === "deleted"
          ? "deleted"
          : "modified";
    el.innerHTML = `<span class="file-change-status ${statusClass}">${status === "added" ? "A" : status === "deleted" ? "D" : "M"}</span> <span class="file-change-path">${this.escape(path)}</span> <span class="file-change-stats">+${additions} −${deletions}</span>`;
    this.append(el);
  }

  private renderPermitRequest(
    toolCallId: string,
    toolName: string,
    args: string,
    summary: string,
    target: string,
    workdir: string,
    risk: string,
  ): void {
    const el = this.createBlock("permit-request");
    const metaLines: string[] = [];
    if (summary) metaLines.push(`操作: ${this.escape(summary)}`);
    if (target) metaLines.push(`目标: ${this.escape(target)}`);
    if (workdir) metaLines.push(`目录: ${this.escape(workdir)}`);
    if (risk) metaLines.push(`风险: ${this.escape(risk)}`);
    const metaHtml = metaLines.length
      ? `<div class="permit-meta">${metaLines.join("<br>")}</div>`
      : "";
    el.innerHTML = `
      <div class="permit-header">审批请求: ${this.escape(toolName)}</div>
      ${metaHtml}
      <pre class="permit-args">${this.escape(args)}</pre>
      <div class="permit-actions">
        <button class="permit-approve" data-approve="${toolCallId}">批准</button>
        <button class="permit-deny" data-deny="${toolCallId}">拒绝</button>
      </div>`;
    el.querySelector("[data-approve]")?.addEventListener("click", () => {
      this.onPermit(toolCallId, true);
      el.remove();
    });
    el.querySelector("[data-deny]")?.addEventListener("click", () => {
      this.onPermit(toolCallId, false);
      el.remove();
    });
    this.permitPrompts.set(toolCallId, el);
    this.append(el);
  }

  private renderPlanProposed(params: Record<string, unknown>): void {
    const el = this.createBlock("plan-proposed");
    const steps = (params.steps as Array<Record<string, unknown>>) ?? [];
    const risks = (params.risks as string[]) ?? [];
    const stepsHtml = steps
      .map(
        (s, i) =>
          `<li class="plan-step-item"><span class="plan-step-num">${i + 1}.</span> ${this.escape(String(s.title ?? ""))}</li>`,
      )
      .join("");
    const risksHtml = risks.length
      ? `<details class="plan-risks-inline"><summary>风险 (${risks.length})</summary><ul>${risks.map((r) => `<li>${this.escape(r)}</li>`).join("")}</ul></details>`
      : "";

    el.innerHTML = `
      <div class="plan-inline-header">📋 实施计划</div>
      <p class="plan-inline-objective">${this.escape(String(params.objective ?? ""))}</p>
      <ol class="plan-inline-steps">${stepsHtml}</ol>
      ${risksHtml}
      <div class="plan-inline-actions">
        <button class="plan-inline-edit">编辑计划</button>
        <button class="plan-inline-approve">批准并执行</button>
      </div>`;
    this.append(el);
  }

  private renderPlanStepChanged(stepId: string, status: string): void {
    // Update step status icon in an existing plan card
    const step = this.container.querySelector(`[data-step-id="${stepId}"]`);
    if (step) {
      const icons: Record<string, string> = {
        pending: "○",
        running: "◉",
        done: "✓",
        blocked: "⊘",
      };
      const icon = step.querySelector(".plan-step-icon");
      if (icon) icon.textContent = icons[status] ?? "○";
      step.className = `plan-step-item plan-step-${status}`;
    }
  }

  private renderArtifact(name: string, path: string, size: number): void {
    const el = this.createBlock("artifact-card");
    el.innerHTML = `
      <div class="artifact-header">📦 产物</div>
      <div class="artifact-name">${this.escape(name)}</div>
      <div class="artifact-meta">${this.formatBytes(size)} · ${this.escape(path)}</div>
      <div class="artifact-actions">
        <button class="artifact-preview">预览</button>
        <button class="artifact-export">导出</button>
        <button class="artifact-copy-path">复制路径</button>
      </div>`;
    this.append(el);
  }

  // ── Helpers ────────────────────────────────────────────────────────

  private createBlock(className: string): HTMLElement {
    const el = document.createElement("div");
    el.className = `msg-block ${className}`;
    return el;
  }

  private append(el: HTMLElement): void {
    this.container.appendChild(el);
    if (!this.userScrolledUp) {
      requestAnimationFrame(() => {
        this.container.scrollTop = this.container.scrollHeight;
      });
    }
    installCopyButtons(el);
  }

  private hideSkeleton(): void {
    if (!this.skeletonVisible) return;
    this.skeletonVisible = false;
    const sk = this.container.querySelector(".history-skeleton");
    if (sk) sk.remove();
  }

  private bindScroll(): void {
    this.container.addEventListener("scroll", () => {
      const { scrollTop, scrollHeight, clientHeight } = this.container;
      this.userScrolledUp = scrollTop + clientHeight < scrollHeight - 60;
    });
  }

  /** Reset scroll state (called on thread switch). */
  resetScroll(userScrolledUp = false, scrollTop = 0): void {
    this.userScrolledUp = userScrolledUp;
    if (scrollTop > 0) {
      this.container.scrollTop = scrollTop;
    }
  }

  /** Simple Markdown → HTML converter (bold, italic, code, links, lists). */
  private markdownToHtml(text: string): string {
    // Escape HTML first, then apply Markdown transformations
    let html = this.escape(text);
    // Code blocks: ```...```
    html = html.replace(
      /```(\w*)\n([\s\S]*?)```/g,
      (_: string, lang: string, code: string) =>
        `<pre><code class="${lang ? `language-${lang}` : ""}">${code.trim()}</code></pre>`,
    );
    // Inline code: `...`
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    // Bold: **...**
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    // Italic: *...*
    html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");
    // Links: [text](url)
    html = html.replace(
      /\[([^\]]+)\]\(([^)]+)\)/g,
      '<a href="$2" target="_blank">$1</a>',
    );
    // Unordered lists
    html = html.replace(/^- (.+)$/gm, "<li>$1</li>");
    html = html.replace(/(<li>.*<\/li>\n?)+/g, "<ul>$&</ul>");
    // Paragraphs: double newline
    html = html.replace(/\n\n/g, "</p><p>");
    return `<p>${html}</p>`;
  }

  private escape(text: string): string {
    const map: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return text.replace(/[&<>"']/g, (c) => map[c] || c);
  }

  private formatBytes(bytes: number): string {
    if (bytes === 0) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${(bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
  }
}
