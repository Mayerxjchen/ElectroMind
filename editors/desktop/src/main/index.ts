import {
  app,
  BrowserWindow,
  clipboard,
  dialog,
  ipcMain,
  nativeImage,
  screen,
  shell,
  type OpenDialogOptions,
} from "electron";
import * as crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import {
  closeSync,
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  readSync,
  readdirSync,
  statSync,
} from "node:fs";
import * as fs from "node:fs";
import type { Dirent } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";

import {
  AgentBridge,
  type AgentTransport,
  HttpBridge,
  normalizeBaseUrl,
  resolveElectromindWireInvocation,
} from "../shared/agent";
import type {
  AppInfo,
  AppSettings,
  ArtifactPreview,
  ArtifactSummary,
  DesktopEvent,
  ExecutionStatePayload,
  NewSessionOptions,
  ResetSessionOptions,
  RuntimeState,
  SandboxBackendOption,
  SandboxStatus,
  SandboxTreeNode,
  ThreadMeta,
  ThreadSummary,
  WireEvent,
} from "../shared/protocol";
import { parseWireLine } from "../shared/wire";
import { createReconnectScheduler } from "../shared/reconnect";
import {
  completeOnboarding,
  getEnvironmentCheck,
  getOnboardingState,
  installElectromindCli,
  listSandboxImages,
  saveProviderSetup,
} from "./setup";
import { atomicWriteJsonFile } from "./atomicfile";
import { LOG_DIR, log } from "./log";

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
let bridge: AgentTransport | undefined;
let activeTransport: "wire" | "http" = "wire";
let projectPath: string = defaultProjectPath();
let currentThreadId = "";
let bridgeStatus: RuntimeState["status"] = "idle";
let lastError = "";
let recentStderr = "";
let yoloMode = loadYoloMode();
let sandboxStatus: SandboxStatusPayload = {
  thread_id: "",
  backend: "",
  alive: false,
  workdir: "",
};
let threadListWaiters: Array<(payload: ThreadListPayload) => void> = [];
let sandboxTreeWaiters: SandboxTreeWaiter[] = [];
let sandboxStatusWaiters: SandboxStatusWaiter[] = [];
let executionState: ExecutionStatePayload | undefined;
import { DOCUMENTATION_URL } from "../shared/docs";

/** dock/about 用带透明边距的高清图标（符合 macOS 图标网格，避免视觉偏大）。 */
function appIconPngPath(): string {
  const padded = path.join(__dirname, "..", "assets", "app-icon.png");
  if (existsSync(padded)) {
    return padded;
  }
  return path.join(__dirname, "..", "assets", "logo-icon.png");
}

function appIconPath(): string {
  // F2: 一律用 PNG。macOS 上 BrowserWindow 的 icon 本就由 bundle/dock
  // （CFBundleIconFile）决定，传 .icns 反而触发 nativeImage 加载失败日志。
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
    applicationName: "electromind Desktop",
    iconPath: png,
  });
}

function userElectromindHome(): string {
  return path.join(homedir(), ".electromind");
}

function desktopSettingsPath(): string {
  return path.join(userElectromindHome(), "desktop.json");
}

/** 从 ~/.electromind/desktop.json 读取 YOLO；缺省或损坏时为 false。 */
function loadYoloMode(): boolean {
  return readDesktopSettings().yoloMode === true;
}

function saveYoloMode(enabled: boolean): void {
  const filePath = desktopSettingsPath();
  let existing: Record<string, unknown> = {};
  try {
    existing = JSON.parse(readFileSync(filePath, "utf8")) as Record<string, unknown>;
  } catch {
    // keep empty
  }
  existing.yoloMode = enabled;
  // P1.2: 原子写（临时文件 + rename），崩溃不留下半写 desktop.json。
  atomicWriteJsonFile(filePath, existing);
}

/**
 * 后端传输配置。默认 wire（本地 spawn 子进程）；设为 http 则连远程
 * `electromind --http` server，前端行为不变。
 *
 * 优先级：环境变量 > desktop.json，方便开发期用 flag 临时切换：
 *   ELECTROMIND_TRANSPORT=http ELECTROMIND_SERVER_URL=127.0.0.1:8899 \
 *   ELECTROMIND_SERVER_TOKEN=secret npm start
 * desktop.json 里对应 { "transport": "http", "serverUrl": "...", "serverToken": "..." }
 */
type TransportConfig = {
  mode: "wire" | "http";
  serverUrl: string;
  serverToken: string;
};

function loadTransportConfig(): TransportConfig {
  const settings = readDesktopSettings();
  const envMode = process.env.ELECTROMIND_TRANSPORT?.trim().toLowerCase();
  const settingMode =
    typeof settings.transport === "string"
      ? settings.transport.trim().toLowerCase()
      : "";
  const mode = (envMode || settingMode) === "http" ? "http" : "wire";
  const serverUrl =
    process.env.ELECTROMIND_SERVER_URL?.trim() ||
    (typeof settings.serverUrl === "string" ? settings.serverUrl : "") ||
    "127.0.0.1:8848";
  const serverToken =
    process.env.ELECTROMIND_SERVER_TOKEN?.trim() ||
    (typeof settings.serverToken === "string" ? settings.serverToken : "");
  return { mode, serverUrl, serverToken };
}

