/** D3.2 InspectorController — vanilla-side owner of the right Inspector.
 *
 * The Inspector is default-closed and opens contextually.  All state
 * lives in the ThreadStore (``AppState.inspector``); this module
 * translates store state into DOM chrome and translates user gestures
 * into reducer actions.  Keeping the rules in inspector-model.ts (a
 * pure reducer) lets the unit tests pin the exact open/close/pin
 * behavior without a DOM.
 *
 * Owns:
 *  - workbench dataset (data-inspector-open / -pinned / -overlay)
 *  - right-pane width (push mode) vs overlay drawer (narrow windows)
 *  - Escape-to-close, pin/close buttons, contextual trigger clicks
 *  - focus return to the triggering element after close
 *  - persistence of pinned flag + last tab
 *  - the plan / changes / jobs / runtime-status views
 */

import { getThreadStore } from "./store/ThreadStore";
import type { InspectorState, InspectorTab, ThreadState } from "./store/types";
import {
  inspectorReducer,
  isInspectorTab,
  type InspectorAction,
} from "./inspector-model";
import { renderIcon } from "./icons";

/** ≥ PUSH_BREAKPOINT_PX: Inspector pushes the central pane; below it the
 *  Inspector overlays as a right drawer. */
const PUSH_BREAKPOINT_PX = 1280;
/** ≥ WIDE_BREAKPOINT_PX: roomier Inspector (420px); else 360px.  The
 *  360px floor keeps the chat ≥ 680px at 1280×800 (1280 − 220 left −
 *  16 gaps − 360 = 684). */
const WIDE_BREAKPOINT_PX = 1536;
const INSPECTOR_WIDTH_PX = 360;
const INSPECTOR_WIDTH_WIDE_PX = 420;

const PIN_KEY = "electromind-desktop-inspector-pinned";
const LAST_TAB_KEY = "electromind-desktop-inspector-last-tab";

export interface InspectorDeps {
  workbench: HTMLElement;
  /** Sync the vanilla shell's active view + lazy-load per tab. */
  onTabChange: (tab: InspectorTab) => void;
}

export class InspectorController {
  private readonly store = getThreadStore();
  private readonly deps: InspectorDeps;
  private prevThreadId: string | null = null;
  private pinButton: HTMLButtonElement | null = null;
  private closeButton: HTMLButtonElement | null = null;
  private unsubscribe: (() => void) | null = null;
  private attached = false;

  constructor(deps: InspectorDeps) {
    this.deps = deps;
  }

  attach(): void {
    if (this.attached) return;
    this.attached = true;
    this.pinButton = document.querySelector<HTMLButtonElement>("[data-inspector-pin]");
    this.closeButton = document.querySelector<HTMLButtonElement>("[data-inspector-close]");
    this.prevThreadId = this.store.getState().activeThreadId;
    this.restore();
    this.unsubscribe = this.store.subscribe(() => this.onStoreChanged());
    window.addEventListener("keydown", this.handleKeydown);
    window.addEventListener("resize", this.applyChrome);
    document
      .querySelector<HTMLElement>("[data-chat-log]")
      ?.addEventListener("click", this.handleChatClick);
    this.pinButton?.addEventListener("click", this.handlePinClick);
    this.closeButton?.addEventListener("click", this.handleCloseClick);
    document
      .querySelector<HTMLElement>("[data-sandbox-pill]")
      ?.addEventListener("click", () => this.dispatch({ type: "trigger", tab: "runtime", triggerId: "sandbox-pill" }));
    document
      .querySelector<HTMLElement>("[data-select-project]")
      ?.addEventListener("click", () => this.dispatch({ type: "trigger", tab: "files", triggerId: "project-pill" }));
    this.applyChrome();
  }

  dispose(): void {
    if (!this.attached) return;
    this.attached = false;
    this.unsubscribe?.();
    window.removeEventListener("keydown", this.handleKeydown);
    window.removeEventListener("resize", this.applyChrome);
    document
      .querySelector<HTMLElement>("[data-chat-log]")
      ?.removeEventListener("click", this.handleChatClick);
    this.pinButton?.removeEventListener("click", this.handlePinClick);
    this.closeButton?.removeEventListener("click", this.handleCloseClick);
  }

