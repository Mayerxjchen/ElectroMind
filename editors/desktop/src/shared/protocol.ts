export type AppInfo = {
    name: string;
    version: string;
    platform: string;
    userName: string;
};

export type ExecutionStatePayload = {
    mode: "local" | "sandbox" | "ssh" | null;
    resolved_backend: "local" | "docker" | "podman" | "ssh" | null;
    isolated: boolean;
    warning: string | null;
    diagnostics: Array<{ code: string; severity: string; message: string }>;
    thread_id?: string | null;
};

export type RuntimeState = {
    projectPath: string;
    activeHomePath: string;
    activeHomeScope: "user" | "project";
    currentThreadId?: string;
    sandboxBackend?: string;
    sandboxAlive?: boolean;
    yoloMode: boolean;
    bridgeActive: boolean;
    /** 当前后端传输：wire=本地 spawn 子进程，http=连远程 server。 */
    transport: "wire" | "http";
    status: "idle" | "starting" | "ready" | "error";
    lastError?: string;
    /** 执行模式状态（来自后端 ExecutionState 事件）。 */
    executionState?: ExecutionStatePayload;
};

export type ThreadSummary = {
    id: string;
    title: string;
    relativeTime: string;
    projectPath: string;
    sandboxBackend: string;
};

export type ThreadMeta = {
    id: string;
    title: string;
    createdAt: string;
    updatedAt: string;
    messageCount?: number;
    threadPath: string;
    metainfo: Record<string, unknown>;
};

export type ArtifactSummary = {
    id: string;
    name: string;
    path: string;
    size: number;
    mtimeMs: number;
};

export type FilePreview = {
    name: string;
    path: string;
    size: number;
    kind: "text" | "markdown" | "html" | "pdf" | "image" | "binary";
    language?: string;
    text?: string;
    dataUrl?: string;
    truncated?: boolean;
    reason?: string;
};

export type ArtifactPreview = {
    name: string;
    path: string;
    size: number;
    kind: "text" | "markdown" | "html" | "pdf" | "image" | "binary";
    language?: string;
    text?: string;
    dataUrl?: string;
    truncated?: boolean;
    reason?: string;
};

export type Skill = {
    name: string;
    description: string;
    path: string;
};

export type SkillStateItem = {
    name: string;
    description: string;
    source: string;
    sha256: string;
    status: "available" | "loaded" | "unavailable";
};

export type SkillDiagnosticPayload = {
    code: string;
    message: string;
    path: string;
    severity: "warning" | "error";
};

export type SkillsStatePayload = {
    thread_id: string;
    fingerprint: string;
    generation: number;
    digest: string;
    skills: SkillStateItem[];
    loaded: string[];
    loaded_this_run: string[];
    diagnostics: SkillDiagnosticPayload[];
};

export type SkillStateEvent = {
    type: "SkillState";
    generation: number;
    digest: string;
    thread_id: string;
    available: Array<{ name: string; description: string; source: string; sha256: string }>;
    loaded_this_run: string[];
    diagnostics: SkillDiagnosticPayload[];
    which: "init" | "prepare_turn" | "use_skill" | "reset" | "reconnect";
};

export type ExecutionContextDocument = {
    remote_path: string;
    sha256: string;
    size: number;
    fetched_at: number;
};

export type ExecutionContextStatePayload = {
    type: "ExecutionContextState";
    thread_id: string;
    target: string;
    profile_id: string;
    documents: ExecutionContextDocument[];
    diagnostics: SkillDiagnosticPayload[];
};

export type AppSettings = {
    path: string;
    exists: boolean;
    content: string;
};

export type SandboxStatus = {
    threadId: string;
    backend: string;
    alive: boolean;
    workdir: string;
};

/** 新建会话可选的 sandbox backend（与 wire / ThreadSpec 对齐）。 */
export type SandboxBackendOption = "local" | "container" | "docker" | "podman" | "ssh";

export type EnvironmentCheck = {
    uvInstalled: boolean;
    uvPath?: string;
    electromindInstalled: boolean;
    electromindPath?: string;
    apiKeyConfigured: boolean;
    dockerInstalled: boolean;
    podmanInstalled: boolean;
    containerRuntime?: "docker" | "podman";
    sandboxImage: string;
    sandboxImageExists: boolean;
    configPath: string;
    /** ~/.electromind 绝对路径 */
    dataHomePath: string;
    /** 展示用，例如 ~/.electromind */
    dataHomeLabel: string;
    /** 目录占用字节数；目录不存在时为 0；无法读取时为 undefined */
    dataHomeBytes?: number;
    /** 沙箱镜像占用字节数；无运行时或未安装镜像时为 undefined */
    sandboxImageBytes?: number;
};

