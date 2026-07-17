import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  nativeImage,
  shell,
  type OpenDialogOptions,
} from "electron";
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync } from "node:fs";
import type { Dirent } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";

import { AgentBridge, resolvePagentWireInvocation } from "../shared/agent";
import type {
  AppInfo,
  AppSettings,
  ArtifactPreview,
  ArtifactSummary,
  DesktopEvent,
  RuntimeState,
  SandboxStatus,
  SandboxTreeNode,
  ThreadMeta,
  ThreadSummary,
  WireEvent,
} from "../shared/protocol";
import { parseWireLine } from "../shared/wire";

type ThreadListEntry = {
  id: string;
  title: string;
  projectPath: string;
  sandboxBackend: string;
};
type ThreadListPayload = {
  home: string;
  threads_root: string;
  threads: ThreadListEntry[];
};
type SandboxTreePayload = {
  thread_id: string;
  workdir: string;
  nodes: SandboxTreeNode[];
};
type SandboxStatusPayload = {
  thread_id: string;
  backend: string;
  alive: boolean;
  workdir: string;
};
type SandboxTreeWaiter = {
  threadId: string;
  resolve: (payload: SandboxTreePayload) => void;
};
type SandboxStatusWaiter = {
  threadId: string;
  resolve: (payload: SandboxStatusPayload) => void;
};

let mainWindow: BrowserWindow | undefined;
let bridge: AgentBridge | undefined;
let projectPath: string = defaultProjectPath();
let currentThreadId = "";
let bridgeStatus: RuntimeState["status"] = "idle";
let lastError = "";
let recentStderr = "";
let sandboxStatus: SandboxStatusPayload = {
  thread_id: "",
  backend: "",
  alive: false,
  workdir: "",
};
let threadListWaiters: Array<(payload: ThreadListPayload) => void> = [];
let sandboxTreeWaiters: SandboxTreeWaiter[] = [];
let sandboxStatusWaiters: SandboxStatusWaiter[] = [];
const DOCUMENTATION_URL = "https://synclionpaw.github.io/pagent/";

/** dock/about 用带透明边距的高清图标（符合 macOS 图标网格，避免视觉偏大）。 */
function appIconPngPath(): string {
  const padded = path.join(__dirname, "..", "assets", "app-icon.png");
  if (existsSync(padded)) {
    return padded;
  }
  return path.join(__dirname, "..", "assets", "logo-icon.png");
}

function appIconPath(): string {
  if (process.platform === "darwin") {
    const icns = path.join(__dirname, "..", "assets", "icon.icns");
    if (existsSync(icns)) {
      return icns;
    }
  }
  return appIconPngPath();
}

function applyAppIcon(): void {
  const png = appIconPngPath();
  if (!existsSync(png)) {
    return;
  }
  const image = nativeImage.createFromPath(png);
  if (image.isEmpty()) {
    return;
  }
  if (process.platform === "darwin") {
    app.dock?.setIcon(image);
  }
  app.setAboutPanelOptions({
    applicationName: "pagent Desktop",
    iconPath: png,
  });
}

function userPagentHome(): string {
  return path.join(homedir(), ".pagent");
}

/** 桌面默认用户 project（host_root）；agent 沙箱仍是 thread/workspace。 */
function defaultProjectPath(): string {
  return path.join(userPagentHome(), "default");
}

function ensureProjectDirectory(): void {
  mkdirSync(projectPath, { recursive: true });
}

function activeHomePath(): string {
  return userPagentHome();
}

function activeHomeScope(): "user" | "project" {
  return "user";
}

function bridgeWorkingDirectory(): string {
  return projectPath;
}

function setProjectPath(nextProjectPath: string): void {
  projectPath = nextProjectPath;
  ensureProjectDirectory();
}

function artifactsDirectory(): string {
  return path.join(projectPath, "artifacts");
}

function settingsFilePath(): string {
  return path.join(userPagentHome(), "pagent.toml");
}

function threadsDirectory(): string {
  return path.join(userPagentHome(), "threads");
}

function pagentProjectRoot(): string {
  return path.join(__dirname, "..", "..", "..");
}

