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
import { getCommandRegistry, type CommandContext } from "./command-registry";
import { registerCoreCommands, registerSkillSlashCommands } from "./commands";
import { modelSelectionFromPolicy } from "./model-policy";
import { loadDesktopFeatures } from "../features";

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
      onModelChange={(policy) => {
        const id = store.getActiveThreadId();
        if (id) {
          store.updateThread(id, { model: modelSelectionFromPolicy(policy) } as never);
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

// ── P0: Feature Flags 预加载（fail-closed 缓存；新功能由 flag 门控，默认全关）──
void loadDesktopFeatures();

// ── P1: 统一 Command Registry ───────────────────────────────────────
// 单例暴露到 window：vanilla keydown（main.ts）与 React 面板共用同一份
// 命令定义。注册幂等（size>0 跳过）—— renderer reload 后仍只有一份。
const commandRegistry = getCommandRegistry();
registerCoreCommands(commandRegistry);
(window as unknown as Record<string, unknown>).__electromindCommandRegistry =
  commandRegistry;

/** 构建命令执行上下文（keydown 处理器与面板共用）。 */
export function commandContext(): CommandContext {
  return {
    store: sharedThreadStore(),
    sessionManager: (window as unknown as Record<string, unknown>).__electromindSM,
  };
}

// ── P4: Skill 命令随 catalog 动态刷新 ───────────────────────────────
// 可信且可用户调用的 Skill → /<name> 命令（SKILLS 分组）。
// catalog 变化（skills/list / reload）→ 重建命令集（registry 内
// unregisterByPrefix 后重注册，不会出现重复命令）。
let lastSkillFingerprint = "";
sharedThreadStore().subscribe((state) => {
  const id = state.activeThreadId;
  const skills = id ? state.threads[id]?.skillsState : null;
  const fingerprint = skills ? `${skills.generation}:${skills.digest}` : "";
  if (fingerprint === lastSkillFingerprint) return;
  lastSkillFingerprint = fingerprint;
  registerSkillSlashCommands(
    commandRegistry,
    (skills?.skills ?? []).map((s) => ({
      ...s,
      trust_state: (s as { trust_state?: string }).trust_state,
    })),
  );
});

// ── Public API ─────────────────────────────────────────────────────

/** Kept for react-init.js compatibility.  The SessionManager will be
 *  consumed by later phases (thread list swap, command palette); the
 *  shell and composer are already live at this point. */
(window as unknown as Record<string, unknown>).__initReactShell__ = (
  sessionManager?: SessionManager,
) => {
  void sessionManager;
};
