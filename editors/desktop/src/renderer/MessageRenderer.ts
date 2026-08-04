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
import type { ThreadItem } from "./store/types.ts";

// ── Types ────────────────────────────────────────────────────────────

export interface WireEventMessage {
  method: string;
  params: Record<string, unknown>;
}

type PermitCallback = (toolCallId: string, approved: boolean) => void;

// ── MessageRenderer ──────────────────────────────────────────────────

export class MessageRenderer {
  private container: HTMLElement;
  private onPermit: PermitCallback;
  private userScrolledUp = false;
  private skeletonVisible = false;
  private toolCards = new Map<string, HTMLElement>();
  private permitPrompts = new Map<string, HTMLElement>();
  private items: ThreadItem[] = [];
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
        el.appendChild(this.buildItemElement(this.items[index]));
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
    const prevCount = this.items.length;
    this.items = items;

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
    // Route through the virtual timeline (single rendering path)
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
    this.virtualList.setCount(0);
    this.toolCards.clear();
    this.permitPrompts.clear();
    this.renderedIds.clear();
    this.renderedDoneIds.clear();
    this.skeletonVisible = false;
  }

  showError(message: string): void {
    this.hideSkeleton();
    // Route through the virtual timeline (single rendering path)
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