function configureAppRuntimePaths(): void {
  const runtimeRoot = path.join(__dirname, "..", ".runtime");
  app.setPath("userData", path.join(runtimeRoot, "user-data"));
  app.setPath("sessionData", path.join(runtimeRoot, "session-data"));
  app.disableHardwareAcceleration();
}

function appInfo(): AppInfo {
  const homeDir = app.getPath("home");
  const userName = path.basename(homeDir);
  return {
    name: app.getName(),
    version: app.getVersion(),
    platform: process.platform,
    userName,
  };
}

function readAppSettings(): AppSettings {
  const filePath = settingsFilePath();
  if (!existsSync(filePath)) {
    return {
      path: filePath,
      exists: false,
      content: "",
    };
  }
  return {
    path: filePath,
    exists: true,
    content: readFileSync(filePath, "utf8"),
  };
}

function runtimeState(): RuntimeState {
  return {
    projectPath,
    activeHomePath: activeHomePath(),
    activeHomeScope: activeHomeScope(),
    currentThreadId,
    sandboxBackend:
      sandboxStatus.thread_id === currentThreadId
        ? sandboxStatus.backend || undefined
        : undefined,
    sandboxAlive:
      sandboxStatus.thread_id === currentThreadId ? sandboxStatus.alive : undefined,
    bridgeActive: bridge !== undefined,
    status: bridgeStatus,
    lastError: lastError || undefined,
  };
}

function readString(params: Record<string, unknown>, key: string): string {
  const value = params[key];
  return typeof value === "string" ? value : "";
}

function normalizeThreadList(params: Record<string, unknown>): ThreadListPayload {
  const threadsRaw = Array.isArray(params.threads) ? params.threads : [];
  const threads: ThreadListEntry[] = [];
  for (const item of threadsRaw) {
    if (typeof item !== "object" || item === null) {
      continue;
    }
    const record = item as Record<string, unknown>;
    const id = typeof record.id === "string" ? record.id : "";
    if (!id) {
      continue;
    }
    threads.push({
      id,
      title: typeof record.title === "string" ? record.title : "",
      projectPath:
        typeof record.project_path === "string" ? record.project_path : "",
      sandboxBackend:
        typeof record.backend === "string" ? record.backend : "local",
    });
  }
  return {
    home: typeof params.home === "string" ? params.home : "",
    threads_root:
      typeof params.threads_root === "string" ? params.threads_root : "",
    threads,
  };
}

function normalizeSandboxTree(
  params: Record<string, unknown>,
): SandboxTreePayload {
  return {
    thread_id: typeof params.thread_id === "string" ? params.thread_id : "",
    workdir: typeof params.workdir === "string" ? params.workdir : "",
    nodes: Array.isArray(params.nodes) ? (params.nodes as SandboxTreeNode[]) : [],
  };
}

function normalizeSandboxStatus(
  params: Record<string, unknown>,
): SandboxStatusPayload {
  return {
    thread_id: typeof params.thread_id === "string" ? params.thread_id : "",
    backend: typeof params.backend === "string" ? params.backend : "",
    alive: params.alive === true,
    workdir: typeof params.workdir === "string" ? params.workdir : "",
  };
}

function parseThreadTimestamp(threadId: string): Date | undefined {
  const match =
    /^thread-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$/.exec(threadId);
  if (!match) {
    return undefined;
  }
  const [, year, month, day, hour, minute, second] = match;
  return new Date(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour),
    Number(minute),
    Number(second),
  );
}

function formatRelativeTime(date: Date | undefined): string {
  if (!date) {
    return "";
  }
  const diffMs = Date.now() - date.getTime();
  const diffSeconds = Math.max(0, Math.floor(diffMs / 1000));
  if (diffSeconds < 60) {
    return "刚刚";
  }
  if (diffSeconds < 3600) {
    return `${Math.floor(diffSeconds / 60)} 分钟前`;
  }
  if (diffSeconds < 86_400) {
    return `${Math.floor(diffSeconds / 3600)} 小时前`;
  }
  if (diffSeconds < 172_800) {
    return "昨天";
  }
  if (diffSeconds < 604_800) {
    return `${Math.floor(diffSeconds / 86_400)} 天前`;
  }
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  const currentYear = new Date().getFullYear();
  if (year === currentYear) {
    return `${month}-${day}`;
  }
  return `${year}-${month}-${day}`;
}

