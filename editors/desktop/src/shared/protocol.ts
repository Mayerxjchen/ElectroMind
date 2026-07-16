export type AppInfo = {
    name: string;
    version: string;
    platform: string;
};

export type RuntimeState = {
    projectPath: string;
    activeHomePath: string;
    activeHomeScope: "user" | "project";
    currentThreadId?: string;
    sandboxBackend?: string;
    sandboxAlive?: boolean;
    bridgeActive: boolean;
    status: "idle" | "starting" | "ready" | "error";
    lastError?: string;
};

export type ThreadSummary = {
    id: string;
    title: string;
    relativeTime: string;
    projectPath: string;
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

export type SandboxStatus = {
    threadId: string;
    backend: string;
    alive: boolean;
    workdir: string;
};

export type SandboxTreeNode = {
    id: string;
    label: string;
    kind: "dir" | "file";
    count?: number;
    children?: SandboxTreeNode[];
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
    listThreads(): Promise<ThreadSummary[]>;
    getThreadMeta(threadId: string): Promise<ThreadMeta>;
    listArtifacts(): Promise<ArtifactSummary[]>;
    openArtifact(path: string): Promise<void>;
    getSandboxStatus(): Promise<SandboxStatus>;
    listSandboxTree(): Promise<SandboxTreeNode[]>;
    selectProject(): Promise<RuntimeState>;
    resumeThread(threadId: string): Promise<void>;
    sendUserInput(text: string): Promise<void>;
    resetSession(): Promise<void>;
    requestHistoryReplay(): Promise<void>;
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
