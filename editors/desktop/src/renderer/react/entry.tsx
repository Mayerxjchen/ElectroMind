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
import { SessionManager } from "../store/SessionManager";
import type { ThreadStore } from "../store/ThreadStore";
import { sharedThreadStore } from "./useStore";

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

/** Render the Composer into a given container with the wire-bridge props. */
function mountComposerAt(el: HTMLElement, store: ThreadStore): void {
  createRoot(el).render(
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

/** D3.4: mount the Composer into the dock's [data-composer-react] container
 *  and, only then, advertise readiness.
 *
 *  The vanilla shell creates the dock AFTER an await in start(), so this
 *  retries briefly.  A premature "ready" + an off-layout fallback mount would
 *  hide the vanilla composer while the React composer sits elsewhere — the
 *  input box disappears (reported bug).  Falls back to a standalone root only
 *  on non-desktop hosts where the dock never exists. */
function mountComposerIntoDock(store: ThreadStore, attempt = 0): void {
  const dockContainer = document.querySelector<HTMLElement>("[data-composer-react]");
  if (dockContainer) {
    mountComposerAt(dockContainer, store);
    const dock = document.querySelector<HTMLElement>("[data-composer-dock]");
    if (dock) {
      // rAF: let React commit before the shell swaps vanilla → React.
      requestAnimationFrame(() => {
        dock.setAttribute("data-composer-react", "ready");
      });
    }
    return;
  }
  if (attempt < 25) {
    // Dock not rendered yet (renderShell runs after the first await in
    // start()).  Retry ~80ms for up to ~2s before giving up.
    window.setTimeout(() => mountComposerIntoDock(store, attempt + 1), 80);
    return;
  }
  const fallback = ensureContainer("react-composer-root");
  if (fallback) mountComposerAt(fallback, store);
}

function mountReactShell(): void {
  // D3.4-2: bind to the VANILLA shell's ThreadStore singleton (the two
  // bundles each inline their own copy — sharing is mandatory).
  const store = sharedThreadStore();
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

  // ── Bottom: Composer (D3.4) ────────────────────────────────────
  // Mounts into the dock's [data-composer-react] once it exists and only
  // then signals ready (see mountComposerIntoDock).  Retries so the input
  // box never disappears behind a premature vanilla→React swap.
  mountComposerIntoDock(store);

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