function toThreadSummaries(payload: ThreadListPayload): ThreadSummary[] {
  return payload.threads.map((entry) => ({
    id: entry.id,
    title: entry.title.trim() || "新建任务",
    relativeTime: formatRelativeTime(parseThreadTimestamp(entry.id)),
    projectPath: entry.projectPath,
    sandboxBackend: entry.sandboxBackend,
  }));
}

function isValidThreadId(threadId: string): boolean {
  return /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(threadId);
}

function readJsonRecord(filePath: string): Record<string, unknown> {
  if (!existsSync(filePath)) {
    return {};
  }
  try {
    const value = JSON.parse(readFileSync(filePath, "utf8")) as unknown;
    if (typeof value === "object" && value !== null && !Array.isArray(value)) {
      return value as Record<string, unknown>;
    }
  } catch {
    return {};
  }
  return {};
}

function readOptionalString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  return typeof value === "string" ? value : "";
}

function readThreadMeta(threadId: string): ThreadMeta {
  if (!isValidThreadId(threadId)) {
    throw new Error("invalid thread id");
  }
  const threadPath = path.join(threadsDirectory(), threadId);
  const meta = readJsonRecord(path.join(threadPath, "metainfo.json"));
  const messageCount = meta.message_count;
  return {
    id: threadId,
    title: readOptionalString(meta, "title"),
    createdAt: readOptionalString(meta, "created_at"),
    updatedAt: readOptionalString(meta, "updated_at"),
    messageCount: typeof messageCount === "number" ? messageCount : undefined,
    threadPath,
    metainfo: meta,
  };
}

function listProjectArtifacts(): ArtifactSummary[] {
  const root = artifactsDirectory();
  if (!existsSync(root)) {
    return [];
  }
  return readdirSync(root, { withFileTypes: true })
    .filter((entry) => entry.isFile())
    .map((entry) => {
      const filePath = path.join(root, entry.name);
      const stat = statSync(filePath);
      return {
        id: entry.name,
        name: entry.name,
        path: filePath,
        size: stat.size,
        mtimeMs: stat.mtimeMs,
      };
    })
    .sort((a, b) => b.mtimeMs - a.mtimeMs);
}

function resolveArtifactPath(filePath: string): string | undefined {
  const root = path.resolve(artifactsDirectory());
  const target = path.resolve(filePath);
  const relative = path.relative(root, target);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    return undefined;
  }
  return existsSync(target) ? target : undefined;
}

const ARTIFACT_TEXT_LIMIT = 512 * 1024;
const ARTIFACT_IMAGE_LIMIT = 8 * 1024 * 1024;
const ARTIFACT_HTML_LIMIT = 4 * 1024 * 1024;
const ARTIFACT_PDF_LIMIT = 32 * 1024 * 1024;

const ARTIFACT_LANGUAGES: Record<string, string> = {
  ".ts": "typescript",
  ".tsx": "tsx",
  ".js": "javascript",
  ".jsx": "jsx",
  ".mjs": "javascript",
  ".cjs": "javascript",
  ".py": "python",
  ".sh": "bash",
  ".rb": "ruby",
  ".go": "go",
  ".rs": "rust",
  ".java": "java",
  ".c": "c",
  ".h": "c",
  ".cpp": "cpp",
  ".css": "css",
  ".scss": "scss",
  ".html": "html",
  ".htm": "html",
  ".xml": "xml",
  ".json": "json",
  ".yaml": "yaml",
  ".yml": "yaml",
  ".toml": "toml",
  ".md": "markdown",
  ".sql": "sql",
};

const ARTIFACT_IMAGE_MIME: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".svg": "image/svg+xml",
  ".bmp": "image/bmp",
};

const ARTIFACT_TEXT_EXT = new Set([
  ".txt",
  ".log",
  ".csv",
  ".tsv",
  ".env",
  ".ini",
  ".cfg",
  ".conf",
]);

