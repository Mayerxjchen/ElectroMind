/** React entry point — bootstraps the React shell.
 *
 *  Bundled separately, loaded after ``renderer.js``.  At module
 *  evaluation it renders the AppShell (the React-owned shell skeleton)
 *  into ``#app``, then mounts the Composer into the dock's
 *  ``[data-composer-react]`` once the shared ThreadStore is available.
 *
 *  Ownership model (P0「单一 Shell 布局所有者」):
 *  - React owns the SHELL skeleton (AppShell: titlebar / workbench /
 *    composer dock / overlay layer slots).
 *  - The vanilla renderer fills content slots (session list, topbar,
 *    inspector, modals) — its renderShell waits for ``[data-shell]``
 *    and only falls back to the full vanilla template if React never
 *    mounts.
 *  - The vanilla composer stays inside the dock as a pre-ready
 *    fallback; CSS swaps it out once ``data-composer-react="ready"``.
 */

import { createRoot } from "react-dom/client";
import { AppShell } from "./components/AppShell";
import { Composer } from "./components/Composer";
import { SessionManager } from "../store/SessionManager";
import type { ThreadStore } from "../store/ThreadStore";
import { sharedThreadStore } from "./useStore";

/** Render the AppShell skeleton.  Called once at module evaluation.
 *  Guard: if the vanilla fallback already rendered its own shell
 *  (React shell never mounted), do not stack a second one. */
function mountAppShell(): void {
  const app = document.getElementById("app");
  if (!app || document.querySelector(".desktop-shell")) return;
  const el = document.createElement("div");
  el.id = "react-appshell-root";
  el.style.height = "100%";
  app.appendChild(el);
  createRoot(el).render(<AppShell />);
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

/** Mount the Composer into the dock's [data-composer-react] container and,
 *  only then, advertise readiness.
 *
 *  In the React-shell path the dock exists from the moment AppShell
 *  renders (module evaluation), so this resolves immediately.  In the
 *  legacy fallback path the dock is created by the vanilla template
 *  after start()'s first await, so this retries briefly — a premature
 *  "ready" + an off-layout fallback mount would hide the vanilla
 *  composer while the React composer sits elsewhere (input disappears). */
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
    window.setTimeout(() => mountComposerIntoDock(store, attempt + 1), 80);
    return;
  }
  // Neither shell path produced a dock — nothing to mount into.  The
  // vanilla composer (if any) remains the live input.
}

/** Module evaluation: React owns the shell from the first paint.  The
 *  store singleton is created by renderer.js at module level, so the
 *  composer can subscribe immediately. */
mountAppShell();
mountComposerIntoDock(sharedThreadStore());

// ── Public API ─────────────────────────────────────────────────────

/** Kept for react-init.js compatibility.  The SessionManager will be
 *  consumed by later phases (thread list swap, command palette); the
 *  shell and composer are already live at this point. */
(window as unknown as Record<string, unknown>).__initReactShell__ = (
  sessionManager?: SessionManager,
) => {
  void sessionManager;
};