export type OnboardingState = {
    completed: boolean;
    skipped: boolean;
    /** 未完成且未跳过时展示可选向导 */
    shouldShow: boolean;
    /**
     * 硬拦截：缺少 electromind CLI 或 API Key 时为 true。
     * 为 true 时主界面不可用，设置向导不可关闭/跳过。
     */
    blocked: boolean;
    preferredBackend: "local" | "container" | "ssh";
    environment: EnvironmentCheck;
};

export type ProviderSetupInput = {
    apiKey: string;
    model: string;
    baseUrl?: string;
};

export type ResetSessionOptions = {
    backend?: SandboxBackendOption;
    projectPath?: string;
    sshHost?: string;
    sshConfig?: string;
    sshWorkdir?: string;
    image?: string;
};

export type NewSessionOptions = {
    projectPath: string;
    availableBackends: SandboxBackendOption[];
    sshHosts: string[];
    /** 配置默认镜像（[sandbox].image 或 electromind:latest） */
    defaultImage: string;
    /** 本机可用的 electromind* 镜像（含 defaultImage） */
    availableImages: string[];
};

export type SandboxTreeNode = {
    id: string;
    label: string;
    kind: "dir" | "file";
    count?: number;
    children?: SandboxTreeNode[];
};

export type MentionSource = "project" | "sandbox";

export type MentionFile = {
    path: string;
    source: MentionSource;
};

export type WireEvent = {
    method: string;
    params: Record<string, unknown>;
};

export type DesktopEvent =
    | { type: "wireEvent"; event: WireEvent }
    | { type: "log"; text: string };

/**
 * Wire commands the Renderer may send directly.  Keep this list as the
 * ONLY surface available through sendWireCommand — anything else must
 * get its own typed API instead of a generic passthrough.
 */
export type WireCommand =
  | { cmd: "skills" }
  | { cmd: "cancel" }
  // G1: Plan / Artifact 领域状态命令（后端 harness protocol_v2 同名命令）
  | { cmd: "plan/state"; thread_id?: string }
  | { cmd: "plan/propose"; thread_id?: string; plan?: PlanState }
  | { cmd: "plan/approve"; thread_id?: string }
  | { cmd: "plan/revise"; thread_id?: string }
  | { cmd: "plan/cancel"; thread_id?: string }
  | { cmd: "artifact/state"; thread_id?: string }
  | { cmd: "artifact/register"; thread_id?: string; manifest?: ArtifactManifest }
  | { cmd: "artifact/accept"; thread_id?: string; artifact_id: string; who?: string }
  | { cmd: "artifact/reject"; thread_id?: string; artifact_id: string; reason?: string }
  | { cmd: "artifact/complete"; thread_id?: string; artifact_id: string }
  | { cmd: "artifact/validate"; thread_id?: string; artifact_id: string; parser: string };

// ── G1: Plan 领域状态（镜像后端 PlanState，见 execution/plan.py）─────

export type PlanEvidence = {
  kind: string;
  detail: string;
  sha256: string;
  exit_code: number | null;
  by: string;
  recorded_at: number;
};

export type PlanStepState = {
  id: string;
  title: string;
  description: string;
  files: string[];
  tools: string[];
  depends_on: string[];
  status: string;
  expected_artifacts: string[];
  effects: string[];
  verification: string[];
  evidence: PlanEvidence[];
  error: string;
  retry_policy: string;
  skipped_reason: string;
};

export type PlanState = {
  plan_id: string;
  version: number;
  status: string;
  objective: string;
  assumptions: string[];
  questions: string[];
  steps: PlanStepState[];
  risks: string[];
  verification: string[];
  created_at: number;
  approved_at: number | null;
  fingerprint: string;
};

// ── G1: Artifact Manifest（镜像后端 ArtifactManifest）──────────────

export type ArtifactManifest = {
  artifact_id: string;
  type: string;
  path: string;
  sha256: string;
  run_id: string;
  step_id: string;
  created_by: string;
  input_artifacts: string[];
  command: string;
  software: string;
  software_version: string;
  environment_digest: string;
  units: string;
  validation_status: string;
  acceptance_status: string;
  parser: string;
  created_at: number;
  scheduler: string;
  job_id: string;
};

