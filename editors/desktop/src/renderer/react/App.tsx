/** React shell root — mounts components into existing DOM containers.
 *
 * This is an **incremental** migration.  The existing vanilla JS
 * renderer (main.ts) continues to own the ChatRenderer, file tree,
 * and artifact panels.  React only manages:
 *
 * - Left sidebar: ThreadList (replaces renderSessionList)
 * - Bottom bar: Composer (replaces the input area)
 * - Right sidebar: InspectorShell (replaces ad-hoc right panels)
 *
 * The bridge between vanilla and React is the ThreadStore — both
 * sides read/write the same observable state.
 */

import React, { useCallback } from "react";
import { createRoot } from "react-dom/client";
import { ThreadList } from "./components/ThreadList";
import { Composer } from "./components/Composer";
import { InspectorShell } from "./components/InspectorShell";
import { getThreadStore } from "../store/ThreadStore";
import { SessionManager } from "../store/SessionManager";

// ── Bootstrap into DOM ───────────────────────────────────────────────

export function mountReactShell(): void {
  // Mount into existing DOM elements created by the vanilla HTML template
  const mounts: { id: string; Component: React.FC }[] = [
    { id: "react-thread-list", Component: ThreadListShell },
    { id: "react-composer", Component: ComposerShell },
    { id: "react-inspector", Component: InspectorShellShell },
  ];

  for (const { id, Component } of mounts) {
    const el = document.getElementById(id);
    if (el) {
      createRoot(el).render(<Component />);
    }
  }

  // Theme sync
  const store = getThreadStore();
  store.subscribe((state) => {
    document.documentElement.dataset.theme = state.theme;
  });
}

// ── Shell wrappers (connect to SessionManager) ───────────────────────

let _sessionManager: SessionManager | null = null;

export function setSessionManager(sm: SessionManager): void {
  _sessionManager = sm;
}

const ThreadListShell: React.FC = () => {
  const sm = _sessionManager;

  const handleSwitch = useCallback(
    (id: string) => {
      sm?.switchThread(id);
    },
    [sm],
  );

  const handleNew = useCallback(() => {
    sm?.newThread();
  }, [sm]);

  const handleDelete = useCallback(
    (id: string) => {
      sm?.closeThread(id);
    },
    [sm],
  );

  return (
    <ThreadList
      onSwitchThread={handleSwitch}
      onNewThread={handleNew}
      onDeleteThread={handleDelete}
    />
  );
};

const ComposerShell: React.FC = () => {
  const store = getThreadStore();

  const handleSend = useCallback(
    (text: string, delivery: string) => {
      // Dispatch user input via the existing wire mechanism
      const activeThread = store.getActiveThread();
      const mode = activeThread?.sessionMode ?? "agent";
      const event = new CustomEvent("electromind:user-input", {
        detail: { text, delivery, mode },
      });
      window.dispatchEvent(event);
    },
    [store],
  );

  const handleStop = useCallback(() => {
    window.dispatchEvent(new CustomEvent("electromind:stop"));
  }, []);

  const handleModeChange = useCallback((mode: string) => {
    const id = store.getActiveThreadId();
    if (id) store.updateThread(id, { sessionMode: mode as never });
  }, [store]);

  const handleModelChange = useCallback((modelId: string) => {
    const id = store.getActiveThreadId();
    if (id) {
      store.updateThread(id, {
        model:
          modelId === "auto"
            ? { kind: "auto" }
            : { kind: "named", modelId },
      } as never);
    }
  }, [store]);

  const handleAutonomyChange = useCallback((level: string) => {
    const id = store.getActiveThreadId();
    if (id) store.updateThread(id, { autonomy: level as never });
  }, [store]);

  return (
    <Composer
      onSend={handleSend}
      onStop={handleStop}
      onModeChange={handleModeChange}
      onModelChange={handleModelChange}
      onAutonomyChange={handleAutonomyChange}
    />
  );
};

const InspectorShellShell: React.FC = () => {
  return <InspectorShell />;
};