/** 读取 artifact 内容供右侧面板内联预览：markdown/html/pdf 富渲染，代码/文本高亮，图片转 data URL，其余标记为二进制。 */
function readArtifactPreview(filePath: string): ArtifactPreview {
  const target = resolveArtifactPath(filePath);
  const name = path.basename(filePath);
  if (!target) {
    return { name, path: filePath, size: 0, kind: "binary", reason: "文件不存在" };
  }
  const stat = statSync(target);
  const ext = path.extname(target).toLowerCase();
  const base = { name: path.basename(target), path: target, size: stat.size };

  const imageMime = ARTIFACT_IMAGE_MIME[ext];
  if (imageMime) {
    if (stat.size > ARTIFACT_IMAGE_LIMIT) {
      return { ...base, kind: "binary", reason: "图片过大，无法内联预览" };
    }
    const buffer = readFileSync(target);
    return { ...base, kind: "image", dataUrl: `data:${imageMime};base64,${buffer.toString("base64")}` };
  }

  if (ext === ".pdf") {
    if (stat.size > ARTIFACT_PDF_LIMIT) {
      return { ...base, kind: "binary", reason: "PDF 过大，无法内联预览" };
    }
    const buffer = readFileSync(target);
    return { ...base, kind: "pdf", dataUrl: `data:application/pdf;base64,${buffer.toString("base64")}` };
  }

  if (ext === ".html" || ext === ".htm") {
    if (stat.size > ARTIFACT_HTML_LIMIT) {
      return { ...base, kind: "binary", reason: "HTML 过大，无法内联预览" };
    }
    const buffer = readFileSync(target);
    return { ...base, kind: "html", dataUrl: `data:text/html;base64,${buffer.toString("base64")}` };
  }

  const known = ext in ARTIFACT_LANGUAGES || ARTIFACT_TEXT_EXT.has(ext);
  const buffer = readFileSync(target, { flag: "r" });
  const slice = buffer.subarray(0, ARTIFACT_TEXT_LIMIT);
  if (!known && slice.includes(0)) {
    return { ...base, kind: "binary", reason: "二进制文件，无法内联预览" };
  }
  const text = slice.toString("utf8");
  const truncated = stat.size > ARTIFACT_TEXT_LIMIT;
  if (ext === ".md" || ext === ".markdown") {
    return { ...base, kind: "markdown", text, truncated };
  }
  return {
    ...base,
    kind: "text",
    language: ARTIFACT_LANGUAGES[ext],
    text,
    truncated,
  };
}

const PROJECT_FILE_IGNORE = new Set([
  ".git",
  "node_modules",
  ".venv",
  "__pycache__",
  ".DS_Store",
  "dist",
  "build",
  ".idea",
  ".vscode",
]);
const PROJECT_FILE_LIMIT = 2000;

/** 扁平列出 project 目录下的相对路径，供 @ 引用补全。忽略常见的重目录。 */
function listProjectFiles(): string[] {
  const root = projectPath;
  if (!existsSync(root)) {
    return [];
  }
  const results: string[] = [];
  const walk = (dir: string): void => {
    if (results.length >= PROJECT_FILE_LIMIT) {
      return;
    }
    let entries: Dirent[];
    try {
      entries = readdirSync(dir, { withFileTypes: true }) as Dirent[];
    } catch {
      return;
    }
    for (const entry of entries) {
      if (results.length >= PROJECT_FILE_LIMIT) {
        return;
      }
      if (entry.name.startsWith(".") && entry.name !== ".pagent") {
        continue;
      }
      if (PROJECT_FILE_IGNORE.has(entry.name)) {
        continue;
      }
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
        continue;
      }
      if (entry.isFile()) {
        results.push(path.relative(root, full));
      }
    }
  };
  walk(root);
  return results.sort((a, b) => a.localeCompare(b));
}

function postDesktopEvent(event: DesktopEvent): void {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  mainWindow.webContents.send("desktop:event", event);
}

function postWireEvent(event: WireEvent): void {
  postDesktopEvent({ type: "wireEvent", event });
}

function postSyntheticHistoryReplay(): void {
  postWireEvent({
    method: "HistoryReplay",
    params: { thread_id: "", title: "", messages: [] },
  });
}

function notifyRuntimeState(): void {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  mainWindow.webContents.send("desktop:runtime-state", runtimeState());
}

