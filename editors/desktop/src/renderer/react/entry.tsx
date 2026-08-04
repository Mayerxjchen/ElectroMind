/** React entry point — bootstraps the React shell.
 *
 *  Bundled separately, loaded after ``renderer.js``.  The vanilla
 *  renderer calls ``window.__initReactShell__()`` once the DOM and
 *  ThreadStore are ready.
 *
 *  React components mount into existing DOM containers.  If a
 *  container doesn't exist yet (vanilla renderer still loading),
 *  we create it and append to the app root.
 */

import { createRoot } from "react-dom/client";
import { ThreadList } from "./components/ThreadList";
import { Composer } from "./components/Composer";
import { InspectorShell } from "./components/InspectorShell";
import { getThreadStore } from "../store/ThreadStore";
import { SessionManager } from "../store/SessionManager";

let _sessionManager: SessionManager | null = null;

function ensureContainer(id: string, parentId = "app"): HTMLElement {
  let el = document.getElementById(id);
  if (!el) {
    el = document.createElement("div");
    el.id = id;
    const parent = document.getElementById(parentId);
    if (parent) parent.appendChild(el);
  }
  return el;
}

function mountReactShell(): void {
  const store = getThreadStore();
  const sm = _sessionManager;

  // ── Left sidebar: Thread list ──────────────────────────────────
  // Mount into a dedicated container under #app.  (The vanilla shell
  // owns [data-session-list] via innerHTML, so React must not share it.)
  const leftEl = ensureContainer("react-thread-list-root");
  if (leftEl) {
    createRoot(leftEl).render(
      <ThreadList
        onSwitchThread={(id) => sm?.switchThread(id)}
        onNewThread={() => sm?.newThread()}
        onDeleteThread={(id) => sm?.closeThread(id)}
      />,
    );
  }

  // ── Bottom: Composer ───────────────────────────────────────────
  const composerEl = ensureContainer("react-composer-root");
  if (composerEl) {
    createRoot(composerEl).render(
      <Composer
        onSend={(text) => {
          window.dispatchEvent(
            new CustomEvent("electromind:user-input", { detail: { text } }),
          );
        }}
        onStop={() => {
          window.dispatchEvent(new CustomEvent("electromind:stop"));
        }}
        onModeChange={(mode) => {
          const id = store.getActiveThreadId();
          if (id) store.updateThread(id, { sessionMode: mode as never });
        }}
        onModelChange={(modelId) => {
          const id = store.getActiveThreadId();
          if (id) {
            store.updateThread(id, {
              model:
                modelId === "auto"
                  ? { kind: "auto" }
                  : { kind: "named", modelId },
            } as never);
          }
        }}
        onAutonomyChange={(level) => {
          const id = store.getActiveThreadId();
          if (id) store.updateThread(id, { autonomy: level as never });
        }}
      />,
    );
  }

  // ── Right sidebar: Inspector ───────────────────────────────────
  const rightEl = ensureContainer("react-inspector-root");
  if (rightEl) {
    createRoot(rightEl).render(<InspectorShell />);
  }

  // Theme sync
  store.subscribe((state) => {
    document.documentElement.dataset.theme = state.theme;
  });
}

// ── Public API ─────────────────────────────────────────────────────

(window as unknown as Record<string, unknown>).__initReactShell__ = (
  sessionManager?: SessionManager,
) => {
  if (sessionManager) _sessionManager = sessionManager;
  mountReactShell();
};
