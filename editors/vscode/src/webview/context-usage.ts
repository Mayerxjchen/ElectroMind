/** Token / cache metering from TurnResult.usage — composer ring UI. */

export type UsageDict = {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  prompt_tokens_details?: {
    cached_tokens?: number;
    cache_write_tokens?: number;
  };
  completion_tokens_details?: {
    reasoning_tokens?: number;
    accepted_prediction_tokens?: number;
    rejected_prediction_tokens?: number;
  };
};

export type ContextUsageSnapshot = {
  contextLimit: number;
  promptTokens: number;
  cachedTokens: number;
  uncachedPromptTokens: number;
  cacheWriteTokens: number;
  lastCompletionTokens: number;
  lastReasoningTokens: number;
  runCompletionTokens: number;
  runReasoningTokens: number;
  runTurnCount: number;
};

export const DEFAULT_CONTEXT_LIMIT = 128_000;

function readUsageDict(value: unknown): UsageDict | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  return value as UsageDict;
}

function readCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? Math.max(0, value) : 0;
}

export class ContextUsageTracker {
  private contextLimit = DEFAULT_CONTEXT_LIMIT;
  private promptTokens = 0;
  private cachedTokens = 0;
  private cacheWriteTokens = 0;
  private lastCompletionTokens = 0;
  private lastReasoningTokens = 0;
  private runCompletionTokens = 0;
  private runReasoningTokens = 0;
  private runTurnCount = 0;

  setContextLimit(limit: number): void {
    if (Number.isFinite(limit) && limit > 0) {
      this.contextLimit = limit;
    }
  }

  resetAll(): void {
    this.promptTokens = 0;
    this.cachedTokens = 0;
    this.cacheWriteTokens = 0;
    this.lastCompletionTokens = 0;
    this.lastReasoningTokens = 0;
    this.runCompletionTokens = 0;
    this.runReasoningTokens = 0;
    this.runTurnCount = 0;
  }

  resetRun(): void {
    this.lastCompletionTokens = 0;
    this.lastReasoningTokens = 0;
    this.runCompletionTokens = 0;
    this.runReasoningTokens = 0;
    this.runTurnCount = 0;
  }

  ingestTurnResult(usage: unknown): void {
    const dict = readUsageDict(usage);
    if (!dict) {
      return;
    }

    const prompt = readCount(dict.prompt_tokens);
    const completion = readCount(dict.completion_tokens);
    const cached = readCount(dict.prompt_tokens_details?.cached_tokens);
    const cacheWrite = readCount(dict.prompt_tokens_details?.cache_write_tokens);
    const reasoning = readCount(dict.completion_tokens_details?.reasoning_tokens);

    if (prompt > 0) {
      this.promptTokens = prompt;
      this.cachedTokens = Math.min(cached, prompt);
      this.cacheWriteTokens = cacheWrite;
    }
    this.lastCompletionTokens = completion;
    this.lastReasoningTokens = reasoning;
    this.runCompletionTokens += completion;
    this.runReasoningTokens += reasoning;
    this.runTurnCount += 1;
  }

  restoreFromSnapshot(snapshot: unknown): void {
    this.resetAll();
    if (!snapshot || typeof snapshot !== "object") {
      return;
    }
    const data = snapshot as Record<string, unknown>;
    const limit = readCount(data.context_limit);
    if (limit > 0) {
      this.contextLimit = limit;
    }
    this.promptTokens = readCount(data.prompt_tokens);
    this.cachedTokens = Math.min(readCount(data.cached_tokens), this.promptTokens);
    this.cacheWriteTokens = readCount(data.cache_write_tokens);
    this.lastCompletionTokens = readCount(data.completion_tokens);
    this.lastReasoningTokens = readCount(data.reasoning_tokens);
  }

  snapshot(): ContextUsageSnapshot {
    const uncachedPromptTokens = Math.max(0, this.promptTokens - this.cachedTokens);
    return {
      contextLimit: this.contextLimit,
      promptTokens: this.promptTokens,
      cachedTokens: this.cachedTokens,
      uncachedPromptTokens,
      cacheWriteTokens: this.cacheWriteTokens,
      lastCompletionTokens: this.lastCompletionTokens,
      lastReasoningTokens: this.lastReasoningTokens,
      runCompletionTokens: this.runCompletionTokens,
      runReasoningTokens: this.runReasoningTokens,
      runTurnCount: this.runTurnCount,
    };
  }
}

