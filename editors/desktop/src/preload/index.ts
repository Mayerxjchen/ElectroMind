import { contextBridge, ipcRenderer } from "electron";
import type {
  DesktopApi,
  DesktopEvent,
  ResetSessionOptions,
  RuntimeState,
} from "../shared/protocol";

function subscribeToChannel<T>(
  channel: string,
  listener: (payload: T) => void,
): () => void {
  const wrapped = (_event: unknown, payload: T) => listener(payload);
  ipcRenderer.on(channel, wrapped);
  return () => {
    ipcRenderer.off(channel, wrapped);
  };
}

const desktopApi: DesktopApi = {
  getAppInfo() {
    return ipcRenderer.invoke("desktop:get-app-info");
  },
  getRuntimeState() {
    return ipcRenderer.invoke("desktop:get-runtime-state");
  },
  setYoloMode(enabled: boolean) {
    return ipcRenderer.invoke("desktop:set-yolo-mode", enabled);
  },
  listThreads() {
    return ipcRenderer.invoke("desktop:list-threads");
  },
  getThreadMeta(threadId: string) {
    return ipcRenderer.invoke("desktop:get-thread-meta", threadId);
  },
  getSettings() {
    return ipcRenderer.invoke("desktop:get-settings");
  },
  openDocumentation() {
    return ipcRenderer.invoke("desktop:open-documentation");
  },
  listArtifacts() {
    return ipcRenderer.invoke("desktop:list-artifacts");
  },
  openArtifact(path: string) {
    return ipcRenderer.invoke("desktop:open-artifact", path);
  },
  readArtifact(path: string) {
    return ipcRenderer.invoke("desktop:read-artifact", path);
  },
  getSandboxStatus() {
    return ipcRenderer.invoke("desktop:get-sandbox-status");
  },
  listSandboxTree() {
    return ipcRenderer.invoke("desktop:list-sandbox-tree");
  },
  listProjectFiles() {
    return ipcRenderer.invoke("desktop:list-project-files");
  },
  listProjectTree() {
    return ipcRenderer.invoke("desktop:list-project-tree");
  },
  selectProject() {
    return ipcRenderer.invoke("desktop:select-project");
  },
  pickDirectory(defaultPath?: string) {
    return ipcRenderer.invoke("desktop:pick-directory", defaultPath);
  },
  getNewSessionOptions() {
    return ipcRenderer.invoke("desktop:get-new-session-options");
  },
  resumeThread(threadId: string) {
    return ipcRenderer.invoke("desktop:resume-thread", threadId);
  },
  deleteThread(threadId: string) {
    return ipcRenderer.invoke("desktop:delete-thread", threadId);
  },
  sendUserInput(text: string) {
    return ipcRenderer.invoke("desktop:send-user-input", text);
  },
  clearLastError() {
    return ipcRenderer.invoke("desktop:clear-last-error");
  },
  resetSession(options?: ResetSessionOptions) {
    return ipcRenderer.invoke("desktop:reset-session", options);
  },
  requestHistoryReplay() {
    return ipcRenderer.invoke("desktop:request-history");
  },
  sendWireCommand(command: Record<string, unknown>) {
    return ipcRenderer.invoke("desktop:send-wire-command", command);
  },
  permitToolCall(toolCallId: string) {
    return ipcRenderer.invoke("desktop:permit-tool-call", toolCallId);
  },
  denyToolCall(toolCallId: string, reason?: string) {
    return ipcRenderer.invoke("desktop:deny-tool-call", toolCallId, reason);
  },
  onAgentEvent(listener: (event: DesktopEvent) => void) {
    return subscribeToChannel("desktop:event", listener);
  },
  onRuntimeState(listener: (state: RuntimeState) => void) {
    return subscribeToChannel("desktop:runtime-state", listener);
  },
};

contextBridge.exposeInMainWorld("desktop", desktopApi);