export type DesktopApi = {
    getAppInfo(): Promise<AppInfo>;
    getRuntimeState(): Promise<RuntimeState>;
    setYoloMode(enabled: boolean): Promise<RuntimeState>;
    listThreads(): Promise<ThreadSummary[]>;
    getThreadMeta(threadId: string): Promise<ThreadMeta>;
    getSettings(): Promise<AppSettings>;
    openDocumentation(): Promise<void>;
    listArtifacts(): Promise<ArtifactSummary[]>;
    openArtifact(path: string): Promise<void>;
    readArtifact(path: string): Promise<ArtifactPreview>;
    getSandboxStatus(): Promise<SandboxStatus>;
    listSandboxTree(): Promise<SandboxTreeNode[]>;
    listProjectFiles(): Promise<string[]>;
    listProjectTree(): Promise<SandboxTreeNode[]>;
    selectProject(): Promise<RuntimeState>;
    pickDirectory(defaultPath?: string): Promise<string | null>;
    getNewSessionOptions(): Promise<NewSessionOptions>;
    getOnboardingState(): Promise<OnboardingState>;
    refreshEnvironmentCheck(): Promise<EnvironmentCheck>;
    installElectromindCli(): Promise<{ ok: boolean; error?: string; electromindPath?: string }>;
    saveProviderSetup(setup: ProviderSetupInput): Promise<string>;
    completeOnboarding(options?: { preferredBackend?: "local" | "container" | "ssh"; skipped?: boolean }): Promise<void>;
    resumeThread(threadId: string): Promise<void>;
    deleteThread(threadId: string): Promise<boolean>;
    sendUserInput(text: string, requestId?: string, delivery?: string, mode?: string): Promise<void>;
    clearLastError(): Promise<void>;
    resetSession(options?: ResetSessionOptions): Promise<void>;
    requestHistoryReplay(): Promise<void>;
    sendWireCommand(command: WireCommand): Promise<void>;
    permitToolCall(toolCallId: string, approvalId?: string, threadId?: string, runId?: string): Promise<void>;
    denyToolCall(toolCallId: string, reason?: string, approvalId?: string, threadId?: string, runId?: string): Promise<void>;
    onAgentEvent(listener: (event: DesktopEvent) => void): () => void;
    onRuntimeState(listener: (state: RuntimeState) => void): () => void;

    // ── File operations ────────────────────────────────────────────
    getFileMetadata(ref: FileRef): Promise<FileMetadata>;
    copyFilePath(ref: FileRef, format: PathFormat): Promise<void>;
    exportFile(ref: FileRef, suggestedName?: string): Promise<FileTransferResult>;
    revealInFinder(ref: FileRef): Promise<void>;

    // ── File operations not yet implemented in main ────────────────
    // These are optional so the typed DesktopApi contract is honest
    // about what preload actually exposes.  FileApi feature-detects
    // them at runtime and returns a clear unsupported result rather
    // than invoking an absent IPC channel.
    previewFile?(ref: FileRef): Promise<FilePreview>;
    importFiles?(target: FileRef, localPaths: string[]): Promise<FileTransferResult[]>;
    copyFileBetween?(
      source: FileRef,
      target: FileRef,
    ): Promise<FileTransferResult>;
    renameFile?(ref: FileRef, newName: string): Promise<FileRef>;
    deleteFile?(ref: FileRef): Promise<void>;
    showFileContextMenu?(ref: FileRef, anchor: { x: number; y: number }): Promise<void>;
};

// ── FileRef types ────────────────────────────────────────────────────

export type FileSource = "project" | "execution" | "artifact";

export type PathFormat = "name" | "relative" | "absolute" | "uri";

export type FileRef = {
  id: string;
  source: FileSource;
  executionKind?: "local" | "sandbox" | "ssh";
  threadId?: string;
  path: string;
  name: string;
  kind: "file" | "directory";
  size?: number;
  mtimeMs?: number;
  mimeType?: string;
  capabilities: FileCapabilities;
};

export type FileCapabilities = {
  preview: boolean;
  attach: boolean;
  copyPath: boolean;
  exportToLocal: boolean;
  copyToProject: boolean;
  copyToExecution: boolean;
  reveal: boolean;
  rename: boolean;
  delete: boolean;
};

export type FileMetadata = {
  ref: FileRef;
  exists: boolean;
  sha256?: string;
};

export type FileTransferResult = {
  ok: boolean;
  source: FileRef;
  target: FileRef;
  size: number;
  sha256?: string;
  error?: string;
};

declare global {
    interface Window {
        desktop: DesktopApi;
    }
}

export { };
