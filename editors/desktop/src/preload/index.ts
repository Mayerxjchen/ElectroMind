import { contextBridge, ipcRenderer } from "electron";
import { validateIpcParams } from "./ipc-schema";
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
  // 七: Desktop Skills Manager（用户显式操作；模型不可触发）
  "skills/reload",
  "skills/install",
  "skills/update",
  "skills/remove",
  "skills/trust",
]);

function invoke<T>(channel: string, ...args: unknown[]): Promise<T> {
  validateIpcParams(channel, args);
  return ipcRenderer.invoke(channel, ...args);
}

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
    return invoke("desktop:get-app-info");
  },
  getRuntimeState() {
    return invoke("desktop:get-runtime-state");
  },
  setYoloMode(enabled: boolean) {
    return invoke("desktop:set-yolo-mode", enabled);
  },
  listThreads() {
    return invoke("desktop:list-threads");
  },
  getThreadMeta(threadId: string) {
    return invoke("desktop:get-thread-meta", threadId);
  },
  getSettings() {
    return invoke("desktop:get-settings");
  },
  openDocumentation() {
    return invoke("desktop:open-documentation");
  },
  listArtifacts() {
    return invoke("desktop:list-artifacts");
  },
  openArtifact(path: string) {
    return invoke("desktop:open-artifact", path);
  },
  /** P4.4: 一键打开日志目录。 */
  openLogDir() {
    return invoke("desktop:open-log-dir");
  },
  readArtifact(path: string) {
    return invoke("desktop:read-artifact", path);
  },
  getSandboxStatus() {
    return invoke("desktop:get-sandbox-status");
  },
  listSandboxTree() {
    return invoke("desktop:list-sandbox-tree");
  },
  listProjectFiles() {
    return invoke("desktop:list-project-files");
  },
  listProjectTree() {
    return invoke("desktop:list-project-tree");
  },
  selectProject() {
    return invoke("desktop:select-project");
  },
  pickDirectory(defaultPath?: string) {
    return invoke("desktop:pick-directory", defaultPath);
  },
  getNewSessionOptions() {
    return invoke("desktop:get-new-session-options");
  },
  getOnboardingState() {
    return invoke("desktop:get-onboarding-state");
  },
  refreshEnvironmentCheck() {
    return invoke("desktop:refresh-environment-check");
  },
  installElectromindCli() {
    return invoke("desktop:install-electromind-cli");
  },
  saveProviderSetup(setup) {
    return invoke("desktop:save-provider-setup", setup);
  },
  completeOnboarding(options) {
    return invoke("desktop:complete-onboarding", options);
  },
  resumeThread(threadId: string) {
    return invoke("desktop:resume-thread", threadId);
  },
  forceReconnect() {
    return invoke("desktop:force-reconnect");
  },
  deleteThread(threadId: string) {
    return invoke("desktop:delete-thread", threadId);
  },
  sendUserInput(text: string, requestId?: string, delivery?: string, mode?: string, model?: string, skill?: string) {
    return invoke("desktop:send-user-input", text, requestId, delivery, mode, model, skill);
  },
  clearLastError() {
    return invoke("desktop:clear-last-error");
  },
  resetSession(options?: ResetSessionOptions) {
    return invoke("desktop:reset-session", options);
  },
  requestHistoryReplay() {
    return invoke("desktop:request-history");
  },
  sendWireCommand(command: WireCommand) {
    // Capability boundary: only allowlist commands may cross the bridge.
    if (!ALLOWED_WIRE_COMMANDS.has(command.cmd)) {
      return Promise.reject(
        new Error(`wire command not allowed: ${String(command.cmd)}`),
      );
    }
    return invoke("desktop:send-wire-command", command);
  },
  permitToolCall(toolCallId: string, approvalId?: string, threadId?: string, runId?: string) {
    return invoke("desktop:permit-tool-call", { toolCallId, approvalId, threadId, runId });
  },
  denyToolCall(toolCallId: string, reason?: string, approvalId?: string, threadId?: string, runId?: string) {
    return invoke("desktop:deny-tool-call", { toolCallId, reason, approvalId, threadId, runId });
  },
  onAgentEvent(listener: (event: DesktopEvent) => void) {
    return subscribeToChannel("desktop:event", listener);
  },
  onRuntimeState(listener: (state: RuntimeState) => void) {
    return subscribeToChannel("desktop:runtime-state", listener);
  },

  // ── File operations ────────────────────────────────────────────

  getFileMetadata(ref: FileRef): Promise<FileMetadata> {
    return invoke("desktop:get-file-metadata", ref);
  },
  previewFile(ref: FileRef): Promise<FilePreview> {
    return invoke("desktop:preview-file", ref);
  },
  copyFilePath(ref: FileRef, format: PathFormat): Promise<void> {
    return invoke("desktop:copy-file-path", ref, format);
  },
  exportFile(ref: FileRef, suggestedName?: string): Promise<FileTransferResult> {
    return invoke("desktop:export-file", ref, suggestedName);
  },
  revealInFinder(ref: FileRef): Promise<void> {
    return invoke("desktop:reveal-in-finder", ref);
  },
};

contextBridge.exposeInMainWorld("desktop", desktopApi);