  /** Tab-bar click entry (called from the vanilla tab group). */
  openTab(tab: InspectorTab): void {
    this.dispatch({ type: "openTab", tab });
  }

  /** Keyboard shortcut entry: close if open, else reopen the last tab. */
  toggle(): void {
    const s = this.store.getState().inspector;
    this.dispatch(s.open ? { type: "close" } : { type: "openTab", tab: s.activeTab });
  }

  // ── state transitions ─────────────────────────────────────────────

  private dispatch(action: InspectorAction): void {
    const next = inspectorReducer(this.store.getState().inspector, action);
    this.store.setInspector(next);
    this.persist(next);
  }

  private restore(): void {
    const pinned = readStoredFlag(PIN_KEY, false);
    const lastTab = readStoredTab(LAST_TAB_KEY, "files");
    this.store.setInspector(
      inspectorReducer(this.store.getState().inspector, {
        type: "restore",
        pinned,
        lastTab,
      }),
    );
  }

  private persist(state: InspectorState): void {
    try {
      window.localStorage.setItem(PIN_KEY, state.pinned ? "1" : "0");
      window.localStorage.setItem(LAST_TAB_KEY, state.activeTab);
    } catch {
      /* storage unavailable — persistence is best-effort */
    }
  }

  // ── store → DOM ───────────────────────────────────────────────────

  private onStoreChanged(): void {
    const state = this.store.getState();
    if (state.activeThreadId !== this.prevThreadId) {
      this.prevThreadId = state.activeThreadId;
      this.dispatch({ type: "threadSwitched" });
    }
    this.applyChrome();
  }

  private applyChrome = (): void => {
    const s = this.store.getState().inspector;
    const wb = this.deps.workbench;
    const overlay = window.innerWidth < PUSH_BREAKPOINT_PX;
    wb.dataset.inspectorOpen = String(s.open);
    wb.dataset.inspectorPinned = String(s.pinned);
    wb.dataset.inspectorOverlay = String(overlay);
    // In overlay mode the pane is out of the grid flow (absolute), so the
    // grid track must not reserve space — the CSS width rule applies.
    wb.style.setProperty("--right-pane-width", this.rightWidth(overlay));
    wb.style.setProperty("--right-gap", s.open && !overlay ? "8px" : "0px");
    this.deps.onTabChange(s.activeTab);
    this.syncPinButton(s);
    this.renderViews();
  };

  private rightWidth(overlay: boolean): string {
    const s = this.store.getState().inspector;
    if (!s.open || overlay) return "0px";
    return window.innerWidth >= WIDE_BREAKPOINT_PX
      ? `${INSPECTOR_WIDTH_WIDE_PX}px`
      : `${INSPECTOR_WIDTH_PX}px`;
  }

  private syncPinButton(s: InspectorState): void {
    if (!this.pinButton) return;
    const pinned = s.pinned;
    this.pinButton.classList.toggle("active", pinned);
    this.pinButton.title = pinned ? "取消钉住（保持打开）" : "钉住（切换任务时保持打开）";
    this.pinButton.setAttribute("aria-pressed", String(pinned));
    this.pinButton.innerHTML = renderIcon(pinned ? "pin" : "pin-off");
  }

  // ── gestures ──────────────────────────────────────────────────────

  private handleKeydown = (event: KeyboardEvent): void => {
    if (event.key !== "Escape") return;
    const s = this.store.getState().inspector;
    if (s.open && !s.pinned) {
      const triggerId = s.triggerId;
      this.dispatch({ type: "escape" });
      this.restoreFocus(triggerId);
      event.preventDefault();
    }
  };

  private handlePinClick = (): void => {
    const s = this.store.getState().inspector;
    this.dispatch({ type: "pin", pinned: !s.pinned });
  };