function reportBridgeFailure(message: string, where: string): void {
  bridge = undefined;
  bridgeStatus = "error";
  lastError = message;
  notifyRuntimeState();
  postWireEvent({
    method: "Error",
    params: { message, where },
  });
}

function handleWireLine(line: string): void {
  const event = parseWireLine(line);
  if (!event) {
    postDesktopEvent({ type: "log", text: `[wire] skip invalid line: ${line}` });
    return;
  }
  if (event.method === "ThreadList") {
    const payload = normalizeThreadList(event.params);
    const waiters = threadListWaiters.splice(0);
    for (const waiter of waiters) {
      waiter(payload);
    }
    return;
  }
  if (event.method === "SandboxTree") {
    const payload = normalizeSandboxTree(event.params);
    const matched = sandboxTreeWaiters.filter(
      (waiter) => waiter.threadId === payload.thread_id,
    );
    sandboxTreeWaiters = sandboxTreeWaiters.filter(
      (waiter) => waiter.threadId !== payload.thread_id,
    );
    for (const waiter of matched) {
      waiter.resolve(payload);
    }
    return;
  }
  if (event.method === "SandboxStatus") {
    const payload = normalizeSandboxStatus(event.params);
    sandboxStatus = payload;
    notifyRuntimeState();
    const matched = sandboxStatusWaiters.filter(
      (waiter) => waiter.threadId === payload.thread_id,
    );
    sandboxStatusWaiters = sandboxStatusWaiters.filter(
      (waiter) => waiter.threadId !== payload.thread_id,
    );
    for (const waiter of matched) {
      waiter.resolve(payload);
    }
    return;
  }
  if (event.method === "CurrentThread" || event.method === "HistoryReplay") {
    currentThreadId = readString(event.params, "thread_id");
    const nextProjectPath = readString(event.params, "project_path");
    if (nextProjectPath) {
      setProjectPath(nextProjectPath);
    }
    notifyRuntimeState();
  }
  if (event.method === "Error") {
    lastError = readString(event.params, "message");
    notifyRuntimeState();
  }
  postWireEvent(event);
}

function disposeBridge(): void {
  bridge?.stop();
  bridge = undefined;
  bridgeStatus = "idle";
  recentStderr = "";
  sandboxStatus = { thread_id: "", backend: "", alive: false, workdir: "" };
}

function ensureBridge(): AgentBridge | undefined {
  if (bridge) {
    return bridge;
  }

  bridgeStatus = "starting";
  lastError = "";
  ensureProjectDirectory();
  notifyRuntimeState();

  const wireInvocation = resolvePagentWireInvocation(pagentProjectRoot());
  const nextBridge = new AgentBridge({
    command: wireInvocation.command,
    args: wireInvocation.args,
    cwd: bridgeWorkingDirectory(),
    env: { PAGENT_HOME: userPagentHome() },
    onLine: handleWireLine,
    onStderr: (text) => {
      recentStderr = (recentStderr + text).slice(-4000);
      postDesktopEvent({ type: "log", text });
    },
    onExit: (code) => {
      const detail = code === null ? "子进程已退出。" : `子进程已退出，code=${code}。`;
      const extra = recentStderr.trim();
      reportBridgeFailure(extra ? `${detail}\n${extra}` : detail, "bridge");
    },
    onError: (error) => {
      reportBridgeFailure(error.message, "spawn");
    },
  });

  bridge = nextBridge;
  bridgeStatus = "ready";
  notifyRuntimeState();
  nextBridge.start();
  nextBridge.send({ cmd: "commands" });
  return nextBridge;
}

function requestThreadList(): Promise<ThreadListPayload> {
  return new Promise((resolvePromise, reject) => {
    const activeBridge = ensureBridge();
    if (!activeBridge) {
      reject(new Error("bridge unavailable"));
      return;
    }
    const timer = setTimeout(() => {
      const index = threadListWaiters.indexOf(onList);
      if (index >= 0) {
        threadListWaiters.splice(index, 1);
      }
      reject(new Error("list_threads timeout"));
    }, 10_000);
    const onList = (payload: ThreadListPayload) => {
      clearTimeout(timer);
      resolvePromise(payload);
    };
    threadListWaiters.push(onList);
    activeBridge.send({ cmd: "list_threads", project_path: projectPath });
  });
}

