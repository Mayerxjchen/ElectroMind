/** Desktop-native task-timeline renderer.
 *
 * Renders the PROJECTED TimelineItem[] (single source of truth — the
 * v1 raw-items path was removed with the D3 baseline).  Preserves
 * scroll position per thread; activity groups, inline approvals,
 * jobs/artifacts/plans are first-class blocks.
 */


import { VirtualList } from "./VirtualList.ts";
import { installCopyButtons, installMessageActions } from "./copy.ts";
import { renderIcon, type DesktopIconName } from "./icons.ts";
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

type PermitCallback = (toolCallId: string, approved: boolean) => void;

// ── MessageRenderer ──────────────────────────────────────────────────

export class MessageRenderer {
  private container: HTMLElement;
  private onPermit: PermitCallback;
  private userScrolledUp = false;
  private skeletonVisible = false;
  /** Projected task timeline (single source of truth). */
  private timeline: TimelineItem[] = [];
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
        el.appendChild(this.buildTimelineElement(this.timeline[index]));
      },
      estimateHeight: () => 80,
      overscan: 4,
    });
  }

  // ── ThreadStore-driven rendering ──────────────────────────────────

  /** Remove rendered state (called on thread switch or clear). */
  resetRendered(): void {
    this.groupOverrides.clear();
    this.lastSyncKey = "";
  }

  // ── Projected timeline rendering ──────────────────────────────────

  /**
   * Render the PROJECTED task timeline (single source of truth).  Each
   * TimelineItem is drawn by buildTimelineElement; in-place status
   * changes (action completed, job state, approval resolution) trigger
   * a virtual-list refresh via a cheap content fingerprint.
   */
  syncTimeline(timeline: TimelineItem[]): void {
    this.hideSkeleton();
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

    // ── Public API (ChatRenderer-compatible) ──────────────────────────



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
    this.timeline = [];
    this.virtualList.setCount(0);
    this.groupOverrides.clear();
    this.lastSyncKey = "";
    this.skeletonVisible = false;
  }

  showError(message: string): void {
    this.hideSkeleton();
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
  }





    // ── Helpers ────────────────────────────────────────────────────────

  private createBlock(className: string): HTMLElement {
    const el = document.createElement("div");
    el.className = `msg-block ${className}`;
    return el;
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
