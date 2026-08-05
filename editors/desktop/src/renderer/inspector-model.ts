/** D3.2 Inspector state model — pure, DOM-free.
 *
 * The Inspector is default-closed and opens contextually: clicking a
 * Plan / file change / Artifact / Job / runtime pill / log opens the
 * matching tab.  All open/close/pin rules from the D3.2 spec live here
 * as a reducer so they can be pinned down by unit tests without a DOM.
 *
 * Single source of truth: the state lives in the ThreadStore
 * (``AppState.inspector``); this module only decides how it changes.
 */

export type InspectorTab =
  | "plan"
  | "changes"
  | "files"
  | "artifacts"
  | "jobs"
  | "runtime"
  | "logs";

export const INSPECTOR_TABS: readonly InspectorTab[] = [
  "plan",
  "changes",
  "files",
  "artifacts",
  "jobs",
  "runtime",
  "logs",
];

export function isInspectorTab(value: string | null | undefined): value is InspectorTab {
  return typeof value === "string" && (INSPECTOR_TABS as readonly string[]).includes(value);
}

export interface InspectorState {
  /** Panel visibility.  Default closed at startup. */
  open: boolean;
  /** Pinned — stays open across thread switches (Escape still closes
   *  an unpinned one only). */
  pinned: boolean;
  activeTab: InspectorTab;
  /** Optional resource to surface (e.g. an artifact path). */
  selectedResourceId?: string;
  /** Identity of the element that last opened the inspector — used for
   *  same-trigger toggle and focus return.  Not persisted. */
  triggerId?: string;
}

export type InspectorAction =
  /** Contextual trigger (timeline block, pill, …).  Re-triggering the
   *  same object toggles the inspector closed. */
  | { type: "trigger"; tab: InspectorTab; triggerId?: string; selectedResourceId?: string }
  /** Tab-bar click — always opens / switches, never toggles. */
  | { type: "openTab"; tab: InspectorTab }
  | { type: "close" }
  /** Escape: closes unless pinned. */
  | { type: "escape" }
  | { type: "pin"; pinned: boolean }
  /** Thread switch: unpinned closes; pinned stays open but the old
   *  thread's selection is dropped (content refreshes via the store). */
  | { type: "threadSwitched" }
  /** Startup restore: pinned flag + last tab survive, but the panel
   *  starts closed. */
  | { type: "restore"; pinned: boolean; lastTab: InspectorTab };

export function createInitialInspectorState(): InspectorState {
  return { open: false, pinned: false, activeTab: "files" };
}

export function inspectorReducer(
  prev: InspectorState,
  action: InspectorAction,
): InspectorState {
  switch (action.type) {
    case "trigger": {
      const sameTrigger =
        prev.open &&
        prev.activeTab === action.tab &&
        prev.triggerId === action.triggerId &&
        action.triggerId !== undefined;
      if (sameTrigger) {
        return { ...prev, open: false, triggerId: undefined };
      }
      return {
        ...prev,
        open: true,
        activeTab: action.tab,
        selectedResourceId: action.selectedResourceId,
        triggerId: action.triggerId,
      };
    }
    case "openTab":
      return { ...prev, open: true, activeTab: action.tab, selectedResourceId: undefined, triggerId: undefined };
    case "close":
      return { ...prev, open: false, triggerId: undefined };
    case "escape":
      return prev.pinned ? prev : { ...prev, open: false, triggerId: undefined };
    case "pin":
      return { ...prev, pinned: action.pinned };
    case "threadSwitched":
      if (prev.pinned) {
        return { ...prev, selectedResourceId: undefined, triggerId: undefined };
      }
      return { ...prev, open: false, selectedResourceId: undefined, triggerId: undefined };
    case "restore":
      return {
        open: false,
        pinned: action.pinned,
        activeTab: action.lastTab,
        selectedResourceId: undefined,
        triggerId: undefined,
      };
  }
}