  private handleCloseClick = (): void => {
    const triggerId = this.store.getState().inspector.triggerId;
    this.dispatch({ type: "close" });
    this.restoreFocus(triggerId);
  };

  /** Contextual triggers inside the timeline: plan / file-change /
   *  artifact blocks carry data-inspector-tab.  Controls inside the
   *  block (approve, preview, …) keep their own behavior. */
  private handleChatClick = (event: MouseEvent): void => {
    const target = event.target as HTMLElement | null;
    if (!target) return;
    if (target.closest("button, a, input, textarea, select, [role='button'], [contenteditable='true']")) {
      return;
    }
    const trigger = target.closest<HTMLElement>("[data-inspector-tab]");
    if (!trigger) return;
    const tab = trigger.dataset.inspectorTab as InspectorTab | undefined;
    if (!tab) return;
    this.dispatch({
      type: "trigger",
      tab,
      triggerId: trigger.dataset.inspectorTrigger ?? tab,
      selectedResourceId: trigger.dataset.inspectorResource,
    });
  };

  /** After closing, keyboard focus returns to the element that opened
   *  the Inspector (timeline blocks re-render, so re-query by id). */
  private restoreFocus(triggerId: string | undefined): void {
    if (!triggerId) return;
    const el = document.querySelector<HTMLElement>(
      `[data-inspector-trigger="${cssEscape(triggerId)}"]`,
    );
    el?.focus({ preventScroll: true });
  }

  // ── inspector content views ───────────────────────────────────────

  private renderViews(): void {
    const state = this.store.getState();
    if (!state.inspector.open) return;
    const thread = state.activeThreadId ? state.threads[state.activeThreadId] : null;
    switch (state.inspector.activeTab) {
      case "plan":
        this.renderPlan(thread);
        break;
      case "changes":
        this.renderChanges(thread);
        break;
      case "jobs":
        this.renderJobs(thread);
        break;
      case "runtime":
        this.renderRuntimeStatus(thread);
        break;
      default:
        break; // files / artifacts / logs are vanilla-owned views
    }
  }

  private renderPlan(thread: ThreadState | null): void {
    const host = document.querySelector<HTMLElement>("[data-inspector-view='plan']");
    if (!host) return;
    const plan = thread?.plan;
    if (!plan) {
      host.innerHTML = `<div class="inspector-empty"><span class="inspector-empty-icon">${renderIcon("file-text")}</span><span>当前任务还没有计划</span></div>`;
      return;
    }
    const steps = plan.steps
      .map(
        (st, i) => `<li class="inspector-plan-step">
          <span class="inspector-plan-step-num">${i + 1}.</span>
          <span class="inspector-plan-step-title">${escapeHtml(st.title)}</span>
          <span class="inspector-plan-step-status status-${cssClass(st.status)}">${escapeHtml(st.status)}</span>
        </li>`,
      )
      .join("");
    const risks = plan.risks.length
      ? `<details class="inspector-plan-details"><summary>风险 (${plan.risks.length})</summary><ul>${plan.risks.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul></details>`
      : "";
    host.innerHTML = `<div class="inspector-plan">
      <div class="inspector-plan-head">
        <span class="inspector-plan-status status-${cssClass(plan.status)}">${escapeHtml(plan.status)}</span>
        <span class="inspector-plan-meta">v${plan.version} · ${escapeHtml(plan.plan_id)}</span>
      </div>
      ${plan.objective ? `<p class="inspector-plan-objective">${escapeHtml(plan.objective)}</p>` : ""}
      ${steps ? `<ol class="inspector-plan-steps">${steps}</ol>` : ""}
      ${risks}
    </div>`;
  }