/** 读整份 desktop.json（损坏或缺失时返回空对象）。 */
function readDesktopSettings(): Record<string, unknown> {
  try {
    return JSON.parse(readFileSync(desktopSettingsPath(), "utf8")) as Record<
      string,
      unknown
    >;
  } catch {
    return {};
  }
}

/** 桌面默认用户 project（host_root）；agent 沙箱仍是 thread/workspace。 */
function defaultProjectPath(): string {
  return path.join(userElectromindHome(), "default");
}

function ensureProjectDirectory(): void {
  mkdirSync(projectPath, { recursive: true });
}

function activeHomePath(): string {
  return userElectromindHome();
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

function commandExists(cli: string): boolean {
  try {
    execFileSync("which", [cli], { stdio: "pipe" });
    return true;
  } catch {
    return false;
  }
}

/** 新建会话可选 backend：local / container（自动探测 docker|podman）/ ssh。 */
function detectAvailableBackends(): SandboxBackendOption[] {
  const backends: SandboxBackendOption[] = ["local"];
  if (commandExists("docker") || commandExists("podman")) {
    backends.push("container");
  }
  backends.push("ssh");
  return backends;
}

/** 从 ~/.ssh/config 解析显式 Host 别名（过滤通配）。 */
function readSshHosts(configPath = "~/.ssh/config"): string[] {
  const expanded = configPath.replace(/^~(?=$|[/\\])/, homedir());
  try {
    const text = readFileSync(path.resolve(expanded), "utf-8");
    const hosts: string[] = [];
    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) {
        continue;
      }
      if (!trimmed.toLowerCase().startsWith("host ")) {
        continue;
      }
      for (const token of trimmed.slice(5).trim().split(/\s+/)) {
        if (token.includes("*") || token.includes("?")) {
          continue;
        }
        hosts.push(token);
      }
    }
    return hosts;
  } catch {
    return [];
  }
}

function newSessionOptions(): NewSessionOptions {
  const images = listSandboxImages();
  return {
    projectPath,
    availableBackends: detectAvailableBackends(),
    sshHosts: readSshHosts(),
    defaultImage: images.defaultImage,
    availableImages: images.images,
  };
}

async function pickDirectory(defaultPath?: string): Promise<string | null> {
  const options: OpenDialogOptions = {
    properties: ["openDirectory", "createDirectory"],
    defaultPath: defaultPath || projectPath,
    title: "选择项目目录",
    buttonLabel: "选择",
  };
  const result = mainWindow
    ? await dialog.showOpenDialog(mainWindow, options)
    : await dialog.showOpenDialog(options);
  if (result.canceled || result.filePaths.length === 0) {
    return null;
  }
  return result.filePaths[0];
}

function artifactsDirectory(): string {
  return path.join(projectPath, "artifacts");
}

function settingsFilePath(): string {
  return path.join(userElectromindHome(), "config.toml");
}

function threadsDirectory(): string {
  return path.join(userElectromindHome(), "threads");
}

function electromindProjectRoot(): string {
  return path.join(__dirname, "..", "..", "..");
}