async function restoreHistory(): Promise<void> {
  const activeBridge = ensureBridge();
  if (!activeBridge) {
    return;
  }
  if (currentThreadId) {
    activeBridge.send({
      cmd: "resume",
      thread_id: currentThreadId,
      project_path: projectPath,
    });
    return;
  }
  try {
    const payload = await requestThreadList();
    const latest = payload.threads[0];
    if (!latest) {
      postSyntheticHistoryReplay();
      return;
    }
    activeBridge.send({
      cmd: "resume",
      thread_id: latest.id,
      project_path: projectPath,
    });
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    postDesktopEvent({ type: "log", text: `[history] ${detail}` });
    postSyntheticHistoryReplay();
  }
}

function requestSandboxTree(): Promise<SandboxTreePayload> {
  return new Promise((resolvePromise, reject) => {
    if (!bridge || !currentThreadId) {
      resolvePromise({ thread_id: "", workdir: "", nodes: [] });
      return;
    }
    const targetThreadId = currentThreadId;
    const timer = setTimeout(() => {
      const index = sandboxTreeWaiters.indexOf(waiter);
      if (index >= 0) {
        sandboxTreeWaiters.splice(index, 1);
      }
      reject(new Error("sandbox_tree timeout"));
    }, 10_000);
    const onTree = (payload: SandboxTreePayload) => {
      clearTimeout(timer);
      resolvePromise(payload);
    };
    const waiter: SandboxTreeWaiter = {
      threadId: targetThreadId,
      resolve: onTree,
    };
    sandboxTreeWaiters.push(waiter);
    bridge.send({ cmd: "sandbox_tree" });
  });
}

function requestSandboxStatus(): Promise<SandboxStatusPayload> {
  return new Promise((resolvePromise) => {
    if (!bridge || !currentThreadId) {
      resolvePromise({ thread_id: "", backend: "", alive: false, workdir: "" });
      return;
    }
    const targetThreadId = currentThreadId;
    const fallbackStatus =
      sandboxStatus.thread_id === targetThreadId
        ? sandboxStatus
        : {
          thread_id: targetThreadId,
          backend: "",
          alive: false,
          workdir: "",
        };
    const timer = setTimeout(() => {
      const index = sandboxStatusWaiters.indexOf(waiter);
      if (index >= 0) {
        sandboxStatusWaiters.splice(index, 1);
      }
      postDesktopEvent({
        type: "log",
        text: "[sandbox] sandbox_status timeout; using cached status",
      });
      resolvePromise(fallbackStatus);
    }, 10_000);
    const onStatus = (payload: SandboxStatusPayload) => {
      clearTimeout(timer);
      resolvePromise(payload);
    };
    const waiter: SandboxStatusWaiter = {
      threadId: targetThreadId,
      resolve: onStatus,
    };
    sandboxStatusWaiters.push(waiter);
    bridge.send({ cmd: "sandbox_status" });
  });
}

function createWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 1360,
    height: 900,
    minWidth: 1100,
    minHeight: 720,
    title: "pagent Desktop",
    backgroundColor: "#0f1115",
    icon: appIconPath(),
    ...(process.platform === "darwin"
      ? {
        titleBarStyle: "hiddenInset" as const,
        trafficLightPosition: { x: 16, y: 14 },
      }
      : {}),
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      plugins: true,
    },
  });

  window.loadFile(path.join(__dirname, "index.html"));
  window.webContents.once("did-finish-load", () => {
    notifyRuntimeState();
  });
  return window;
}

function hideAppDuringQuit(): void {
  for (const window of BrowserWindow.getAllWindows()) {
    window.hide();
  }
  if (process.platform === "darwin") {
    app.dock?.hide();
  }
}

app.whenReady().then(() => {
  app.setName("pagent Desktop");
  applyAppIcon();
  mainWindow = createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length > 0) {
      return;
    }
    mainWindow = createWindow();
  });
});

configureAppRuntimePaths();