  private renderChanges(thread: ThreadState | null): void {
    const host = document.querySelector<HTMLElement>("[data-inspector-view='changes']");
    if (!host) return;
    const changes = (thread?.items ?? [])
      .filter((it) => it.kind === "file_change")
      .map((it) => {
        const p = it.payload ?? {};
        return {
          path: String(p.path ?? ""),
          status: String(p.status ?? "modified"),
          additions: Number(p.additions ?? 0),
          deletions: Number(p.deletions ?? 0),
        };
      });
    if (!changes.length) {
      host.innerHTML = `<div class="inspector-empty"><span class="inspector-empty-icon">${renderIcon("code-xml")}</span><span>暂无文件变更</span></div>`;
      return;
    }
    host.innerHTML = `<ul class="inspector-changes">${changes
      .map((c) => {
        const letter = c.status === "added" ? "A" : c.status === "deleted" ? "D" : "M";
        return `<li class="inspector-change">
          <span class="inspector-change-status status-${cssClass(c.status)}">${letter}</span>
          <span class="inspector-change-path" title="${escapeHtml(c.path)}">${escapeHtml(c.path)}</span>
          <span class="inspector-change-stats">+${c.additions} −${c.deletions}</span>
        </li>`;
      })
      .join("")}</ul>`;
  }

  private renderJobs(thread: ThreadState | null): void {
    const host = document.querySelector<HTMLElement>("[data-inspector-view='jobs']");
    if (!host) return;
    const run = thread?.activeRun;
    if (!run) {
      host.innerHTML = `<div class="inspector-empty"><span class="inspector-empty-icon">${renderIcon("server")}</span><span>当前任务没有活动运行</span></div>`;
      return;
    }
    const elapsed = Math.max(0, Math.round((Date.now() - run.startedAt) / 1000));
    const pending = run.pendingApprovals.length
      ? `<span class="inspector-job-stat">待审批 ${run.pendingApprovals.length}</span>`
      : "";
    host.innerHTML = `<div class="inspector-job-card">
      <div class="inspector-job-head">
        <span class="inspector-job-phase status-${cssClass(run.phase)}">${escapeHtml(run.phase)}</span>
        <span class="inspector-job-elapsed">${elapsed}s</span>
      </div>
      <div class="inspector-job-stats">
        <span class="inspector-job-stat">工具调用 ${run.toolCallsIssued}</span>
        ${pending}
      </div>
    </div>`;
  }

  private renderRuntimeStatus(thread: ThreadState | null): void {
    const host = document.querySelector<HTMLElement>("[data-runtime-status]");
    if (!host) return;
    const sb = thread?.sandboxStatus;
    const ec = thread?.executionContextState;
    if (!sb && !ec) {
      host.innerHTML = "";
      return;
    }
    const sandbox =
      sb != null
        ? `<span class="runtime-backend">
            <span class="runtime-dot ${sb.alive ? "alive" : "dead"}" aria-hidden="true"></span>
            ${escapeHtml(backendLabel(sb.backend))}
          </span>
          <span class="runtime-workdir" title="${escapeHtml(sb.workdir)}">${escapeHtml(sb.workdir)}</span>`
        : "";
    const context =
      ec != null
        ? `<span class="runtime-target">${escapeHtml(ec.target)} · ${escapeHtml(ec.profileId)}</span>`
        : "";
    host.innerHTML = `<div class="runtime-status">${sandbox}${context}</div>`;
  }
}

// ── helpers ──────────────────────────────────────────────────────────

function backendLabel(backend: string): string {
  if (backend === "container" || backend === "docker" || backend === "podman") {
    return "container";
  }
  if (backend === "ssh") {
    return "ssh";
  }
  return "local";
}

function cssClass(value: unknown): string {
  return String(value ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-");
}

function escapeHtml(text: unknown): string {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function cssEscape(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]/g, (ch) => `\\${ch}`);
}

function readStoredFlag(key: string, fallback: boolean): boolean {
  try {
    const v = window.localStorage.getItem(key);
    return v !== null ? v === "1" : fallback;
  } catch {
    return fallback;
  }
}

function readStoredTab(key: string, fallback: InspectorTab): InspectorTab {
  try {
    const v = window.localStorage.getItem(key);
    if (isInspectorTab(v)) return v;
  } catch {
    /* ignore */
  }
  return fallback;
}
