export type AppInfo = {
    name: string;
    version: string;
    platform: string;
    userName: string;
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
    status: "idle" | "starting" | "ready" | "error";
    lastError?: string;
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
    resumeThread(threadId: string): Promise<void>;
    deleteThread(threadId: string): Promise<void>;
    sendUserInput(text: string): Promise<void>;
    clearLastError(): Promise<void>;
    resetSession(options?: ResetSessionOptions): Promise<void>;
    requestHistoryReplay(): Promise<void>;
    sendWireCommand(command: Record<string, unknown>): Promise<void>;
    permitToolCall(toolCallId: string): Promise<void>;
    denyToolCall(toolCallId: string, reason?: string): Promise<void>;
    onAgentEvent(listener: (event: DesktopEvent) => void): () => void;
    onRuntimeState(listener: (state: RuntimeState) => void): () => void;
};

declare global {
    interface Window {
        desktop: DesktopApi;
    }
}

export { };