app.on("window-all-closed", () => {
  disposeBridge();
  if (process.platform === "darwin") {
    return;
  }
  app.quit();
});

// 退出时先隐藏 dock 图标，避免 dev 模式下 dock 短暂回退到默认 Electron 图标而“闪一下”。
app.on("before-quit", () => {
  hideAppDuringQuit();
  disposeBridge();
});

app.on("will-quit", () => {
  hideAppDuringQuit();
});

ipcMain.handle("desktop:get-app-info", async () => appInfo());
ipcMain.handle("desktop:get-runtime-state", async () => runtimeState());
ipcMain.handle("desktop:list-threads", async () => {
  const payload = await requestThreadList();
  return toThreadSummaries(payload);
});
ipcMain.handle("desktop:get-thread-meta", async (_event, threadId: string) => {
  return readThreadMeta(threadId);
});
ipcMain.handle("desktop:get-settings", async () => readAppSettings());
ipcMain.handle("desktop:open-documentation", async () => {
  await shell.openExternal(DOCUMENTATION_URL);
});
ipcMain.handle("desktop:list-artifacts", async () => listProjectArtifacts());
ipcMain.handle("desktop:open-artifact", async (_event, filePath: string) => {
  const target = resolveArtifactPath(filePath);
  if (!target) {
    return;
  }
  shell.showItemInFolder(target);
});
ipcMain.handle("desktop:read-artifact", async (_event, filePath: string): Promise<ArtifactPreview> => {
  return readArtifactPreview(filePath);
});
ipcMain.handle("desktop:get-sandbox-status", async (): Promise<SandboxStatus> => {
  const payload = await requestSandboxStatus();
  return {
    threadId: payload.thread_id,
    backend: payload.backend,
    alive: payload.alive,
    workdir: payload.workdir,
  };
});
ipcMain.handle("desktop:list-sandbox-tree", async () => {
  const payload = await requestSandboxTree();
  return payload.nodes;
});
ipcMain.handle("desktop:list-project-files", async () => listProjectFiles());
ipcMain.handle("desktop:resume-thread", async (_event, threadId: string) => {
  if (!threadId) {
    return;
  }
  const activeBridge = ensureBridge();
  if (!activeBridge) {
    return;
  }
  activeBridge.send({ cmd: "resume", thread_id: threadId, project_path: projectPath });
});
ipcMain.handle("desktop:send-user-input", async (_event, text: string) => {
  const activeBridge = ensureBridge();
  if (!activeBridge) {
    return;
  }
  activeBridge.send({ cmd: "user", text, project_path: projectPath });
});
ipcMain.handle("desktop:send-wire-command", async (_event, command: Record<string, unknown>) => {
  const activeBridge = ensureBridge();
  if (!activeBridge) {
    return;
  }
  activeBridge.send(command);
});
ipcMain.handle("desktop:reset-session", async () => {
  const activeBridge = ensureBridge();
  if (!activeBridge) {
    return;
  }
  activeBridge.send({ cmd: "reset", project_path: projectPath });
});
ipcMain.handle("desktop:select-project", async () => {
  const options: OpenDialogOptions = {
    properties: ["openDirectory", "createDirectory"],
    defaultPath: projectPath,
    title: "选择项目目录",
    buttonLabel: "绑定项目",
  };
  const result = mainWindow
    ? await dialog.showOpenDialog(mainWindow, options)
    : await dialog.showOpenDialog(options);
  if (result.canceled || result.filePaths.length === 0) {
    return runtimeState();
  }
  setProjectPath(result.filePaths[0]);
  disposeBridge();
  currentThreadId = "";
  postSyntheticHistoryReplay();
  notifyRuntimeState();
  return runtimeState();
});
ipcMain.handle("desktop:request-history", async () => {
  await restoreHistory();
});
ipcMain.handle("desktop:permit-tool-call", async (_event, toolCallId: string) => {
  bridge?.send({ cmd: "permit", tool_call_id: toolCallId });
});
ipcMain.handle(
  "desktop:deny-tool-call",
  async (_event, toolCallId: string, reason?: string) => {
    bridge?.send({
      cmd: "deny",
      tool_call_id: toolCallId,
      reason: reason ?? "",
    });
  },
);
