import { contextBridge, ipcRenderer } from "electron";
import type {
  DesktopApi,
  DesktopEvent,
  FileMetadata,
  FilePreview,
  FileRef,
  FileTransferResult,
  PathFormat,
  ResetSessionOptions,
  RuntimeState,
  WireCommand,
} from "../shared/protocol";

/** Wire commands the Renderer may send directly (capability boundary). */
const ALLOWED_WIRE_COMMANDS = new Set<string>([
  "skills",
  "cancel",
  // G1: Plan / Artifact 领域状态命令
  "plan/state",
  "plan/propose",
  "plan/approve",
  "plan/revise",
  "plan/cancel",
  "artifact/state",
  "artifact/register",
  "artifact/accept",
  "artifact/reject",
  "artifact/complete",
  "artifact/validate",
]);

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
  /** P4.4: 一键打开日志目录。 */
  openLogDir() {
    return ipcRenderer.invoke("desktop:open-log-dir");
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
  getOnboardingState() {
    return ipcRenderer.invoke("desktop:get-onboarding-state");
  },
  refreshEnvironmentCheck() {
    return ipcRenderer.invoke("desktop:refresh-environment-check");
  },
  installElectromindCli() {
    return ipcRenderer.invoke("desktop:install-electromind-cli");
  },
  saveProviderSetup(setup) {
    return ipcRenderer.invoke("desktop:save-provider-setup", setup);
  },
  completeOnboarding(options) {
    return ipcRenderer.invoke("desktop:complete-onboarding", options);
  },
  resumeThread(threadId: string) {
    return ipcRenderer.invoke("desktop:resume-thread", threadId);
  },
  forceReconnect() {
    return ipcRenderer.invoke("desktop:force-reconnect");
  },
  deleteThread(threadId: string) {
    return ipcRenderer.invoke("desktop:delete-thread", threadId);
  },
  sendUserInput(text: string, requestId?: string, delivery?: string, mode?: string) {
    return ipcRenderer.invoke("desktop:send-user-input", text, requestId, delivery, mode);
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
  sendWireCommand(command: WireCommand) {
    // Capability boundary: only allowlist commands may cross the bridge.
    if (!ALLOWED_WIRE_COMMANDS.has(command.cmd)) {
      return Promise.reject(
        new Error(`wire command not allowed: ${String(command.cmd)}`),
      );
    }
    return ipcRenderer.invoke("desktop:send-wire-command", command);
  },
  permitToolCall(toolCallId: string, approvalId?: string, threadId?: string, runId?: string) {
    return ipcRenderer.invoke("desktop:permit-tool-call", { toolCallId, approvalId, threadId, runId });
  },
  denyToolCall(toolCallId: string, reason?: string, approvalId?: string, threadId?: string, runId?: string) {
    return ipcRenderer.invoke("desktop:deny-tool-call", { toolCallId, reason, approvalId, threadId, runId });
  },
  onAgentEvent(listener: (event: DesktopEvent) => void) {
    return subscribeToChannel("desktop:event", listener);
  },
  onRuntimeState(listener: (state: RuntimeState) => void) {
    return subscribeToChannel("desktop:runtime-state", listener);
  },

  // ── File operations ────────────────────────────────────────────

  getFileMetadata(ref: FileRef): Promise<FileMetadata> {
    return ipcRenderer.invoke("desktop:get-file-metadata", ref);
  },
  previewFile(ref: FileRef): Promise<FilePreview> {
    return ipcRenderer.invoke("desktop:preview-file", ref);
  },
  copyFilePath(ref: FileRef, format: PathFormat): Promise<void> {
    return ipcRenderer.invoke("desktop:copy-file-path", ref, format);
  },
  exportFile(ref: FileRef, suggestedName?: string): Promise<FileTransferResult> {
    return ipcRenderer.invoke("desktop:export-file", ref, suggestedName);
  },
  revealInFinder(ref: FileRef): Promise<void> {
    return ipcRenderer.invoke("desktop:reveal-in-finder", ref);
  },
};

contextBridge.exposeInMainWorld("desktop", desktopApi);