type WireEventMessage = {
  method: string;
  params: Record<string, unknown>;
};

function formatTokens(value: number): string {
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}M`;
  }
  if (value >= 10_000) {
    return `${Math.round(value / 1000)}k`;
  }
  if (value >= 1000) {
    return `${(value / 1000).toFixed(1)}k`;
  }
  return String(value);
}

function formatPercent(part: number, total: number): string {
  if (total <= 0) {
    return "0%";
  }
  return `${Math.round((part / total) * 100)}%`;
}

const RING_RADIUS = 9;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

export class ContextUsageRing {
  private readonly tracker = new ContextUsageTracker();
  private readonly button: HTMLButtonElement;
  private readonly track: SVGCircleElement;
  private readonly cachedArc: SVGCircleElement;
  private readonly uncachedArc: SVGCircleElement;
  private readonly popover: HTMLDivElement;

  constructor(mount: HTMLElement) {
    this.button = document.createElement("button");
    this.button.type = "button";
    this.button.className = "composer-btn context-usage-btn";
    this.button.setAttribute("aria-label", "上下文用量");
    this.button.title = "上下文用量";

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("class", "context-usage-svg");
    svg.setAttribute("aria-hidden", "true");

    const makeCircle = (className: string) => {
      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("cx", "12");
      circle.setAttribute("cy", "12");
      circle.setAttribute("r", String(RING_RADIUS));
      circle.setAttribute("fill", "none");
      circle.setAttribute("stroke-width", "2.5");
      circle.setAttribute("class", className);
      svg.appendChild(circle);
      return circle;
    };

    this.track = makeCircle("context-usage-track");
    this.cachedArc = makeCircle("context-usage-segment context-usage-cached");
    this.uncachedArc = makeCircle("context-usage-segment context-usage-uncached");
    this.track.setAttribute("stroke-width", "2");

    this.button.appendChild(svg);

    this.popover = document.createElement("div");
    this.popover.className = "context-usage-popover";
    this.popover.hidden = true;
    document.body.appendChild(this.popover);

    mount.appendChild(this.button);

    this.button.addEventListener("click", (event) => {
      event.stopPropagation();
      this.setPopoverOpen(this.popover.hidden);
    });
    document.addEventListener("mousedown", (event) => {
      if (this.popover.hidden) {
        return;
      }
      const target = event.target as Node;
      if (!this.button.contains(target) && !this.popover.contains(target)) {
        this.setPopoverOpen(false);
      }
    });
    window.addEventListener("resize", () => {
      if (!this.popover.hidden) {
        this.positionPopover();
      }
    });
    window.addEventListener(
      "scroll",
      () => {
        if (!this.popover.hidden) {
          this.positionPopover();
        }
      },
      true,
    );

    this.configureArc(this.track, 1, 0);
    this.configureArc(this.cachedArc, 0, 0);
    this.configureArc(this.uncachedArc, 0, 0);
    this.render();
  }

  setContextLimit(limit: number): void {
    this.tracker.setContextLimit(limit);
    this.render();
  }

  handleWireEvent(event: WireEventMessage): void {
    if (event.method === "RunBegin") {
      this.tracker.resetRun();
      this.render();
      return;
    }
    if (event.method === "TurnResult") {
      this.tracker.ingestTurnResult(event.params.usage);
      this.render();
      return;
    }
    if (event.method === "HistoryReplay") {
      const topLimit = readCount(event.params.context_limit);
      if (topLimit > 0) {
        this.tracker.setContextLimit(topLimit);
      }
      const usage = event.params.usage;
      if (usage) {
        this.tracker.restoreFromSnapshot(usage);
      } else {
        this.tracker.resetAll();
      }
      this.render();
    }
  }

  private setPopoverOpen(open: boolean): void {
    this.popover.hidden = !open;
    if (open) {
      this.positionPopover();
    }
  }

  private positionPopover(): void {
    const anchor = this.button.getBoundingClientRect();
    const gap = 8;
    const margin = 8;

    this.popover.style.visibility = "hidden";
    this.popover.hidden = false;
    const panel = this.popover.getBoundingClientRect();

    let left = anchor.right - panel.width;
    let top = anchor.top - gap - panel.height;

    if (top < margin) {
      top = anchor.bottom + gap;
    }

    left = Math.max(margin, Math.min(left, window.innerWidth - panel.width - margin));
    top = Math.max(margin, Math.min(top, window.innerHeight - panel.height - margin));

    this.popover.style.left = `${Math.round(left)}px`;
    this.popover.style.top = `${Math.round(top)}px`;
    this.popover.style.visibility = "";
  }

  private configureArc(circle: SVGCircleElement, fraction: number, offsetFraction: number): void {
    const clamped = Math.max(0, Math.min(1, fraction));
    const length = clamped * RING_CIRCUMFERENCE;
    const gap = RING_CIRCUMFERENCE - length;
    circle.setAttribute("stroke-dasharray", `${length} ${gap}`);
    circle.setAttribute(
      "stroke-dashoffset",
      String(-offsetFraction * RING_CIRCUMFERENCE + RING_CIRCUMFERENCE * 0.25),
    );
    circle.style.opacity = clamped > 0 ? "1" : "0";
  }

  private render(): void {
    const snap = this.tracker.snapshot();
    const limit = snap.contextLimit;
    const promptFraction = limit > 0 ? Math.min(1, snap.promptTokens / limit) : 0;
    const cachedFraction =
      limit > 0 ? Math.min(promptFraction, snap.cachedTokens / limit) : 0;
    const uncachedFraction = Math.max(0, promptFraction - cachedFraction);

    this.configureArc(this.track, 1, 0);
    this.configureArc(this.cachedArc, cachedFraction, 0);
    this.configureArc(this.uncachedArc, uncachedFraction, cachedFraction);

    this.button.classList.toggle("is-hot", snap.promptTokens > limit);
    this.button.classList.toggle("is-idle", snap.promptTokens === 0);

    const contextPercent = formatPercent(snap.promptTokens, limit);
    const cachePercent = formatPercent(snap.cachedTokens, snap.promptTokens);

    this.button.title = snap.promptTokens
      ? `上下文 ${formatTokens(snap.promptTokens)} / ${formatTokens(limit)}（${contextPercent}）`
      : "上下文用量";

    this.popover.replaceChildren(
      this.makeRow("上下文输入", `${formatTokens(snap.promptTokens)} / ${formatTokens(limit)}`, contextPercent, true),
      this.makeRow("缓存命中", formatTokens(snap.cachedTokens), cachePercent),
      this.makeRow("未缓存输入", formatTokens(snap.uncachedPromptTokens)),
      this.makeRow("写入缓存", formatTokens(snap.cacheWriteTokens)),
      this.makeDivider(),
      this.makeRow("本轮输出", formatTokens(snap.lastCompletionTokens)),
      this.makeRow("推理 token", formatTokens(snap.lastReasoningTokens)),
      this.makeDivider(),
      this.makeRow("本次 run 输出", formatTokens(snap.runCompletionTokens)),
      this.makeRow("本次 run 推理", formatTokens(snap.runReasoningTokens)),
      this.makeRow("本次 run 调用", String(snap.runTurnCount)),
      this.makeLegend(),
    );
  }

  private makeDivider(): HTMLHRElement {
    const hr = document.createElement("hr");
    hr.className = "context-usage-divider";
    return hr;
  }

  private makeRow(
    label: string,
    value: string,
    hint?: string,
    emphasize = false,
  ): HTMLDivElement {
    const row = document.createElement("div");
    row.className = "context-usage-row";
    if (emphasize) {
      row.classList.add("is-emphasis");
    }

    const labelEl = document.createElement("span");
    labelEl.className = "context-usage-label";
    labelEl.textContent = label;

    const valueEl = document.createElement("span");
    valueEl.className = "context-usage-value";
    valueEl.textContent = hint ? `${value} · ${hint}` : value;

    row.append(labelEl, valueEl);
    return row;
  }

  private makeLegend(): HTMLDivElement {
    const legend = document.createElement("div");
    legend.className = "context-usage-legend";
    legend.innerHTML =
      '<span class="context-usage-legend-item"><i class="context-usage-swatch cached"></i>缓存</span>' +
      '<span class="context-usage-legend-item"><i class="context-usage-swatch uncached"></i>未缓存</span>';
    return legend;
  }
}