function configureAppRuntimePaths(): void {
  app.disableHardwareAcceleration();
  // 打包后 .app 内只读，不能用 bundle 里的 .runtime；交给系统默认 Application Support。
  if (app.isPackaged) {
    return;
  }
  // ELECTROMIND_HOME 已设置（测试 / 独立实例）→ userData 跟随它隔离，
  // 否则多实例共享固定 .runtime/user-data，单实例锁会互相拦截
  // （一个残留实例就会让后续所有测试启动失败）。
  const runtimeRoot = process.env.ELECTROMIND_HOME
    ? path.join(process.env.ELECTROMIND_HOME, ".runtime")
    : path.join(__dirname, "..", ".runtime");
  app.setPath("userData", path.join(runtimeRoot, "user-data"));
  app.setPath("sessionData", path.join(runtimeRoot, "session-data"));
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
    yoloMode,
    bridgeActive: bridge !== undefined,
    transport: activeTransport,
    status: bridgeStatus,
    lastError: lastError || undefined,
    executionState,
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

function normalizeExecutionState(
  params: Record<string, unknown>,
): ExecutionStatePayload {
  const diagsRaw = Array.isArray(params.diagnostics) ? params.diagnostics : [];
  const diagnostics: ExecutionStatePayload["diagnostics"] = [];
  for (const d of diagsRaw) {
    if (typeof d !== "object" || d === null) continue;
    const item = d as Record<string, unknown>;
    diagnostics.push({
      code: typeof item.code === "string" ? item.code : "",
      severity: typeof item.severity === "string" ? item.severity : "info",
      message: typeof item.message === "string" ? item.message : "",
    });
  }
  const modeRaw = params.mode;
  const mode = typeof modeRaw === "string" && ["local", "sandbox", "ssh"].includes(modeRaw)
    ? (modeRaw as "local" | "sandbox" | "ssh")
    : null;
  const backend = typeof params.resolved_backend === "string" ? params.resolved_backend : null;
  const thread_id = typeof params.thread_id === "string" ? params.thread_id : null;
  return {
    mode,
    resolved_backend: (backend === "local" || backend === "docker" || backend === "podman" || backend === "ssh") ? backend : null,
    isolated: params.isolated === true,
    warning: typeof params.warning === "string" ? params.warning : null,
    diagnostics,
    thread_id,
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

/** 读取 artifact 内容供右侧面板内联预览：markdown/文本高亮；图片/PDF/HTML
 * 不再整体编码为 Data URL（违反大文件协议）——标记为"需外部打开"。 */
function readArtifactPreview(filePath: string): ArtifactPreview {
  const target = resolveArtifactPath(filePath);
  const name = path.basename(filePath);
  if (!target) {
    return { name, path: filePath, size: 0, kind: "binary", reason: "文件不存在" };
  }
  return readConstrainedPreview(target, name);
}

/** P4.7: 用 fd 定位读一个文本文件的【头 + 尾】，绝不加载整份。
 *
 * 返回 { head, tail, truncated }：
 * - 文件 ≤ limit：head 即全文，tail 空，truncated=false。
 * - 文件 > limit：head=开头 limit 字节，tail=结尾 limit 字节，
 *   truncated=true。中间内容不读。
 */
function readHeadTailText(
  target: string,
  size: number,
  limit: number,
): { head: string; tail: string; truncated: boolean } {
  if (size <= limit) {
    return { head: readFileSync(target, "utf8"), tail: "", truncated: false };
  }
  const fd = openSync(target, "r");
  try {
    const headBuf = Buffer.alloc(limit);
    readSync(fd, headBuf, 0, limit, 0);
    const tailBuf = Buffer.alloc(limit);
    readSync(fd, tailBuf, 0, limit, size - limit);
    return {
      head: headBuf.toString("utf8"),
      tail: tailBuf.toString("utf8"),
      truncated: true,
    };
  } finally {
    closeSync(fd);
  }
}

/** 读取一个【已通过 containment 授权】的规范路径供内联预览。
 *  与 artifact 路径解析解耦：preview-file 传入 resolveProjectPath 的结果，
 *  read-artifact 传入 resolveArtifactPath 的结果，二者共用此读取逻辑。 */
function readConstrainedPreview(target: string, _name: string): ArtifactPreview {
  const stat = statSync(target);
  const ext = path.extname(target).toLowerCase();
  const base = { name: path.basename(target), path: target, size: stat.size };

  // Binary/rich media: no Data URL — open externally (openArtifact).
  const imageMime = ARTIFACT_IMAGE_MIME[ext];
  if (imageMime) {
    return { ...base, kind: "image", reason: "二进制内容，请使用「在系统中打开」" };
  }

  if (ext === ".pdf") {
    return { ...base, kind: "pdf", reason: "PDF 二进制内容，请使用「在系统中打开」" };
  }

  if (ext === ".html" || ext === ".htm") {
    return { ...base, kind: "html", reason: "HTML 请使用「在系统中打开」" };
  }

  const known = ext in ARTIFACT_LANGUAGES || ARTIFACT_TEXT_EXT.has(ext);
  // P4.7: 只读头 + 尾（positional read），绝不把数 GB 文件一次性读进内存。
  // 大文件用 fd 定位读：头部 <limit> 字节 + 尾部 <limit> 字节，中间省略。
  const { head, tail, truncated } = readHeadTailText(target, stat.size, ARTIFACT_TEXT_LIMIT);
  if (!known && head.includes("\x00")) {
    return { ...base, kind: "binary", reason: "二进制文件，无法内联预览" };
  }
  // 文本合并：小文件直接读全文（head 已含全文）；大文件给 head + 分隔 + tail。
  const text = !truncated ? head : `${head}\n… [文件较大，仅显示首尾各 ${ARTIFACT_TEXT_LIMIT} 字节] …\n${tail}`;
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

// ── FileRef helpers ──────────────────────────────────────────────────

function safeRealpath(p: string): string | null {
  try {
    return fs.realpathSync(p);
  } catch {
    return null; // Path doesn't exist yet — caller handles the null case
  }
}

function resolveProjectPath(filePath: string): string | null {
  if (!filePath) return null;
  const resolved = path.isAbsolute(filePath)
    ? filePath
    : path.resolve(projectPath, filePath);
  // Canonical containment: resolve symlinks on BOTH the project root and
  // the target.  A project-local symlink pointing outside projectPath is
  // rejected — string-prefix checks alone cannot catch this.
  const rootReal = safeRealpath(projectPath) ?? path.normalize(projectPath);
  const targetReal = safeRealpath(resolved) ?? path.normalize(resolved);
  if (
    targetReal !== rootReal &&
    !targetReal.startsWith(rootReal + path.sep)
  ) {
    return null; // Symlink escape or path outside the project directory
  }
  return resolved;
}

function resolveFileMetadata(filePath: string, source: string) {
  const resolved = resolveProjectPath(filePath);
  const exists = resolved ? fs.existsSync(resolved) : false;
  const stat = exists ? fs.statSync(resolved!) : null;
  const isDir = stat?.isDirectory() ?? false;

  return {
    ref: {
      id: `file-${Date.now().toString(36)}`,
      source,
      path: filePath,
      name: path.basename(filePath),
      kind: isDir ? "directory" : "file",
      size: stat?.size,
      mtimeMs: stat?.mtimeMs,
      capabilities: {
        preview: !isDir && exists,
        attach: exists,
        copyPath: true,
        exportToLocal: source === "execution",
        copyToProject: source === "execution",
        copyToExecution: source === "project",
        reveal: source === "project" && exists,
        rename: source === "project" && exists,
        delete: source === "project" && exists,
      },
    },
    exists,
  };
}

function formatFilePath(filePath: string, format: string): string {
  switch (format) {
    case "name":
      return path.basename(filePath);
    case "relative":
      return filePath.startsWith(projectPath)
        ? path.relative(projectPath, filePath)
        : filePath;
    case "uri":
      return `electromind://file/${filePath}`;
    case "absolute":
    default:
      return resolveProjectPath(filePath) ?? filePath;
  }
}

async function exportFileToLocal(ref: {
  path: string;
  source: string;
  name?: string;
}) {
  const resolved = resolveProjectPath(ref.path);
  if (!resolved || !fs.existsSync(resolved)) {
    return { ok: false, error: `文件不存在: ${ref.path}`, size: 0 };
  }

  const suggestedName = ref.name ?? path.basename(ref.path);
  const { filePath } = await dialog.showSaveDialog({
    defaultPath: suggestedName,
    title: "导出文件",
  });

  if (!filePath) {
    return { ok: false, error: "用户取消", size: 0 };
  }

  const stat = fs.statSync(resolved);
  fs.copyFileSync(resolved, filePath);
  return { ok: true, size: stat.size };
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
      if (entry.name.startsWith(".") && entry.name !== ".electromind") {
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

type ProjectTreeNode = {
  id: string;
  label: string;
  kind: "dir" | "file";
  count?: number;
  children?: ProjectTreeNode[];
};

/** 递归列出 project 目录树，供右侧「项目」面板展示。 */
function listProjectTree(dir = projectPath, prefix = ""): ProjectTreeNode[] {
  if (!existsSync(dir)) {
    return [];
  }
  let entries: Dirent[];
  try {
    entries = readdirSync(dir, { withFileTypes: true }) as Dirent[];
  } catch {
    return [];
  }
  entries.sort((a, b) => {
    if (a.isDirectory() !== b.isDirectory()) {
      return a.isDirectory() ? -1 : 1;
    }
    return a.name.localeCompare(b.name);
  });
  const nodes: ProjectTreeNode[] = [];
  for (const entry of entries) {
    if (entry.name.startsWith(".") && entry.name !== ".electromind") {
      continue;
    }
    if (PROJECT_FILE_IGNORE.has(entry.name)) {
      continue;
    }
    const nodeId = prefix ? `${prefix}/${entry.name}` : entry.name;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      const children = listProjectTree(full, nodeId);
      nodes.push({
        id: nodeId,
        label: entry.name,
        kind: "dir",
        count: children.length,
        children,
      });
      continue;
    }
    if (entry.isFile()) {
      nodes.push({ id: nodeId, label: entry.name, kind: "file" });
    }
  }
  return nodes;
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

function clearLastError(notify = true): void {
  if (!lastError) {
    return;
  }
  lastError = "";
  if (notify) {
    notifyRuntimeState();
  }
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
    // P4.4: 无法解析的 wire 协议行落 wire.log（排查协议漂移）。
    log.wire(`invalid line: ${line.slice(0, 500)}`);
    postDesktopEvent({ type: "log", text: `[wire] skip invalid line: ${line}` });
    return;
  }
  // D3: 收到任何有效事件 = wire 进程存活并握手成功 → 重置退避；若刚经历
  // 断线重连，触发状态重建（会话列表 + 当前 thread 快照）。
  onWireConnected();
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
  if (event.method === "ExecutionState") {
    executionState = normalizeExecutionState(event.params);
    notifyRuntimeState();
    return;
  }
  if (event.method === "CurrentThread" || event.method === "HistoryReplay") {
    currentThreadId = readString(event.params, "thread_id");
    const nextProjectPath = readString(event.params, "project_path");
    if (nextProjectPath) {
      setProjectPath(nextProjectPath);
    }
    // 成功切到会话后清掉上一轮残留错误（reset 失败会紧跟着再发 Error）。
    if (event.method === "HistoryReplay" && currentThreadId) {
      lastError = "";
    }
    notifyRuntimeState();
  }
  if (event.method === "RunBegin") {
    clearLastError(false);
  }
  if (event.method === "Error") {
    lastError = readString(event.params, "message");
    notifyRuntimeState();
  }
  postWireEvent(event);
}

// P4.2: 记录"正在退出"的旧 Agent；ensureBridge 在它彻底退出前不启动新进程，
// 防止两个 wire Agent 同时跑（双写同 thread 会互相覆盖状态）。
let stoppingBridge: AgentBridge | undefined;
let stoppingBridgeExited: Promise<void> = Promise.resolve();

function disposeBridge(): void {
  if (bridge) {
    stoppingBridge = bridge as AgentBridge;
    stoppingBridgeExited = stoppingBridge.whenExited();
    bridge.stop();
  }
  bridge = undefined;
  bridgeStatus = "idle";
  recentStderr = "";
  sandboxStatus = { thread_id: "", backend: "", alive: false, workdir: "" };
  reconnectScheduler.cancel();
  log.desktop("bridge disposed");
}

// ── D3: wire 自动重连（指数退避，有上限；不无限循环） ────────────
let reconnectedOnce = false; // 本次连接是否经历过断线（首个事件时触发重建）

const reconnectScheduler = createReconnectScheduler({
  onReconnect: async () => {
    // P4.2: 重连前等旧 Agent 进程树彻底退出，防止两个 wire Agent 同时跑。
    await settleStoppingBridge();
    // bridge 已被 reportBridgeFailure 清空；重新 ensureBridge（wire 新进程
    // 启动时自行从磁盘恢复线程状态）。
    const revived = ensureBridge();
    if (revived) {
      console.log("[main] D3: wire 已自动重连");
    }
  },
});

/** P4.2: 等正在退出的旧 Agent 进程彻底结束（带超时兜底）。 */
async function settleStoppingBridge(timeoutMs = 4000): Promise<void> {
  if (!stoppingBridge) {
    return;
  }
  stoppingBridge = undefined;
  // stop() 已 SIGTERM 整组 + 1.5s 后 SIGKILL；这里只需等到 exit 事件。
  const timer = new Promise<void>((resolve) => setTimeout(resolve, timeoutMs));
  await Promise.race([stoppingBridgeExited, timer]);
}

function onWireDisconnected(): void {
  reconnectedOnce = true;
  if (!reconnectScheduler.schedule()) {
    console.log("[main] D3: 自动重连达到上限，等待手动重试");
  }
}

function onWireConnected(): void {
  reconnectScheduler.onConnected();
  if (reconnectedOnce) {
    reconnectedOnce = false;
    // 重建：广播运行状态（renderer 刷新会话列表）+ 当前 thread 全量快照
    // （wire 新进程已从磁盘恢复线程状态；snapshot 经事件流回 renderer）。
    notifyRuntimeState();
    if (currentThreadId) {
      bridge?.send({
        cmd: "thread/snapshot",
        thread_id: currentThreadId,
        after_seq: -1,
      });
    }
    console.log(`[main] D3: wire 已重连，重建 thread ${currentThreadId || "(none)"} 状态`);
  }
}

function ensureBridge(): AgentTransport | undefined {
  if (bridge) {
    return bridge;
  }

  bridgeStatus = "starting";
  lastError = "";
  ensureProjectDirectory();

  const transport = loadTransportConfig();
  activeTransport = transport.mode;
  notifyRuntimeState();

  const nextBridge =
    transport.mode === "http"
      ? new HttpBridge({
        baseUrl: normalizeBaseUrl(transport.serverUrl),
        token: transport.serverToken || undefined,
        ...bridgeCallbacks("http"),
      })
      : buildWireBridge();

  bridge = nextBridge;
  bridgeStatus = "ready";
  notifyRuntimeState();
  log.desktop(`bridge ${transport.mode} starting (${transport.mode === "wire" ? wireInvocationArg() : transport.serverUrl})`);
  nextBridge.start();
  nextBridge.send({
    cmd: "client_features",
    features: { subagent_events: true },
  });
  nextBridge.send({ cmd: "commands" });
  return nextBridge;
}

function wireInvocationArg(): string {
  const inv = resolveElectromindWireInvocation(electromindProjectRoot(), {
    yolo: yoloMode,
    isPackaged: app.isPackaged,
  });
  return `${inv.command} ${inv.args.join(" ")}`;
}

function buildWireBridge(): AgentBridge {
  const wireInvocation = resolveElectromindWireInvocation(electromindProjectRoot(), {
    yolo: yoloMode,
    isPackaged: app.isPackaged,
  });
  return new AgentBridge({
    command: wireInvocation.command,
    args: wireInvocation.args,
    cwd: bridgeWorkingDirectory(),
    env: { ELECTROMIND_HOME: userElectromindHome() },
    ...bridgeCallbacks("wire"),
  });
}

/** wire / http 共用的事件、日志、生命周期回调；退出文案随传输区分。 */
function bridgeCallbacks(mode: "wire" | "http") {
  return {
    onLine: handleWireLine,
    onStderr: (text: string) => {
      recentStderr = (recentStderr + text).slice(-4000);
      // P4.4: agent stderr 落 agent.log。
      for (const line of text.split("\n")) {
        if (line.trim()) {
          log.agent(line);
        }
      }
      postDesktopEvent({ type: "log", text });
    },
    onExit: (code: number | null) => {
      const base =
        mode === "http"
          ? "与服务端的事件流已断开。"
          : code === null
            ? "子进程已退出。"
            : `子进程已退出，code=${code}。`;
      const extra = recentStderr.trim();
      reportBridgeFailure(extra ? `${base}\n${extra}` : base, "bridge");
      log.desktop(`bridge ${mode} exited: ${base}${extra ? " | " + extra : ""}`);
      onWireDisconnected();
    },
    onError: (error: Error) => {
      reportBridgeFailure(error.message, mode === "http" ? "bridge" : "spawn");
      log.desktop(`bridge ${mode} error: ${error.message}`);
      onWireDisconnected();
    },
  };
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
  // Fit the window to the primary display's work area (excludes the macOS
  // menu bar + dock).  A fixed 900-tall default or a 720 min-height can push
  // the composer/input box behind the dock — the input then appears only in
  // fullscreen (reported bug).  Clamp both the default and the minimum so the
  // input box stays on-screen at any window size.
  const workArea = screen.getPrimaryDisplay().workArea;
  const defaultWidth = Math.min(1360, workArea.width);
  const defaultHeight = Math.min(900, workArea.height);
  // P0: 验收窗口含 1024×768 —— minWidth 必须 ≤1024。Composer 已在主列
  // 正常文档流（非浮层），窄窗口下自动收缩，无需 1100 下限。
  const minWidth = Math.min(960, workArea.width);
  const minHeight = Math.min(600, workArea.height);
  // The window must NEVER exceed the work area — otherwise dragging the
  // bottom edge down tucks the composer (window bottom) behind the macOS
  // dock.  max* clamps manual resizes, not just the open size.
  const maxWidth = workArea.width;
  const maxHeight = workArea.height;

  const window = new BrowserWindow({
    width: defaultWidth,
    height: defaultHeight,
    minWidth,
    minHeight,
    maxWidth,
    maxHeight,
    title: "electromind Desktop",
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
      // 验收六：Renderer 开启沙箱。preload 只用 contextBridge/ipcRenderer，
      // 与 sandbox:true 兼容（沙箱化 preload 仍是特权上下文，可暴露 API）。
      sandbox: true,
      plugins: true,
    },
  });

  window.loadFile(path.join(__dirname, "index.html"));
  window.webContents.on("did-fail-load", (_event, code, description, url) => {
    void dialog.showErrorBox(
      "electromind Desktop",
      `页面加载失败 (${code}): ${description}\n${url}`,
    );
  });
  window.webContents.on("render-process-gone", (_event, details) => {
    // P4.3: Renderer 崩溃 → 自动 reload，并从 Agent Snapshot 恢复当前
    // Thread（renderer 启动时 requestHistoryReplay + 主进程 currentThreadId
    // 驱动 wire 重建）。带重试上限，避免崩溃循环时无限 reload。
    void handleRendererCrash(window, details.reason);
  });
  window.webContents.once("did-finish-load", () => {
    // P4.3: 加载成功 → 重置崩溃计数。
    rendererCrashStreak = 0;
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

// P4.3: Renderer 崩溃自动 reload。连续崩溃超过上限 → 弹出错误框并停止
// 自动重载（避免进程崩溃循环空转）。
let rendererCrashStreak = 0;
const RENDERER_CRASH_RELOAD_LIMIT = 3;

async function handleRendererCrash(
  window: BrowserWindow,
  reason: string,
): Promise<void> {
  rendererCrashStreak += 1;
  if (rendererCrashStreak > RENDERER_CRASH_RELOAD_LIMIT) {
    rendererCrashStreak = 0;
    void dialog.showErrorBox(
      "electromind Desktop",
      `界面进程连续崩溃 ${RENDERER_CRASH_RELOAD_LIMIT} 次，已停止自动重载。\n` +
        `最近一次原因: ${reason}\n请查看 desktop.log 定位问题。`,
    );
    return;
  }
  console.log(`[main] P4.3: renderer crashed (${reason}), reloading (${rendererCrashStreak}/${RENDERER_CRASH_RELOAD_LIMIT})`);
  try {
    window.webContents.reload();
  } catch {
    window.reload();
  }
  // 重载成功 → 从 Agent Snapshot 恢复当前 Thread（renderer 启动时
  // requestHistoryReplay；currentThreadId 保留在 main 进程）。
  if (currentThreadId) {
    bridge?.send({
      cmd: "thread/snapshot",
      thread_id: currentThreadId,
      after_seq: -1,
    });
  }
}

// P1.4: 单实例锁。第二个实例启动时聚焦既有窗口并退出，避免两个 Desktop
// 同时管理同一批 thread / Agent 进程。
// 必须在 configureAppRuntimePaths()（userData 已按 ELECTROMIND_HOME 隔离）
// 之后请求锁 —— 否则锁落在默认 userData 上，残留实例会拦截所有后续启动。
configureAppRuntimePaths();

const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) {
        mainWindow.restore();
      }
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

app.whenReady().then(() => {
  app.setName("electromind Desktop");
  applyAppIcon();
  mainWindow = createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length > 0) {
      return;
    }
    mainWindow = createWindow();
  });
});

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
/** P4.4: 一键打开日志目录。 */
ipcMain.handle("desktop:open-log-dir", async () => {
  try {
    mkdirSync(LOG_DIR, { recursive: true });
    const err = await shell.openPath(LOG_DIR);
    return { ok: !err, error: err || undefined };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
});
/** YOLO 改变审批 hook 装配，持久化后重启 wire 生效。 */
ipcMain.handle("desktop:set-yolo-mode", async (_event, enabled: boolean) => {
  const next = Boolean(enabled);
  if (next === yoloMode) {
    return runtimeState();
  }
  yoloMode = next;
  saveYoloMode(next);
  const resumeId = currentThreadId;
  disposeBridge();
  await settleStoppingBridge(); // P4.2: 旧 Agent 退出后再起新进程
  ensureBridge();
  if (resumeId) {
    bridge?.send({
      cmd: "resume",
      thread_id: resumeId,
      project_path: projectPath,
    });
  }
  notifyRuntimeState();
  return runtimeState();
});
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

// ── FileRef operations ───────────────────────────────────────────────

ipcMain.handle(
  "desktop:get-file-metadata",
  async (_event, ref: { path: string; source: string }) => {
    return resolveFileMetadata(ref.path, ref.source);
  },
);

ipcMain.handle(
  "desktop:preview-file",
  async (_event, ref: { path: string; source: string }): Promise<ArtifactPreview> => {
    // Constrained: only project files are previewable in-process; binary
    // content is never encoded as Data URL.  The resolved path is already
    // containment-authorized — do NOT re-validate as an artifact.
    const resolved = resolveProjectPath(ref.path);
    if (!resolved || !fs.existsSync(resolved)) {
      return { name: path.basename(ref.path), path: ref.path, size: 0, kind: "binary", reason: "文件不存在" };
    }
    return readConstrainedPreview(resolved, path.basename(resolved));
  },
);

ipcMain.handle(
  "desktop:copy-file-path",
  async (_event, ref: { path: string }, format: string) => {
    const text = formatFilePath(ref.path, format);
    clipboard.writeText(text);
  },
);

ipcMain.handle(
  "desktop:export-file",
  async (_event, ref: { path: string; source: string; name?: string }) => {
    return exportFileToLocal(ref);
  },
);

ipcMain.handle(
  "desktop:reveal-in-finder",
  async (_event, ref: { path: string; source: string }) => {
    const resolved = resolveProjectPath(ref.path);
    if (resolved && fs.existsSync(resolved)) {
      shell.showItemInFolder(resolved);
    }
  },
);

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
ipcMain.handle("desktop:list-project-tree", async () => listProjectTree());
ipcMain.handle("desktop:clear-last-error", async () => {
  clearLastError();
});
ipcMain.handle("desktop:force-reconnect", async () => {
  // D3.4-2: manual reconnect entry — the auto scheduler stops after its
  // attempt ceiling; a manual retry resets it and re-spawns the wire.
  reconnectScheduler.cancel();
  return ensureBridge();
});

ipcMain.handle("desktop:resume-thread", async (_event, threadId: string) => {
  clearLastError(false);
  if (!threadId) {
    return;
  }
  const activeBridge = ensureBridge();
  if (!activeBridge) {
    return;
  }
  activeBridge.send({ cmd: "resume", thread_id: threadId, project_path: projectPath });
});
ipcMain.handle("desktop:delete-thread", async (_event, threadId: string) => {
  if (!threadId || typeof threadId !== "string") {
    return false;
  }
  const activeBridge = ensureBridge();
  if (!activeBridge) {
    return false;
  }
  // 二次确认在渲染进程用自定义对话框完成，这里直接执行删除。
  const deletingCurrent = threadId === currentThreadId;
  activeBridge.send({
    cmd: "delete_thread",
    thread_id: threadId,
    project_path: projectPath,
  });
  if (deletingCurrent) {
    currentThreadId = "";
    clearLastError(false);
    notifyRuntimeState();
  }
  return true;
});
ipcMain.handle("desktop:send-user-input", async (_event, text: string, requestId?: string, delivery?: string, mode?: string, model?: string, skill?: string) => {
  clearLastError();
  const activeBridge = ensureBridge();
  if (!activeBridge) {
    return;
  }
  const reqId = requestId && requestId.startsWith("req-")
    ? requestId
    : `req-${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`;
  const dlv = delivery === "enqueue" || delivery === "immediate" || delivery === "auto"
    ? delivery
    : "auto";
  activeBridge.send({
    cmd: "input/send",
    text,
    delivery: dlv,
    mode: mode && mode !== "agent" ? mode : undefined,
    // P3: Auto Model policy（auto/fast/balanced/best/plan-execute/模型 id）
    model: model && model.trim() ? model.trim() : undefined,
    // P4: /skill 调用 —— skill 名随行（后端确定性激活）
    skill: skill && skill.trim() ? skill.trim() : undefined,
    project_path: projectPath,
    request_id: reqId,
  });
});
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

ipcMain.handle("desktop:send-wire-command", async (_event, command: Record<string, unknown>) => {
  // Defense in depth: the Renderer may only send allowlisted commands.
  const cmd = String(command?.cmd ?? "");
  if (!ALLOWED_WIRE_COMMANDS.has(cmd)) {
    console.warn(`[main] rejected wire command: ${cmd}`);
    return;
  }
  const activeBridge = ensureBridge();
  if (!activeBridge) {
    return;
  }
  activeBridge.send(command);
});
ipcMain.handle(
  "desktop:reset-session",
  async (_event, options?: ResetSessionOptions) => {
    clearLastError(false);
    const activeBridge = ensureBridge();
    if (!activeBridge) {
      return;
    }
    const nextProject =
      typeof options?.projectPath === "string" && options.projectPath.trim()
        ? options.projectPath.trim()
        : projectPath;
    if (nextProject !== projectPath) {
      setProjectPath(nextProject);
      notifyRuntimeState();
    }
    const command: Record<string, unknown> = {
      cmd: "reset",
      project_path: nextProject,
    };
    // 将旧 backend 映射为新 execution_mode 协议：
    //   local → execution_mode=local
    //   container/docker/podman → execution_mode=sandbox, backend=...
    //   ssh → execution_mode=ssh
    const backend = options?.backend;
    if (backend) {
      if (backend === "local") {
        command.execution_mode = "local";
      } else if (backend === "container" || backend === "docker" || backend === "podman") {
        command.execution_mode = "sandbox";
        command.backend = backend;
      } else if (backend === "ssh") {
        command.execution_mode = "ssh";
      }
    }
    if (options?.image?.trim()) {
      command.image = options.image.trim();
    }
    if (options?.sshHost?.trim()) {
      command.ssh_host = options.sshHost.trim();
    }
    if (options?.sshConfig?.trim()) {
      command.ssh_config = options.sshConfig.trim();
    }
    if (options?.sshWorkdir?.trim()) {
      command.ssh_workdir = options.sshWorkdir.trim();
    }
    activeBridge.send(command);
  },
);
ipcMain.handle("desktop:pick-directory", async (_event, defaultPath?: string) => {
  return pickDirectory(
    typeof defaultPath === "string" ? defaultPath : undefined,
  );
});
ipcMain.handle("desktop:get-new-session-options", async () => {
  return newSessionOptions();
});
ipcMain.handle("desktop:get-onboarding-state", async () =>
  getOnboardingState(electromindProjectRoot(), app.isPackaged),
);
ipcMain.handle("desktop:refresh-environment-check", async () =>
  getEnvironmentCheck({
    includeDisk: true,
    projectRoot: electromindProjectRoot(),
    isPackaged: app.isPackaged,
  }),
);
ipcMain.handle("desktop:install-electromind-cli", async () => installElectromindCli());
ipcMain.handle("desktop:save-provider-setup", async (_event, setup) => {
  const saved = saveProviderSetup(setup);
  // wire 启动时缓存了旧配置；写入 Key 后丢掉进程，下次 ensureBridge 会重新加载。
  disposeBridge();
  notifyRuntimeState();
  return saved;
});
ipcMain.handle("desktop:complete-onboarding", async (_event, options) => {
  completeOnboarding({
    ...options,
    projectRoot: electromindProjectRoot(),
    isPackaged: app.isPackaged,
  });
  disposeBridge();
  notifyRuntimeState();
});
ipcMain.handle("desktop:select-project", async () => {
  const picked = await pickDirectory(projectPath);
  if (!picked) {
    return runtimeState();
  }
  setProjectPath(picked);
  disposeBridge();
  currentThreadId = "";
  postSyntheticHistoryReplay();
  notifyRuntimeState();
  return runtimeState();
});
ipcMain.handle("desktop:request-history", async () => {
  await restoreHistory();
});
ipcMain.handle("desktop:permit-tool-call", async (_event, payload: unknown) => {
  const p = (typeof payload === "object" && payload !== null ? payload : {}) as Record<string, unknown>;
  bridge?.send({
    cmd: "permit",
    tool_call_id: String(p.toolCallId ?? ""),
    approval_id: String(p.approvalId ?? ""),
    thread_id: String(p.threadId ?? ""),
    run_id: String(p.runId ?? ""),
  });
});
ipcMain.handle(
  "desktop:deny-tool-call",
  async (_event, payload: unknown) => {
    const p = (typeof payload === "object" && payload !== null ? payload : {}) as Record<string, unknown>;
    bridge?.send({
      cmd: "deny",
      tool_call_id: String(p.toolCallId ?? ""),
      reason: String(p.reason ?? ""),
      approval_id: String(p.approvalId ?? ""),
      thread_id: String(p.threadId ?? ""),
      run_id: String(p.runId ?? ""),
    });
  },
);
