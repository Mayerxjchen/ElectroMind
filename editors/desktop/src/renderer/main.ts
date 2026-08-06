import { getThreadStore } from "./store/ThreadStore";
import { SessionManager } from "./store/SessionManager";
import { InspectorController } from "./InspectorController";

// D3.4-2: the renderer and react-shell bundles each bundle their own copy
// of ThreadStore — without a shared instance the React side would read a
// never-updated store (empty sessions, stale bridge state).  Expose the
// vanilla store here (module level, before react-shell.js evaluates) so
// the React side binds to the SAME singleton (single source of truth).
(window as unknown as Record<string, unknown>).__electromindStore =
  getThreadStore();
import { isInspectorTab, type InspectorTab } from "./inspector-model";
import {
  initialSkillsPanelState,
  reduceSkillsAction,
  renderSkillRows,
  type SkillViewItem,
} from "./skills-view";
import { MessageRenderer } from "./MessageRenderer";
import { ContextUsageRing } from "./context-usage";
import { modelPolicyString } from "./react/model-policy";
import { INSTALL_COMMANDS, bindHealthPanel, renderHealthPanel } from "./environment-health";
import { mountOnboarding } from "./onboarding";
import DOMPurify from "dompurify";
import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import c from "highlight.js/lib/languages/c";
import cpp from "highlight.js/lib/languages/cpp";
import css from "highlight.js/lib/languages/css";
import go from "highlight.js/lib/languages/go";
import ini from "highlight.js/lib/languages/ini";
import java from "highlight.js/lib/languages/java";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import markdown from "highlight.js/lib/languages/markdown";
import python from "highlight.js/lib/languages/python";
import ruby from "highlight.js/lib/languages/ruby";
import rust from "highlight.js/lib/languages/rust";
import scss from "highlight.js/lib/languages/scss";
import sql from "highlight.js/lib/languages/sql";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";
import { marked } from "marked";
import type {
  AppInfo,
  AppSettings,
  EnvironmentCheck,
  ArtifactPreview,
  ArtifactSummary,
  HpcSubmissionsPayload,
  MentionFile,
  MentionSource,
  NewSessionOptions,
  ResetSessionOptions,
  RuntimeState,
  SandboxBackendOption,
  SandboxStatus,
  SandboxTreeNode,
  Skill,
  ThreadMeta,
  ThreadSummary,
  WireCommand,
  WireEvent,
} from "../shared/protocol";
import { renderIcon, renderWechatIcon, type DesktopIconName } from "./icons";
import { paintDocsQr } from "./docs-qr";
import { mountToaster, toast } from "./toast";
import {
  computeExecutionContextTransition,
  shouldClearExecutionContextOnReplay,
} from "./execution-context-state";

const INPUT_MAX_HEIGHT_PX = 160;
const LEFT_PANE_WIDTH_PX = 220;
const LEFT_COLLAPSED_WIDTH_PX = 44;

type ThemeMode = "dark" | "light";
type PanelTab = InspectorTab;
type ActivityState = "running" | "sleeping" | "error";
type ResourceKind = "cpu" | "memory" | "disk";
type TerminalEntryKind = "command" | "stdout" | "stderr" | "status";

type TerminalEntry = {
  kind: TerminalEntryKind;
  text: string;
};

type SettingsSection = {
  name: string;
  entries: Array<{ key: string; value: string }>;
};

function platformClass(appInfo: AppInfo): string {
  return appInfo.platform === "darwin" ? "macos" : "default";
}

function escapeHtml(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function readStringField(params: Record<string, unknown>, key: string): string {
  const value = params[key];
  return typeof value === "string" ? value : "";
}

function readRecordField(
  params: Record<string, unknown>,
  key: string,
): Record<string, unknown> | undefined {
  const value = params[key];
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : undefined;
}

function unwrapSubagentEvent(
  event: WireEvent,
): { name: string; inner: WireEvent } | undefined {
  if (event.method !== "SubagentEvent") {
    return undefined;
  }
  const wrapped = readRecordField(event.params, "event");
  if (!wrapped) {
    return undefined;
  }
  const method = readStringField(wrapped, "method");
  if (!method) {
    return undefined;
  }
  return {
    name: readStringField(event.params, "name"),
    inner: {
      method,
      params: readRecordField(wrapped, "params") ?? {},
    },
  };
}

function summarize(text: string, maxLength = 72): string {
  const compact = text.replace(/\s+/g, " ").trim();
  if (!compact) {
    return "";
  }
  if (compact.length <= maxLength) {
    return compact;
  }
  return `${compact.slice(0, maxLength)}…`;
}

function formatBytes(size: number): string {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function formatMetaDate(value: string): string {
  if (!value) {
    return "未记录";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function formatMetaValue(value: string | number | undefined): string {
  if (value === undefined || value === "") {
    return "未记录";
  }
  return String(value);
}

/** Normalize a project-relative path string. Returns null for absolute paths
 *  or paths that attempt to escape the project root via `..` segments. */
function normalizeProjectRelativePath(raw: string): string | null {
  if (!raw) {
    return null;
  }
  // Absolute paths (Unix or Windows) are not valid relative paths.
  if (raw.startsWith("/") || /^[A-Za-z]:[/\\]/.test(raw)) {
    return null;
  }
  const segments = raw.replace(/\\/g, "/").split("/");
  const resolved: string[] = [];
  for (const segment of segments) {
    if (segment === "" || segment === ".") {
      continue;
    }
    if (segment === "..") {
      if (resolved.length === 0) {
        return null; // escaping project root
      }
      resolved.pop();
    } else {
      resolved.push(segment);
    }
  }
  return resolved.join("/");
}

/** Build an absolute path by joining the project root with a normalized
 *  relative path. Returns null if the result does not sit under the root. */
function buildAbsolutePath(projectPath: string, relativePath: string): string | null {
  if (!projectPath) {
    return null;
  }
  const normalized = normalizeProjectRelativePath(relativePath);
  if (normalized === null) {
    return null;
  }

  const sep = projectPath.includes("\\") ? "\\" : "/";
  const trimmed = projectPath.replace(/[/\\]+$/, "");

  // Reconstitute a proper root when stripping left an incomplete prefix:
  //   "/"        → trimmed ""   → root "/"
  //   "C:\\"     → trimmed "C:" → root "C:\\"
  //   "/project" → trimmed "/project" → root "/project"
  let root: string;
  if (!trimmed) {
    root = sep;
  } else if (/^[A-Za-z]:$/.test(trimmed)) {
    root = `${trimmed}${sep}`;
  } else {
    root = trimmed;
  }

  if (!normalized) {
    return root;
  }

  const absolute = `${root}${root.endsWith(sep) ? "" : sep}${normalized.replace(/\//g, sep)}`;
  // Safety: verify the result starts with the canonical root (trimmed or reconstructed).
  const checkRoot = trimmed || root;
  if (!absolute.startsWith(checkRoot)) {
    return null;
  }
  return absolute;
}

function artifactIcon(name: string): DesktopIconName {
  if (/\.(html?|css|jsx?|tsx?|py|sh)$/i.test(name)) {
    return "code-xml";
  }
  if (/\.json$/i.test(name)) {
    return "file-json";
  }
  if (/\.(md|txt|log)$/i.test(name)) {
    return "file-text";
  }
  return "file";
}

function readStoredTheme(): ThemeMode {
  const value = window.localStorage.getItem("electromind-desktop-theme");
  return value === "light" ? "light" : "dark";
}

function readStoredSidebarPinned(): boolean {
  return window.localStorage.getItem("electromind-desktop-sidebar-pinned") === "1";
}

function projectLabel(runtime: RuntimeState): string {
  const path = runtime.projectPath;
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] || path || "default";
}

function artifactRootPath(runtime: RuntimeState): string {
  const separator = runtime.projectPath.includes("\\") ? "\\" : "/";
  return `${runtime.projectPath.replace(/[\\/]+$/, "")}${separator}artifacts`;
}

function sandboxBackendLabel(runtime: RuntimeState): string {
  const backend = runtime.sandboxBackend;
  if (!backend) {
    return runtime.currentThreadId ? "待连接" : "未启动";
  }
  if (backend === "docker" || backend === "podman") {
    return "container";
  }
  return backend;
}

function sandboxBackendIconName(runtime: RuntimeState): DesktopIconName {
  const backend = runtime.sandboxBackend;
  if (!backend) {
    return "server";
  }
  if (backend === "local") {
    return "hard-drive";
  }
  if (backend === "container" || backend === "docker" || backend === "podman") {
    return "container";
  }
  if (backend === "ssh") {
    return "globe";
  }
  return "server";
}

function sessionSandboxLabel(backend: string): string {
  if (backend === "container" || backend === "docker" || backend === "podman") {
    return "container";
  }
  if (backend === "ssh") {
    return "ssh";
  }
  return "local";
}

function sessionSandboxIconName(backend: string): DesktopIconName {
  if (backend === "container" || backend === "docker" || backend === "podman") {
    return "container";
  }
  if (backend === "ssh") {
    return "globe";
  }
  return "hard-drive";
}

function sandboxBackendOptionLabel(backend: SandboxBackendOption): string {
  if (backend === "local") {
    return "本机";
  }
  if (backend === "container" || backend === "docker" || backend === "podman") {
    return "容器";
  }
  return "SSH";
}

function sandboxBackendOptionSub(backend: SandboxBackendOption): string {
  if (backend === "local") {
    return "local";
  }
  if (backend === "container") {
    return "auto";
  }
  if (backend === "docker") {
    return "docker";
  }
  if (backend === "podman") {
    return "podman";
  }
  return "remote";
}

function sandboxBackendOptionHint(backend: SandboxBackendOption): string {
  if (backend === "local") {
    return "命令与文件落在本机 thread workspace，无需 Docker。";
  }
  if (backend === "container" || backend === "docker" || backend === "podman") {
    return "命令在容器内执行；工作区仍挂载到本机 thread workspace。";
  }
  return "通过 SSH 在远端主机执行；需填写 Host 与远程工作目录。";
}

function sandboxPresenceClass(runtime: RuntimeState): "alive" | "dead" | "pending" {
  if (runtime.sandboxAlive === true) {
    return "alive";
  }
  if (runtime.sandboxAlive === false) {
    return "dead";
  }
  return "pending";
}

function currentSessionTitle(
  runtime: RuntimeState,
  sessions: ThreadSummary[],
): string {
  const current = sessions.find((item) => item.id === runtime.currentThreadId);
  if (current) {
    return current.title;
  }
  return "新建任务";
}

function resourceSnapshot(activityState: ActivityState): Record<ResourceKind, {
  value: string;
  percent: number;
}> {
  if (activityState === "running") {
    return {
      cpu: { value: "41%", percent: 41 },
      memory: { value: "1.3 GB", percent: 57 },
      disk: { value: "2.4 GB", percent: 34 },
    };
  }
  if (activityState === "error") {
    return {
      cpu: { value: "--", percent: 12 },
      memory: { value: "--", percent: 18 },
      disk: { value: "2.4 GB", percent: 34 },
    };
  }
  return {
    cpu: { value: "0%", percent: 0 },
    memory: { value: "0 GB", percent: 0 },
    disk: { value: "2.4 GB", percent: 34 },
  };
}

function renderSessionList(
  sessions: ThreadSummary[],
  currentThreadId: string,
): string {
  if (sessions.length === 0) {
    return `
      <div class="session-empty">
        <div class="session-empty-title">还没有历史会话</div>
        <div class="session-empty-copy">点击上方新建任务开始第一条对话。</div>
      </div>
    `;
  }

  return sessions
    .map((session) => {
      const isCurrent = session.id === currentThreadId;
      const relativeTime = session.relativeTime || "刚刚";
      const sandboxLabel = sessionSandboxLabel(session.sandboxBackend);
      return `
        <div
          class="session-item${isCurrent ? " current" : ""}"
          data-thread-id="${escapeHtml(session.id)}"
        >
          <button class="session-open" type="button" data-thread-open data-thread-id="${escapeHtml(session.id)}">
            <span class="session-status${isCurrent ? " current" : ""}" title="沙箱：${escapeHtml(sandboxLabel)}">
              ${renderIcon(sessionSandboxIconName(session.sandboxBackend))}
            </span>
            <span class="session-main">
              <span class="session-title">${escapeHtml(session.title)}</span>
              <span class="session-time">${escapeHtml(relativeTime)}</span>
            </span>
          </button>
          <div class="session-actions">
            <button class="session-action-button" type="button" data-thread-delete data-thread-id="${escapeHtml(session.id)}" title="删除会话" aria-label="删除会话">
              ${renderIcon("trash-2")}
            </button>
            <button class="session-action-button" type="button" data-thread-meta data-thread-id="${escapeHtml(session.id)}" title="查看会话信息" aria-label="查看会话信息">
              ${renderIcon("circle-alert")}
            </button>
          </div>
        </div>
      `;
    })
    .join("");
}

function renderThreadMetaSkeleton(): string {
  return `
    <div class="meta-skeleton">
      <div class="meta-skeleton-row">
        <div class="skeleton-line title"></div>
        <div class="skeleton-line short"></div>
      </div>
      <div class="meta-skeleton-row">
        <div class="skeleton-line medium"></div>
        <div class="skeleton-line medium"></div>
        <div class="skeleton-line short"></div>
      </div>
      <div class="meta-skeleton-row">
        <div class="skeleton-line short"></div>
        <div class="skeleton-line block"></div>
      </div>
    </div>
  `;
}

function renderThreadMeta(meta: ThreadMeta, session: ThreadSummary | undefined): string {
  const title = meta.title || session?.title || "新建任务";
  const projectPath = session?.projectPath || "";
  const rawMeta = JSON.stringify(meta.metainfo, null, 2);
  return `
    <div class="thread-meta-summary">
      <div class="thread-meta-title">${escapeHtml(title)}</div>
      <div class="thread-meta-id">${escapeHtml(meta.id)}</div>
    </div>
    <div class="thread-meta-grid">
      <div class="thread-meta-label">Project</div>
      <div class="thread-meta-value">${escapeHtml(formatMetaValue(projectPath))}</div>
      <div class="thread-meta-label">创建时间</div>
      <div class="thread-meta-value">${escapeHtml(formatMetaDate(meta.createdAt))}</div>
      <div class="thread-meta-label">更新时间</div>
      <div class="thread-meta-value">${escapeHtml(formatMetaDate(meta.updatedAt))}</div>
      <div class="thread-meta-label">消息数</div>
      <div class="thread-meta-value">${escapeHtml(formatMetaValue(meta.messageCount))}</div>
      <div class="thread-meta-label">目录</div>
      <div class="thread-meta-value">${escapeHtml(meta.threadPath)}</div>
    </div>
    <div class="thread-meta-raw-title">metainfo.json</div>
    <pre class="thread-meta-raw">${escapeHtml(rawMeta || "{}")}</pre>
  `;
}

function settingSectionLabel(name: string): string {
  const labels: Record<string, string> = {
    agent: "助手",
    conversation: "会话",
    llm: "模型服务",
    model: "模型服务",
    project: "项目",
    sandbox: "沙箱",
    ssh: "远程连接",
  };
  return labels[name] ?? name;
}

function settingLabel(key: string): string {
  const labels: Record<string, string> = {
    api_key: "API Key",
    base_url: "服务地址",
    backend: "类型",
    host: "主机",
    image: "镜像",
    model: "模型",
    path: "路径",
    workdir: "工作目录",
  };
  return labels[key] ?? key.replaceAll("_", " ");
}

function settingValue(key: string, value: string): string {
  if (/(api.?key|secret|token|password)/i.test(key)) {
    return "已配置";
  }
  return value.replace(/^"(.*)"$/, "$1");
}

function parseSettings(content: string): SettingsSection[] {
  const sections = new Map<string, SettingsSection>();
  let currentSection = "general";
  sections.set(currentSection, { name: currentSection, entries: [] });

  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) {
      continue;
    }
    const section = /^\[([A-Za-z0-9_.-]+)]$/.exec(line);
    if (section) {
      currentSection = section[1];
      sections.set(currentSection, { name: currentSection, entries: [] });
      continue;
    }
    const entry = /^([A-Za-z0-9_.-]+)\s*=\s*(.+)$/.exec(line);
    if (entry) {
      sections.get(currentSection)?.entries.push({
        key: entry[1],
        value: settingValue(entry[1], entry[2]),
      });
    }
  }

  return [...sections.values()].filter((section) => section.entries.length > 0);
}

function renderNewSessionForm(
  options: NewSessionOptions,
  draft: {
    backend: SandboxBackendOption;
    projectPath: string;
    sshHost: string;
    sshWorkdir: string;
    image: string;
  },
): string {
  // 始终展示全部三种模式；不可用模式标记为 disabled，container 不可用时阻塞但不切 local。
  const allBackends: SandboxBackendOption[] = ["container", "local", "ssh"];
  const availableSet = new Set(options.availableBackends);
  const backend = draft.backend;
  const containerUnavailable = backend === "container" && !availableSet.has("container");
  const sshHosts = options.sshHosts;
  const images = options.availableImages.length > 0
    ? options.availableImages
    : [options.defaultImage || "electromind:latest"];
  const image = draft.image && images.includes(draft.image)
    ? draft.image
    : (images.includes(options.defaultImage) ? options.defaultImage : images[0]);
  const isContainer =
    backend === "container" || backend === "docker" || backend === "podman";
  const backendCards = allBackends
    .map((item) => {
      const available = availableSet.has(item);
      const active = item === backend ? " active" : "";
      const disabled = !available ? " disabled" : "";
      const sub = available
        ? sandboxBackendOptionSub(item)
        : (item === "container" ? "Docker/Podman 不可用" : "当前不可用");
      return `
        <button class="new-session-backend${active}" type="button" data-backend="${escapeHtml(item)}"${disabled}>
          <span class="new-session-backend-icon" aria-hidden="true">${renderIcon(sessionSandboxIconName(item))}</span>
          <span class="new-session-backend-copy">
            <span class="new-session-backend-label">${escapeHtml(sandboxBackendOptionLabel(item))}</span>
            <span class="new-session-backend-sub">${escapeHtml(sub)}</span>
          </span>
        </button>
      `;
    })
    .join("");
  const imageBlock = isContainer
    ? `
      <label class="new-session-field">
        <span class="new-session-label">镜像</span>
        ${images.length > 1
      ? `<div class="new-session-dropdown" data-image-dropdown>
              <button class="new-session-input new-session-dropdown-trigger" type="button" data-image-dropdown-toggle aria-haspopup="listbox" aria-expanded="false">
                <span class="new-session-dropdown-value" data-image-label>${escapeHtml(image)}</span>
                <span class="new-session-dropdown-chevron" aria-hidden="true">${renderIcon("chevron-down")}</span>
              </button>
              <input type="hidden" data-image value="${escapeHtml(image)}" />
              <div class="new-session-dropdown-menu" data-image-dropdown-menu hidden role="listbox">
                ${images.map((item) => {
        const active = item === image ? " active" : "";
        return `<button class="new-session-dropdown-option${active}" type="button" role="option" data-image-option value="${escapeHtml(item)}" aria-selected="${item === image ? "true" : "false"}">${escapeHtml(item)}</button>`;
      }).join("")}
              </div>
            </div>`
      : `<input class="new-session-input" data-image type="text" value="${escapeHtml(image)}" placeholder="electromind:latest" spellcheck="false" />`
    }
        <div class="new-session-hint">本机 electromind 镜像；browser 可用于渲染 HTML / 导出 PDF。</div>
      </label>
    `
    : "";
  const sshBlock = backend === "ssh"
    ? `
      <label class="new-session-field">
        <span class="new-session-label">SSH Host</span>
        ${sshHosts.length > 0
      ? `<div class="new-session-dropdown" data-ssh-dropdown>
              <button class="new-session-input new-session-dropdown-trigger" type="button" data-ssh-dropdown-toggle aria-haspopup="listbox" aria-expanded="false">
                <span class="new-session-dropdown-value${draft.sshHost ? "" : " is-placeholder"}" data-ssh-host-label>${escapeHtml(draft.sshHost || "选择 Host…")}</span>
                <span class="new-session-dropdown-chevron" aria-hidden="true">${renderIcon("chevron-down")}</span>
              </button>
              <input type="hidden" data-ssh-host value="${escapeHtml(draft.sshHost)}" />
              <div class="new-session-dropdown-menu" data-ssh-dropdown-menu hidden role="listbox">
                ${sshHosts.map((host) => {
        const active = host === draft.sshHost ? " active" : "";
        return `<button class="new-session-dropdown-option${active}" type="button" role="option" data-ssh-host-option value="${escapeHtml(host)}" aria-selected="${host === draft.sshHost ? "true" : "false"}">${escapeHtml(host)}</button>`;
      }).join("")}
              </div>
            </div>`
      : `<input class="new-session-input" data-ssh-host type="text" value="${escapeHtml(draft.sshHost)}" placeholder="例如 myserver" />`
    }
      </label>
      <label class="new-session-field">
        <span class="new-session-label">远程工作目录</span>
        <input class="new-session-input" data-ssh-workdir type="text" value="${escapeHtml(draft.sshWorkdir)}" placeholder="~/electromind" />
      </label>
    `
    : "";
  return `
    <div class="new-session-form">
      <div class="new-session-field">
        <span class="new-session-label">沙箱类型</span>
        <div class="new-session-backends" data-backend-list style="--backend-count: ${allBackends.length}">${backendCards}</div>
        ${
          containerUnavailable
            ? `<div class="new-session-blocking">Docker/Podman 不可用。Sandbox 是默认执行目标，安装或启动容器运行时后重试，或手动选择 Local 并确认风险。</div>`
            : `<div class="new-session-hint" data-backend-hint>${escapeHtml(sandboxBackendOptionHint(backend))}</div>`
        }
      </div>
      ${imageBlock}
      <label class="new-session-field">
        <span class="new-session-label">项目目录</span>
        <div class="new-session-path-row">
          <input class="new-session-input" data-project-path type="text" value="${escapeHtml(draft.projectPath)}" spellcheck="false" />
          <button class="new-session-browse" type="button" data-pick-project>浏览</button>
        </div>
        <div class="new-session-hint">绑定宿主项目（host_root）；agent 沙箱 workspace 仍按会话自动创建。</div>
      </label>
      ${sshBlock}
      <div class="new-session-actions">
        <button class="new-session-secondary" type="button" data-new-session-cancel>取消</button>
        <button class="new-session-primary" type="button" data-new-session-confirm${containerUnavailable ? " disabled" : ""}>${containerUnavailable ? "容器不可用" : "创建会话"}</button>
      </div>
    </div>
  `;
}

function renderSettings(settings: AppSettings, env: EnvironmentCheck): string {
  const health = renderHealthPanel(env);
  if (!settings.exists) {
    return `
      ${health}
      <div class="settings-section-gap"></div>
      <div class="settings-path">${escapeHtml(settings.path)}</div>
      <div class="settings-empty">还没有配置文件。</div>
    `;
  }
  const sections = parseSettings(settings.content);
  const overview = sections.length > 0
    ? sections.map((section) => `
        <section class="settings-section">
          <div class="settings-section-title">${escapeHtml(settingSectionLabel(section.name))}</div>
          <div class="settings-list">
            ${section.entries.map((entry) => `
              <div class="settings-entry">
                <span class="settings-key">${escapeHtml(settingLabel(entry.key))}</span>
                <span class="settings-value">${escapeHtml(entry.value)}</span>
              </div>
            `).join("")}
          </div>
        </section>
      `).join("")
    : `<div class="settings-empty">配置文件还没有可展示的项目。</div>`;
  return `
    ${health}
    <div class="settings-section-gap"></div>
    <div class="settings-path">${escapeHtml(settings.path)}</div>
    <div class="settings-overview">${overview}</div>
    <details class="settings-source">
      <summary>查看原始配置</summary>
      <pre class="settings-raw">${escapeHtml(settings.content || "# 空配置文件")}</pre>
    </details>
  `;
}

function renderTreeRows(
  nodes: SandboxTreeNode[],
  expanded: ReadonlySet<string>,
  depth = 0,
): string {
  return nodes
    .map((node) => {
      const indent = depth * 18;
      if (node.kind === "dir") {
        const isOpen = expanded.has(node.id);
        const children = isOpen && node.children
          ? renderTreeRows(node.children, expanded, depth + 1)
          : "";
        return `
          <div class="tree-block">
            <button
              class="tree-row tree-row-dir"
              type="button"
              data-tree-toggle="${escapeHtml(node.id)}"
              data-node-path="${escapeHtml(node.id)}"
              style="--tree-indent:${indent}px"
            >
              <span class="tree-cell tree-cell-arrow">
                ${renderIcon(isOpen ? "chevron-down" : "chevron-right")}
              </span>
              <span class="tree-cell tree-cell-icon">
                ${renderIcon("folder")}
              </span>
              <span class="tree-cell tree-cell-label">${escapeHtml(node.label)}</span>
              <span class="tree-count">${node.count ?? 0}</span>
            </button>
            ${children}
          </div>
        `;
      }
      return `
        <div class="tree-row tree-row-file" data-node-path="${escapeHtml(node.id)}" style="--tree-indent:${indent}px">
          <span class="tree-cell tree-cell-arrow"></span>
          <span class="tree-cell tree-cell-icon">
            ${renderIcon("file")}
          </span>
          <span class="tree-cell tree-cell-label">
            ${escapeHtml(node.label)}
          </span>
          <span class="tree-change"></span>
        </div>
      `;
    })
    .join("");
}

function renderPathRootCard(rootPath: string, label = "本机路径"): string {
  if (!rootPath) {
    return "";
  }
  return `
    <div class="artifact-root">
      <div class="artifact-root-label">${escapeHtml(label)}</div>
      <div class="artifact-root-path" title="${escapeHtml(rootPath)}">${escapeHtml(rootPath)}</div>
    </div>
  `;
}

/** 沙箱标识卡片：标明 backend 类型与 workdir。 */
function sandboxPathRootLabel(backend: string): string {
  if (backend === "local") {
    return "本机沙箱";
  }
  if (backend === "container" || backend === "docker" || backend === "podman") {
    return "容器沙箱";
  }
  if (backend === "ssh") {
    return "SSH 沙箱";
  }
  return "沙箱";
}

function renderArtifacts(artifacts: ArtifactSummary[], rootPath: string): string {
  const header = renderPathRootCard(rootPath);
  if (artifacts.length === 0) {
    return `
      ${header}
      <div class="session-empty">
        <div class="session-empty-copy">当前项目还没有产物。</div>
      </div>
    `;
  }
  return `${header}${artifacts.map((artifact) => `
    <div class="artifact-row" data-artifact-preview-path="${escapeHtml(artifact.path)}" role="button" tabindex="0" title="预览 ${escapeHtml(artifact.name)}">
      <span class="artifact-icon">${renderIcon(artifactIcon(artifact.name))}</span>
      <div class="artifact-main">
        <div class="artifact-name">${escapeHtml(artifact.name)}</div>
        <div class="artifact-meta">${formatBytes(artifact.size)} · ${new Date(artifact.mtimeMs).toLocaleString()}</div>
      </div>
      <button class="artifact-open" type="button" data-artifact-path="${escapeHtml(artifact.path)}" title="在 Finder 中显示" aria-label="在 Finder 中显示 ${escapeHtml(artifact.name)}">
        ${renderIcon("folder-open")}
      </button>
    </div>
  `).join("")}`;
}

// 与 chat 区一致：开启 GFM（含表格），关掉 async 拿同步字符串。
marked.setOptions({ gfm: true, breaks: false });

// 注册 artifact 语言映射用得到的高亮语言。toml 没有官方语法，用 ini 近似。
for (const [name, lang] of [
  ["bash", bash],
  ["c", c],
  ["cpp", cpp],
  ["css", css],
  ["go", go],
  ["ini", ini],
  ["toml", ini],
  ["java", java],
  ["javascript", javascript],
  ["json", json],
  ["markdown", markdown],
  ["python", python],
  ["ruby", ruby],
  ["rust", rust],
  ["scss", scss],
  ["sql", sql],
  ["typescript", typescript],
  ["xml", xml],
  ["yaml", yaml],
] as const) {
  hljs.registerLanguage(name, lang);
}

/** markdown 文本渲染成消毒后的 HTML，供 artifact 预览内联展示。 */
function renderMarkdownHtml(text: string): string {
  const html = marked.parse(text, { async: false });
  return DOMPurify.sanitize(html);
}

/** 代码文本做语法高亮。语言已知且被 highlight.js 支持时按语言高亮，否则自动识别。 */
function highlightCode(text: string, language?: string): string {
  if (language && hljs.getLanguage(language)) {
    return hljs.highlight(text, { language }).value;
  }
  return hljs.highlightAuto(text).value;
}

function renderArtifactPreview(preview: ArtifactPreview): string {
  const head = `
    <div class="artifact-preview-head">
      <button class="artifact-preview-back" type="button" data-artifact-preview-close title="返回列表" aria-label="返回列表">
        ${renderIcon("arrow-left")}
      </button>
      <span class="artifact-preview-icon">${renderIcon(artifactIcon(preview.name))}</span>
      <span class="artifact-preview-name" title="${escapeHtml(preview.path)}">${escapeHtml(preview.name)}</span>
      <span class="artifact-preview-meta">${formatBytes(preview.size)}${preview.language ? ` · ${escapeHtml(preview.language)}` : ""}</span>
      <button class="artifact-preview-open" type="button" data-artifact-path="${escapeHtml(preview.path)}" title="在 Finder 中显示" aria-label="在 Finder 中显示">
        ${renderIcon("folder-open")}
      </button>
    </div>
  `;
  const truncatedNote = preview.truncated
    ? `<div class="artifact-preview-note">内容较大，仅显示前 512KB。</div>`
    : "";

  if (preview.kind === "image" && preview.dataUrl) {
    return `${head}<div class="artifact-preview-body artifact-preview-image"><img src="${preview.dataUrl}" alt="${escapeHtml(preview.name)}" /></div>`;
  }
  if (preview.kind === "pdf" && preview.dataUrl) {
    return `${head}<div class="artifact-preview-body artifact-preview-frame"><iframe src="${preview.dataUrl}" title="${escapeHtml(preview.name)}"></iframe></div>`;
  }
  if (preview.kind === "html" && preview.dataUrl) {
    return `${head}<div class="artifact-preview-body artifact-preview-frame"><iframe src="${preview.dataUrl}" title="${escapeHtml(preview.name)}" sandbox="allow-scripts allow-popups allow-forms"></iframe></div>`;
  }
  if (preview.kind === "markdown") {
    return `${head}${truncatedNote}<div class="artifact-preview-body"><div class="artifact-preview-markdown markdown-body">${renderMarkdownHtml(preview.text ?? "")}</div></div>`;
  }
  if (preview.kind === "text") {
    return `${head}${truncatedNote}<div class="artifact-preview-body"><pre class="artifact-preview-code hljs"><code>${highlightCode(preview.text ?? "", preview.language)}</code></pre></div>`;
  }
  return `${head}<div class="artifact-preview-body artifact-preview-empty">${escapeHtml(preview.reason ?? "无法内联预览此文件。")}</div>`;
}

function renderTerminalEntries(entries: TerminalEntry[]): string {
  const rows = entries.length === 0
    ? `<div class="terminal-empty">命令执行后，这里会显示最新输出。</div>`
    : entries.map((entry) => `
        <div class="terminal-line terminal-line-${entry.kind}">
          <span class="terminal-prefix">${entry.kind === "command" ? "$" : ">"}</span>
          <span class="terminal-text">${escapeHtml(entry.text)}</span>
        </div>
      `).join("");

  return `
    <div class="terminal-view-panel">
      <div class="file-panel-header">终端输出</div>
      <div class="terminal-scroll">${rows}</div>
    </div>
  `;
}

/**
 * Shell 槽位片段 + 单一布局所有者（P0）。
 *
 * React AppShell 渲染外壳骨架；renderShell 把下列片段填进槽位
 * （[data-slot=...] / [data-composer-dock] / [data-overlay-layer]）。
 * 若 React 外壳缺失，回退到 legacyShellTemplate（完整 vanilla 模板）。
 * 片段与 legacy 模板字节级同源：legacy 由同一批片段拼装而成。
 */

/** React 外壳就绪前最多等待的轮数（每轮 80ms；与 entry.tsx 挂载重试一致）。 */
const SHELL_WAIT_ATTEMPTS = 25;

function shellRiskBarTemplate(): string {
  return `
    <div class="execution-risk-bar" data-execution-risk-bar hidden>
        <span class="execution-risk-icon" aria-hidden="true">⚠</span>
        <span class="execution-risk-text" data-execution-risk-text>本地执行：命令直接以当前用户权限运行，无隔离。</span>
      </div>
  `;
}

function shellTitlebarTemplate(): string {
  return `
      <div class="desktop-titlebar">
        <div class="titlebar-left">
          <div class="titlebar-switch" data-titlebar-switch role="button" tabindex="0" title="切换主题" aria-label="切换主题">
            <div class="titlebar-switch-track">
              <div class="titlebar-switch-thumb" data-titlebar-switch-thumb></div>
            </div>
          </div>
        </div>
        <div class="titlebar-right">
          <button class="titlebar-action" type="button" data-docs-open title="打开文档" aria-label="打开文档">
            <i class="codicon codicon-github" aria-hidden="true"></i>
          </button>
          <button
            class="titlebar-action"
            type="button"
            data-shortcuts-open
            title="快捷键与心智模型"
            aria-label="快捷键与心智模型"
          >
            ${renderIcon("keyboard")}
          </button>
          <button class="titlebar-action title-settings-button" type="button" data-settings-open title="设置" aria-label="设置">
            ${renderIcon("settings")}
          </button>
        </div>
      </div>
  `;
}

function leftPaneExpandedTemplate(appInfo: AppInfo): string {
  return `

            <div class="pane-topbar">
              <button class="new-task-button" type="button" data-new-task>新建任务</button>
            </div>
            <div class="pane-section-label" data-section-label>会话历史</div>
            <div class="session-list" data-session-list></div>
            <div class="skills-panel" data-skills-panel hidden>
              <div id="execution-context-section" style="display:none; margin-bottom:8px; border-bottom:1px solid var(--border); padding-bottom:8px;"></div>
              <div class="skills-list" data-skills-list></div>
              <div class="skills-manager">
                <div class="skills-install-row">
                  <input
                    class="skills-install-input"
                    data-skills-install-source
                    type="text"
                    placeholder="Git URL 或本地目录（安装 Skill）"
                    spellcheck="false"
                  />
                  <label class="skills-install-trust" title="安装后立即授予信任（安装 ≠ 信任，默认不授予）">
                    <input type="checkbox" data-skills-install-trust /> 信任
                  </label>
                  <button class="skills-install-btn" type="button" data-skills-install>安装</button>
                  <button class="skill-action" type="button" data-skills-refresh title="重新发现 Skill 目录">刷新</button>
                </div>
              </div>
            </div>
            <div class="left-footer">
              <div class="user-menu" data-user-menu>
                <button
                  class="user-chip"
                  type="button"
                  data-user-menu-toggle
                  aria-haspopup="menu"
                  aria-expanded="false"
                  title="账户与设置"
                >
                  <span class="user-avatar">${escapeHtml(appInfo.userName.charAt(0).toUpperCase())}</span>
                  <span class="user-name">${escapeHtml(appInfo.userName)}</span>
                  <span class="user-chip-chevron" aria-hidden="true">${renderIcon("chevron-down")}</span>
                </button>
                <div class="user-menu-dropdown" data-user-menu-dropdown hidden role="menu">
                  <div class="user-menu-header">
                    <span class="user-avatar">${escapeHtml(appInfo.userName.charAt(0).toUpperCase())}</span>
                    <div class="user-menu-meta">
                      <div class="user-menu-name">${escapeHtml(appInfo.userName)}</div>
                      <div class="user-menu-status" data-user-menu-status>未登录</div>
                    </div>
                  </div>
                  <div class="user-menu-divider"></div>
                  <button class="user-menu-item" type="button" role="menuitem" data-user-menu-wechat>
                    <span class="user-menu-item-icon wechat">${renderWechatIcon()}</span>
                    <span>扫码看文档</span>
                  </button>
                  <button class="user-menu-item" type="button" role="menuitem" data-user-menu-onboarding>
                    <span class="user-menu-item-icon">${renderIcon("wrench")}</span>
                    <span>首次设置</span>
                  </button>
                  <button class="user-menu-item" type="button" role="menuitem" data-user-menu-settings>
                    <span class="user-menu-item-icon">${renderIcon("settings")}</span>
                    <span>设置</span>
                  </button>
                  <button class="user-menu-item" type="button" role="menuitem" data-user-menu-docs>
                    <span class="user-menu-item-icon">${renderIcon("file-text")}</span>
                    <span>文档</span>
                  </button>
                </div>
              </div>
              <div class="left-footer-actions">
                <button class="icon-button" type="button" data-pin-sidebar title="钉住侧栏">
                  ${renderIcon("pin")}
                </button>
                <button class="icon-button" type="button" data-theme-toggle title="切换主题">
                  ${renderIcon("moon")}
                </button>
                <button class="icon-button" type="button" data-collapse-left title="折叠左栏">
                  ${renderIcon("panel-left-close")}
                </button>
              </div>
            </div>
          
  `;
}

function leftPaneCollapsedTemplate(appInfo: AppInfo): string {
  return `

            <button class="collapsed-expand" type="button" data-expand-left title="展开左栏">
              ${renderIcon("panel-left-open")}
            </button>
            <button class="collapsed-icon" type="button" data-new-task title="新建任务">
              ${renderIcon("plus")}
            </button>
            <button class="collapsed-icon" type="button" data-open-latest title="最近会话">
              ${renderIcon("history")}
            </button>
            <div class="collapsed-bottom">
              <button class="collapsed-icon" type="button" data-theme-toggle title="切换主题">
                ${renderIcon("moon")}
              </button>
              <button
                class="collapsed-icon user"
                type="button"
                data-user-menu-toggle
                title="账户与设置"
                aria-haspopup="menu"
                aria-expanded="false"
              >
                <span class="user-avatar small">${escapeHtml(appInfo.userName.charAt(0).toUpperCase())}</span>
              </button>
            </div>
          
  `;
}

function centerTopbarTemplate(runtime: RuntimeState): string {
  return `

            <div class="center-title" data-task-title>新建任务</div>
            <div class="center-header-side">
              <button class="center-pill center-pill-button" type="button" data-select-project title="${escapeHtml(runtime.projectPath)}">
                <span class="center-pill-icon" aria-hidden="true">${renderIcon("folder")}</span>
                <span data-project-label>${escapeHtml(projectLabel(runtime))}</span>
              </button>
              <span class="center-pill center-pill-status ${sandboxPresenceClass(runtime)}" data-sandbox-pill>
                <span class="center-pill-icon" data-sandbox-backend-icon aria-hidden="true">${renderIcon(sandboxBackendIconName(runtime))}</span>
                <span data-sandbox-backend>${sandboxBackendLabel(runtime)}</span>
              </span>
            </div>
          
  `;
}

function composerDockMentionTemplate(): string {
  return `
            <div class="mention-popup" data-mention-popup hidden></div>
            <!-- D3.4-2: the React Composer mounts here.  It stays hidden
                 until entry.tsx signals readiness (data-composer-react);
                 the vanilla composer remains the live one until then. -->

  `;
}

function composerFloatingTemplate(): string {
  return `
            <div class="composer composer-floating">
              <textarea id="prompt" placeholder="给 electromind 下达任务，输入 @ 引用文件"></textarea>
              <div class="composer-actions">
                <div class="composer-actions-start">
                  <button
                    type="button"
                    class="composer-btn skills-button"
                    data-skills-open
                    title="Skills"
                    aria-label="打开 Skills 面板"
                  >
                    ${renderIcon("plug")}
                  </button>
                  <button
                    type="button"
                    class="composer-btn yolo-btn"
                    data-yolo-toggle
                    title="自动审批：关闭（点击开启 YOLO 模式）"
                    aria-label="YOLO 模式"
                  >
                    ${renderIcon("zap")}
                  </button>
                  <button
                    type="button"
                    class="history-dock-dot"
                    data-history-dock
                    hidden
                    title="展开会话列表"
                    aria-label="展开会话列表"
                  >
                    ${renderIcon("history")}
                  </button>
                  <div class="desktop-composer-hint" data-composer-hint hidden>
                    <span class="desktop-composer-hint-text" data-last-error></span>
                    <button
                      type="button"
                      class="desktop-composer-hint-close"
                      data-clear-last-error
                      title="关闭"
                      aria-label="关闭错误提示"
                    >
                      ${renderIcon("x")}
                    </button>
                  </div>
                </div>
                <div class="composer-actions-end">
                  <span data-context-usage-mount></span>
                  <button class="composer-btn primary" data-send-message title="发送">
                    ${renderIcon("arrow-up")}
                  </button>
                </div>
              </div>
            </div>
  `;
}

function rightPaneTemplate(): string {
  return `

            <div class="pane-topbar right-topbar">
              <div class="tab-group" role="tablist" aria-label="右侧面板">
                <button class="tab-button" type="button" data-tab="plan">计划</button>
                <button class="tab-button" type="button" data-tab="changes">变更</button>
                <button class="tab-button active" type="button" data-tab="files">文件</button>
                <button class="tab-button" type="button" data-tab="artifacts">产物</button>
                <button class="tab-button" type="button" data-tab="jobs">任务</button>
                <button class="tab-button" type="button" data-tab="runtime">运行时</button>
                <button class="tab-button" type="button" data-tab="logs">日志</button>
              </div>
              <div class="right-topbar-actions">
                <button
                  class="icon-button inspector-pin-button"
                  type="button"
                  data-inspector-pin
                  title="钉住（切换任务时保持打开）"
                  aria-pressed="false"
                >
                  ${renderIcon("pin-off")}
                </button>
                <button
                  class="icon-button"
                  type="button"
                  data-inspector-close
                  title="关闭面板 (Esc)"
                  aria-label="关闭面板"
                >
                  ${renderIcon("panel-right-close")}
                </button>
              </div>
            </div>

            <div class="right-content">
              <section class="right-view" data-view="plan">
                <div class="inspector-view-body" data-inspector-view="plan"></div>
              </section>

              <section class="right-view" data-view="changes">
                <div class="inspector-view-body" data-inspector-view="changes"></div>
              </section>

              <section class="right-view active" data-view="files">
                <div class="file-panel-header project-host-header">
                  <span class="file-panel-title">项目文件</span>
                  <button
                    class="file-panel-refresh"
                    type="button"
                    data-refresh-project
                    title="刷新项目目录"
                    aria-label="刷新项目目录"
                  >
                    ${renderIcon("refresh-cw")}
                  </button>
                </div>
                <div class="file-panel project-files-pane">
                  <div class="file-tree" data-project-tree></div>
                </div>
              </section>

              <section class="right-view" data-view="artifacts">
                <div class="file-panel-header">
                  <span class="file-panel-title">产物</span>
                </div>
                <div class="artifacts-panel" data-artifacts-panel>
                  <div class="artifacts-list" data-artifacts-list></div>
                  <div class="artifact-preview" data-artifact-preview hidden></div>
                </div>
              </section>

              <section class="right-view" data-view="jobs">
                <div class="inspector-view-body" data-inspector-view="jobs"></div>
              </section>

              <section class="right-view" data-view="runtime">
                <div class="runtime-status" data-runtime-status></div>
                <div class="file-panel">
                  <div class="file-panel-header">
                    <span>文件系统</span>
                    <button
                      class="file-panel-refresh"
                      type="button"
                      data-refresh-sandbox
                      title="刷新沙箱文件"
                      aria-label="刷新沙箱文件"
                    >
                      ${renderIcon("refresh-cw")}
                    </button>
                  </div>
                  <div class="file-tree" data-file-tree></div>
                </div>
              </section>

              <section class="right-view" data-view="logs">
                <div class="logs-panel-header">
                  <span class="file-panel-title">日志</span>
                  <button class="file-panel-refresh" type="button" data-open-log-dir title="打开日志目录" aria-label="打开日志目录">
                    ${renderIcon("folder-open")}
                  </button>
                </div>
                <div class="terminal-panel" data-terminal-panel></div>
              </section>
            </div>

            <div class="right-footer" data-right-footer>
              <div class="resource-strip" data-resource-strip>
                <div class="resource-item">
                  <span class="resource-icon">${renderIcon("activity")}</span>
                  <div class="resource-track"><span data-resource-bar="cpu"></span></div>
                  <span class="resource-value" data-resource-value="cpu">0%</span>
                </div>
                <div class="resource-item">
                  <span class="resource-icon">${renderIcon("cpu")}</span>
                  <div class="resource-track"><span data-resource-bar="memory"></span></div>
                  <span class="resource-value" data-resource-value="memory">0 GB</span>
                </div>
                <div class="resource-item">
                  <span class="resource-icon">${renderIcon("database")}</span>
                  <div class="resource-track"><span data-resource-bar="disk"></span></div>
                  <span class="resource-value" data-resource-value="disk">2.4 GB</span>
                </div>
              </div>
            </div>
          
  `;
}

function overlayTemplate(): string {
  return `
      <div class="desktop-modal setup-guard-modal" data-onboarding-modal hidden>
        <div class="desktop-modal-backdrop setup-guard-backdrop" data-onboarding-close aria-hidden="true"></div>
        <section class="desktop-modal-card onboarding-modal-card" role="dialog" aria-modal="true" aria-labelledby="onboarding-title">
          <div class="desktop-modal-header">
            <div id="onboarding-title" class="desktop-modal-title">首次设置</div>
            <button class="modal-close-button" type="button" data-onboarding-close title="关闭" aria-label="关闭">
              ${renderIcon("x")}
            </button>
          </div>
          <div class="desktop-modal-body" data-onboarding-body></div>
        </section>
      </div>
      <div class="desktop-modal" data-new-session-modal hidden>
        <div class="desktop-modal-backdrop" data-new-session-close></div>
        <section class="desktop-modal-card new-session-modal-card" role="dialog" aria-modal="true" aria-labelledby="new-session-title">
          <div class="desktop-modal-header">
            <div id="new-session-title" class="desktop-modal-title">新建任务</div>
            <button class="modal-close-button" type="button" data-new-session-close title="关闭" aria-label="关闭">
              ${renderIcon("x")}
            </button>
          </div>
          <div class="desktop-modal-body" data-new-session-body></div>
        </section>
      </div>
      <div class="desktop-modal" data-thread-meta-modal hidden>
        <div class="desktop-modal-backdrop" data-thread-meta-close></div>
        <section class="desktop-modal-card" role="dialog" aria-modal="true" aria-labelledby="thread-meta-title">
          <div class="desktop-modal-header">
            <div id="thread-meta-title" class="desktop-modal-title">会话信息</div>
            <button class="modal-close-button" type="button" data-thread-meta-close title="关闭" aria-label="关闭">
              ${renderIcon("x")}
            </button>
          </div>
          <div class="desktop-modal-body" data-thread-meta-body></div>
        </section>
      </div>
      <div class="desktop-modal" data-settings-modal hidden>
        <div class="desktop-modal-backdrop" data-settings-close></div>
        <section class="desktop-modal-card settings-modal-card" role="dialog" aria-modal="true" aria-labelledby="settings-title">
          <div class="desktop-modal-header">
            <div id="settings-title" class="desktop-modal-title">设置</div>
            <button class="modal-close-button" type="button" data-settings-close title="关闭" aria-label="关闭">
              ${renderIcon("x")}
            </button>
          </div>
          <div class="desktop-modal-body" data-settings-body></div>
        </section>
      </div>
      <div class="desktop-modal" data-docs-qr-modal hidden>
        <div class="desktop-modal-backdrop" data-docs-qr-close></div>
        <section class="desktop-modal-card docs-qr-modal-card" role="dialog" aria-modal="true" aria-labelledby="docs-qr-title">
          <div class="desktop-modal-header">
            <div id="docs-qr-title" class="desktop-modal-title">扫码打开文档</div>
            <button class="modal-close-button" type="button" data-docs-qr-close title="关闭" aria-label="关闭">
              ${renderIcon("x")}
            </button>
          </div>
          <div class="desktop-modal-body docs-qr-body">
            <div class="docs-qr-frame">
              <canvas data-docs-qr-canvas width="220" height="220" aria-label="electromind 文档站二维码"></canvas>
            </div>
            <p class="docs-qr-hint">微信扫一扫，在手机上阅读 electromind 文档</p>
            <button class="new-session-primary docs-qr-open" type="button" data-docs-qr-open>在浏览器中打开</button>
          </div>
        </section>
      </div>
      <div class="desktop-modal" data-shortcuts-modal hidden>
        <div class="desktop-modal-backdrop" data-shortcuts-close></div>
        <section class="desktop-modal-card shortcuts-modal-card" role="dialog" aria-modal="true" aria-labelledby="shortcuts-title">
          <div class="desktop-modal-header">
            <div id="shortcuts-title" class="desktop-modal-title">快捷键与心智模型</div>
            <button class="modal-close-button" type="button" data-shortcuts-close title="关闭" aria-label="关闭">
              ${renderIcon("x")}
            </button>
          </div>
          <div class="desktop-modal-body shortcuts-modal-body">
            <div class="shortcuts-list">
              <div class="shortcut-item">
                <span class="shortcut-label">Command Palette</span>
                <div class="shortcut-keys">
                  <kbd class="key-modifier">
                    <span class="key-icon">⌘</span>
                    <span class="key-label">Command</span>
                  </kbd>
                  <kbd>K</kbd>
                </div>
              </div>
              <div class="shortcut-item">
                <span class="shortcut-label">切换 Ask / Plan / Agent</span>
                <div class="shortcut-keys">
                  <kbd class="key-modifier">
                    <span class="key-icon">⌘</span>
                    <span class="key-label">Command</span>
                  </kbd>
                  <kbd>.</kbd>
                </div>
              </div>
              <div class="shortcut-item">
                <span class="shortcut-label">新建 Thread</span>
                <div class="shortcut-keys">
                  <kbd class="key-modifier">
                    <span class="key-icon">⌘</span>
                    <span class="key-label">Command</span>
                  </kbd>
                  <kbd>N</kbd>
                </div>
              </div>
              <div class="shortcut-item">
                <span class="shortcut-label">聚焦输入框</span>
                <div class="shortcut-keys">
                  <kbd class="key-modifier">
                    <span class="key-icon">⌘</span>
                    <span class="key-label">Command</span>
                  </kbd>
                  <kbd>L</kbd>
                </div>
              </div>
              <div class="shortcut-item">
                <span class="shortcut-label">展开 / 收起 Threads</span>
                <div class="shortcut-keys">
                  <kbd class="key-modifier">
                    <span class="key-icon">⌘</span>
                    <span class="key-label">Command</span>
                  </kbd>
                  <kbd>B</kbd>
                </div>
              </div>
              <div class="shortcut-item">
                <span class="shortcut-label">打开 / 关闭 Inspector</span>
                <div class="shortcut-keys">
                  <kbd class="key-modifier">
                    <span class="key-icon">⌘</span>
                    <span class="key-label">Command</span>
                  </kbd>
                  <kbd>I</kbd>
                </div>
              </div>
              <div class="shortcut-item">
                <span class="shortcut-label">停止当前 Run</span>
                <div class="shortcut-keys">
                  <kbd>Esc</kbd>
                </div>
              </div>
              <div class="shortcut-item">
                <span class="shortcut-label">排队下一任务</span>
                <div class="shortcut-keys">
                  <kbd class="key-modifier">
                    <span class="key-icon">⌘</span>
                    <span class="key-label">Command</span>
                  </kbd>
                  <kbd class="key-modifier">⇧</kbd>
                  <kbd>Enter</kbd>
                </div>
              </div>
            </div>
            <section class="mental-model" data-mental-model aria-label="心智模型演示">
              <div class="mental-model-heading">
                <div class="mental-model-title">一条 Thread，两处绑定</div>
              </div>
              <div class="mental-carousel" data-mental-carousel>
                <button
                  type="button"
                  class="mental-carousel-nav"
                  data-mental-prev
                  title="上一条"
                  aria-label="上一条"
                >
                  ${renderIcon("arrow-left")}
                </button>
                <div class="mental-carousel-viewport">
                  <div class="mental-carousel-track" data-mental-track>
                    <div class="mental-carousel-slide">
                      <div class="mental-carousel-slide-title">Thread</div>
                      <div class="mental-carousel-slide-body">
                        每次对话落在一条 Thread 上：消息历史、配置与工作区都绑在一起。
                      </div>
                    </div>
                    <div class="mental-carousel-slide">
                      <div class="mental-carousel-slide-title">Project</div>
                      <div class="mental-carousel-slide-body">
                        Thread 绑定你的 Project（宿主目录）。右侧「项目」看的就是这里。
                      </div>
                    </div>
                    <div class="mental-carousel-slide">
                      <div class="mental-carousel-slide-title">Agent Computer</div>
                      <div class="mental-carousel-slide-body">
                        同时绑定一台 Agent Computer（沙箱）。右侧「沙箱」看的就是它的工作区。
                      </div>
                    </div>
                    <div class="mental-carousel-slide">
                      <div class="mental-carousel-slide-title">Artifacts</div>
                      <div class="mental-carousel-slide-body">
                        Artifacts 在 Project 里（<code>project/artifacts/</code>）。
                        <code>copy_from_host</code> 从项目拉进沙箱，
                        <code>copy_to_host</code> 交回该目录。
                      </div>
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  class="mental-carousel-nav"
                  data-mental-next
                  title="下一条"
                  aria-label="下一条"
                >
                  ${renderIcon("chevron-right")}
                </button>
              </div>
              <div class="mental-carousel-dots" data-mental-dots role="tablist" aria-label="说明页"></div>
              <div class="mental-model-stage" data-mental-stage>
                <svg class="mental-model-links" viewBox="0 0 360 120" aria-hidden="true">
                  <path
                    class="mental-link mental-link-project"
                    d="M180 28 C120 28, 90 52, 78 78"
                    fill="none"
                    stroke-linecap="round"
                  />
                  <path
                    class="mental-link mental-link-agent"
                    d="M180 28 C240 28, 270 52, 288 78"
                    fill="none"
                    stroke-linecap="round"
                  />
                  <circle class="mental-packet mental-packet-project" r="3.5" />
                  <circle class="mental-packet mental-packet-agent" r="3.5" />
                </svg>
                <div class="mental-bridge" aria-hidden="true">
                  <span class="mental-bridge-line"></span>
                  <span class="mental-bridge-packet mental-bridge-packet-out"></span>
                  <span class="mental-bridge-packet mental-bridge-packet-in"></span>
                </div>
                <div class="mental-node mental-node-thread">
                  <span class="mental-node-icon">${renderIcon("activity")}</span>
                  <span class="mental-node-label">Thread</span>
                  <span class="mental-node-sub">会话</span>
                </div>
                <div class="mental-node mental-node-project">
                  <span class="mental-node-icon">${renderIcon("folder")}</span>
                  <span class="mental-node-label">Project</span>
                  <span class="mental-node-sub">你的项目目录</span>
                  <div class="mental-nested mental-nested-artifacts">
                    <span class="mental-nested-label">artifacts/</span>
                    <span class="mental-nested-methods">
                      <span>copy_from_host</span>
                      <span>copy_to_host</span>
                    </span>
                  </div>
                </div>
                <div class="mental-node mental-node-agent">
                  <span class="mental-node-icon">${renderIcon("hard-drive")}</span>
                  <span class="mental-node-label">Agent Computer</span>
                  <span class="mental-node-sub">沙箱工作区</span>
                </div>
              </div>
            </section>
          </div>
        </section>
      </div>
      <div class="desktop-modal confirm-modal" data-confirm-modal hidden>
        <div class="desktop-modal-backdrop" data-confirm-cancel></div>
        <section class="desktop-modal-card confirm-modal-card" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-message">
          <div class="confirm-modal-body">
            <div class="confirm-modal-icon" data-confirm-icon aria-hidden="true">${renderIcon("circle-alert")}</div>
            <div class="confirm-modal-text">
              <div id="confirm-title" class="confirm-modal-title" data-confirm-title></div>
              <div id="confirm-message" class="confirm-modal-message" data-confirm-message></div>
            </div>
          </div>
          <div class="confirm-modal-actions">
            <button class="new-session-secondary" type="button" data-confirm-cancel-button></button>
            <button class="confirm-modal-primary" type="button" data-confirm-accept-button></button>
          </div>
        </section>
      </div>
      <div class="tree-context-menu" data-tree-context-menu hidden role="menu">
        <button class="tree-context-item" type="button" data-context-copy="absolute" role="menuitem">
          <span class="tree-context-item-label">复制绝对路径</span>
        </button>
        <button class="tree-context-item" type="button" data-context-copy="relative" role="menuitem">
          <span class="tree-context-item-label">复制项目相对路径</span>
        </button>
      </div>
  `;
}

function legacyShellTemplate(appInfo: AppInfo, runtime: RuntimeState): string {
  return `
    <div class="desktop-root">
    <div class="desktop-shell ${platformClass(appInfo)}" data-shell>
      ${shellRiskBarTemplate()}
      ${shellTitlebarTemplate()}
      <div class="desktop-workbench" data-workbench>
        <aside class="pane pane-left" data-left-pane>
          <div class="pane-expanded">${leftPaneExpandedTemplate(appInfo)}</div>
          <div class="pane-collapsed">${leftPaneCollapsedTemplate(appInfo)}</div>
        </aside>
        <div class="pane-resizer" data-resizer="left"></div>
        <section class="pane pane-center">
          <div class="pane-topbar center-topbar">${centerTopbarTemplate(runtime)}</div>
          <div class="chat-log" data-chat-log></div>
          <div class="composer-dock" data-composer-dock>
            ${composerDockMentionTemplate()}
            <div class="composer-react" data-composer-react></div>
            ${composerFloatingTemplate()}
          </div>
        </section>
        <div class="pane-resizer" data-resizer="right" aria-hidden="true"></div>
        <aside class="pane pane-right" data-right-pane>
          <div class="pane-expanded">${rightPaneTemplate()}</div>
        </aside>
      </div>
    </div>
    ${overlayTemplate()}
    </div>
  `;
}

function waitForShellSlot(attempt = 0): Promise<HTMLElement | null> {
  const shell = document.querySelector<HTMLElement>(".desktop-shell[data-shell]");
  if (shell) {
    return Promise.resolve(shell);
  }
  if (attempt >= SHELL_WAIT_ATTEMPTS) {
    return Promise.resolve(null);
  }
  return new Promise((resolve) => {
    window.setTimeout(() => {
      resolve(waitForShellSlot(attempt + 1));
    }, 80);
  });
}

/** 把 vanilla 面板内容填进 React AppShell 的槽位。
 *  - [data-slot=titlebar / left-pane-expanded / left-pane-collapsed /
 *    center-topbar / right-pane]：innerHTML 直接填充；
 *  - [data-composer-dock]：追加 mention 弹层 + vanilla 兜底 composer
 *    （entry.tsx 挂载 React Composer 并置 ready 后由 CSS 隐藏）；
 *  - [data-overlay-layer]：模态 / 右键菜单等 fixed 浮层。
 */
function fillShellSlots(shell: HTMLElement, appInfo: AppInfo, runtime: RuntimeState): void {
  const fill = (slot: string, html: string): void => {
    const el = shell.querySelector<HTMLElement>(`[data-slot="${slot}"]`);
    if (el) {
      el.innerHTML = html;
    }
  };
  fill("titlebar", shellTitlebarTemplate());
  fill("left-pane-expanded", leftPaneExpandedTemplate(appInfo));
  fill("left-pane-collapsed", leftPaneCollapsedTemplate(appInfo));
  fill("center-topbar", centerTopbarTemplate(runtime));
  fill("right-pane", rightPaneTemplate());

  const dock = shell.querySelector<HTMLElement>("[data-composer-dock]");
  if (dock) {
    dock.insertAdjacentHTML(
      "beforeend",
      `${composerDockMentionTemplate()}${composerFloatingTemplate()}`,
    );
  }

  // OverlayLayer 是 .desktop-shell 的兄弟节点（AppShell 结构），
  // 不在 shell 内部 —— 必须从文档根查询。
  const overlay = document.querySelector<HTMLElement>("[data-overlay-layer]");
  if (overlay) {
    overlay.innerHTML = overlayTemplate();
  }
}

async function renderShell(appInfo: AppInfo, runtime: RuntimeState): Promise<void> {
  const root = document.querySelector<HTMLDivElement>("#app");
  if (!root) {
    return;
  }

  const shell = await waitForShellSlot();
  if (shell) {
    // React 外壳已就位 → 只填槽位，绝不重写 #app.innerHTML
    //（重写会摧毁 React 根，导致两个布局系统互相覆盖）。
    fillShellSlots(shell, appInfo, runtime);
    return;
  }

  // React 外壳缺失（bundle 未加载/渲染失败）→ 回退到完整 vanilla 模板。
  root.innerHTML = legacyShellTemplate(appInfo, runtime);
}
function resizePrompt(prompt: HTMLTextAreaElement): void {
  prompt.style.height = "0px";
  prompt.style.height = `${Math.min(prompt.scrollHeight, INPUT_MAX_HEIGHT_PX)}px`;
}

/** 把沙箱目录树拍平成相对路径清单，供 @ 引用补全。 */
function flattenSandboxTree(nodes: SandboxTreeNode[]): string[] {
  const paths: string[] = [];
  const walk = (list: SandboxTreeNode[]): void => {
    for (const node of list) {
      if (node.kind === "file") {
        paths.push(node.id);
      } else if (node.children) {
        walk(node.children);
      }
    }
  };
  walk(nodes);
  return paths;
}

const MENTION_MATCH = /(?:^|\s)@([^\s@]*)$/;
const MENTION_LIMIT = 8;

function scoreMention(pathText: string, query: string): number {
  if (!query) {
    return 1;
  }
  const lowerPath = pathText.toLowerCase();
  const lowerQuery = query.toLowerCase();
  const index = lowerPath.indexOf(lowerQuery);
  if (index < 0) {
    return -1;
  }
  const base = lowerPath.slice(lowerPath.lastIndexOf("/") + 1);
  if (base.startsWith(lowerQuery)) {
    return 3;
  }
  if (index === 0) {
    return 2;
  }
  return 1;
}

function filterMentions(files: MentionFile[], query: string): MentionFile[] {
  const scored: Array<{ file: MentionFile; score: number }> = [];
  for (const file of files) {
    const score = scoreMention(file.path, query);
    if (score < 0) {
      continue;
    }
    scored.push({ file, score });
  }
  scored.sort((a, b) => {
    if (b.score !== a.score) {
      return b.score - a.score;
    }
    return a.file.path.length - b.file.path.length;
  });
  return scored.slice(0, MENTION_LIMIT).map((item) => item.file);
}

function mentionSourceLabel(source: MentionSource): string {
  return source === "project" ? "项目" : "沙箱";
}

/** 引用文本前缀：项目文件用 user，沙箱文件用 sandbox，帮助 agent 区分来源。 */
function mentionSourcePrefix(source: MentionSource): string {
  return source === "sandbox" ? "sandbox" : "user";
}

/** 解析 @ 之后的查询串，识别 user:/sandbox: 前缀并剥离，返回来源过滤与纯查询。 */
function parseMentionQuery(raw: string): { source: MentionSource | null; query: string } {
  if (raw.startsWith("user:")) {
    return { source: "project", query: raw.slice(5) };
  }
  if (raw.startsWith("sandbox:")) {
    return { source: "sandbox", query: raw.slice(8) };
  }
  return { source: null, query: raw };
}

/** 交错合并两个来源的候选，保证沙箱文件也能出现在补全列表里。 */
function mergeMentions(project: MentionFile[], sandbox: MentionFile[]): MentionFile[] {
  const merged: MentionFile[] = [];
  const max = Math.max(project.length, sandbox.length);
  for (let index = 0; index < max; index += 1) {
    if (index < project.length) {
      merged.push(project[index]);
    }
    if (index < sandbox.length) {
      merged.push(sandbox[index]);
    }
  }
  return merged;
}

function findRequired<T extends Element>(selector: string): T {
  const node = document.querySelector<T>(selector);
  if (!node) {
    throw new Error(`missing element: ${selector}`);
  }
  return node;
}

function buildToolPreview(name: string, args: string): string {
  const commandMatch = /"cmd"\s*:\s*"([^"]+)"/.exec(args);
  if (commandMatch) {
    return commandMatch[1];
  }
  return summarize(`${name} ${args}`.trim(), 80) || name;
}

function isRoutineWireLog(text: string): boolean {
  return (
    text.includes("[wire] resume：已切到 thread") ||
    text.includes("[wire] resume: 已切到 thread") ||
    /^\[wire\]\s*(open|reset|list_threads)\b/i.test(text)
  );
}

function finishBootSplash(): void {
  const html = document.documentElement;
  html.dataset.boot = "done";
  const splash = document.getElementById("boot-splash");
  if (!splash) {
    return;
  }
  window.setTimeout(() => {
    splash.hidden = true;
  }, 200);
}

async function start(): Promise<void> {
  // 与壳层数据并行拉挡墙状态，避免主界面先露出来
  const [appInfo, initialRuntime, onboardingState] = await Promise.all([
    window.desktop.getAppInfo(),
    window.desktop.getRuntimeState(),
    window.desktop.getOnboardingState(),
  ]);
  await renderShell(appInfo, initialRuntime);
  mountToaster();

  const workbench = findRequired<HTMLElement>("[data-workbench]");
  const sessionList = findRequired<HTMLElement>("[data-session-list]");
  const sectionLabel = findRequired<HTMLElement>("[data-section-label]");
  const skillsPanel = findRequired<HTMLElement>("[data-skills-panel]");
  const skillsList = findRequired<HTMLElement>("[data-skills-list]");
  const fileTree = findRequired<HTMLElement>("[data-file-tree]");
  const projectTree = findRequired<HTMLElement>("[data-project-tree]");
  const treeContextMenu = findRequired<HTMLElement>("[data-tree-context-menu]");
  const terminalPanel = findRequired<HTMLElement>("[data-terminal-panel]");
  const artifactsList = findRequired<HTMLElement>("[data-artifacts-list]");
  const artifactsPanel = findRequired<HTMLElement>("[data-artifacts-panel]");
  const artifactPreview = findRequired<HTMLElement>("[data-artifact-preview]");
  const chatLog = findRequired<HTMLElement>("[data-chat-log]");
  const promptInput = findRequired<HTMLTextAreaElement>("#prompt");
  const mentionPopup = findRequired<HTMLElement>("[data-mention-popup]");
  const sendMessageButton = findRequired<HTMLButtonElement>("[data-send-message]");
  const composerHint = findRequired<HTMLElement>("[data-composer-hint]");
  const errorText = findRequired<HTMLElement>("[data-last-error]");
  const clearLastErrorButton = findRequired<HTMLButtonElement>("[data-clear-last-error]");
  const taskTitle = findRequired<HTMLElement>("[data-task-title]");
  const projectButton = findRequired<HTMLElement>("[data-select-project]");
  const projectText = findRequired<HTMLElement>("[data-project-label]");
  const sandboxBackendIcon = findRequired<HTMLElement>("[data-sandbox-backend-icon]");
  const sandboxBackend = findRequired<HTMLElement>("[data-sandbox-backend]");
  const sandboxPill = findRequired<HTMLElement>("[data-sandbox-pill]");
  const rightFooter = findRequired<HTMLElement>("[data-right-footer]");
  const threadMetaModal = findRequired<HTMLElement>("[data-thread-meta-modal]");
  const threadMetaBody = findRequired<HTMLElement>("[data-thread-meta-body]");
  const newSessionModal = findRequired<HTMLElement>("[data-new-session-modal]");
  const newSessionBody = findRequired<HTMLElement>("[data-new-session-body]");
  const settingsOpenButton = findRequired<HTMLButtonElement>("[data-settings-open]");
  const documentationButton = findRequired<HTMLButtonElement>("[data-docs-open]");
  const shortcutsOpenButton = findRequired<HTMLButtonElement>("[data-shortcuts-open]");
  const shortcutsModal = findRequired<HTMLElement>("[data-shortcuts-modal]");
  const titlebarSwitch = findRequired<HTMLElement>("[data-titlebar-switch]");
  const titlebarSwitchThumb = findRequired<HTMLElement>("[data-titlebar-switch-thumb]");
  const settingsModal = findRequired<HTMLElement>("[data-settings-modal]");
  const settingsBody = findRequired<HTMLElement>("[data-settings-body]");
  const docsQrModal = findRequired<HTMLElement>("[data-docs-qr-modal]");
  const docsQrCanvas = findRequired<HTMLCanvasElement>("[data-docs-qr-canvas]");
  const onboardingModal = findRequired<HTMLElement>("[data-onboarding-modal]");
  const onboardingBody = findRequired<HTMLElement>("[data-onboarding-body]");
  const confirmModal = findRequired<HTMLElement>("[data-confirm-modal]");
  const confirmTitle = findRequired<HTMLElement>("[data-confirm-title]");
  const confirmMessage = findRequired<HTMLElement>("[data-confirm-message]");
  const confirmAcceptButton = findRequired<HTMLButtonElement>("[data-confirm-accept-button]");
  const confirmCancelButton = findRequired<HTMLButtonElement>("[data-confirm-cancel-button]");

  const shell = findRequired<HTMLElement>("[data-shell]");

  function setSetupGuard(blocked: boolean): void {
    shell.classList.toggle("is-setup-blocked", blocked);
  }

  const onboarding = mountOnboarding({
    modal: onboardingModal,
    body: onboardingBody,
    onBlockedChange: setSetupGuard,
    onDone: () => {
      setSetupGuard(false);
      void refreshSessions();
    },
  });

  // 在会话列表等慢路径之前立刻上墙，再撤启动遮罩
  if (onboardingState.blocked || onboardingState.shouldShow) {
    onboarding.open(onboardingState);
  }
  finishBootSplash();

  // Pending user input awaiting a terminal input/state ACK.
  // Reused on retry so the backend can deduplicate via request_id.
  let pendingInputRequest: { text: string; requestId: string } | null = null;

  const uiState = {
    theme: readStoredTheme(),
    activeTab: "files" as PanelTab,
    leftCollapsed: false,
    sidebarDocked: false,
    sidebarPinned: readStoredSidebarPinned(),
    leftWidth: LEFT_PANE_WIDTH_PX,
    activityState: "sleeping" as ActivityState,
    terminalEntries: [] as TerminalEntry[],
    expandedTree: new Set<string>(),
    expandedProjectTree: new Set<string>(),
    sandboxTree: [] as SandboxTreeNode[],
    projectTreeNodes: [] as SandboxTreeNode[],
    projectLoadedPath: "",
    sandboxStatus: {
      threadId: "",
      backend: "",
      alive: false,
      workdir: "",
    } as SandboxStatus,
    sandboxLoadedThreadId: "",
    artifacts: [] as ArtifactSummary[],
    sessions: [] as ThreadSummary[],
    skills: [] as Skill[],
    skillsState: null as SkillsStatePayload | null,
    // 七: skills/list 的实时目录（安装/更新/移除后刷新；SkillsState 来自
    // 按 Run 冻结的运行时快照，不含操作后的新 Skill）
    skillsCatalog: null as SkillViewItem[] | null,
    skillsPanel: initialSkillsPanelState(),
    executionContextState: null as ExecutionContextStatePayload | null,
    hpcSubmissions: [] as HpcSubmissionsPayload["submissions"],
    runtime: initialRuntime,
  };
  const historyDockButton = findRequired<HTMLButtonElement>("[data-history-dock]");
  const skillsButton = findRequired<HTMLButtonElement>("[data-skills-open]");
  const yoloButton = findRequired<HTMLButtonElement>("[data-yolo-toggle]");
  const contextUsageMount = findRequired<HTMLElement>("[data-context-usage-mount]");
  const pinSidebarButton = findRequired<HTMLButtonElement>("[data-pin-sidebar]");
  const refreshProjectButton = findRequired<HTMLButtonElement>("[data-refresh-project]");
  let keepSidebarOpen = false;
  let artifactPreviewPath = "";
  let contextNodePath = "";

  renderArtifactList();

  // Harness Spine: ThreadStore is the single source of truth for the
  // message timeline.  The renderer subscribes to the store and only
  // renders the currently selected thread's items.
  const threadStore = getThreadStore();
  let lastRenderedThreadId: string | null = null;
  threadStore.subscribe((state) => {
    // Store 是单一事实来源：vanilla 的 runtime.currentThreadId 只在有后端
    // runtime 状态时可用；无后端（onboarding / CDP 测试）时回退到 store 的
    // activeThreadId，保证 Timeline 始终按 store 渲染。
    const currentId =
      uiState.runtime.currentThreadId || threadStore.getActiveThreadId() || null;
    if (!currentId) return;
    const thread = state.threads[currentId];
    if (!thread) return;
    if (currentId !== lastRenderedThreadId) {
      chatRenderer.resetRendered();
      chatRenderer.clear();
      lastRenderedThreadId = currentId;
    }
    // D3.3/D3.4: the renderer consumes the PROJECTED task timeline
    // (single source of truth — the v1 raw-items path was removed).
    chatRenderer.syncTimeline(thread.timeline);
    // Activity state is a pure projection of the store (single source).
    if (uiState.activityState !== state.activityState) {
      uiState.activityState = state.activityState;
      applyActivityState();
    }
  });

  const chatRenderer = new MessageRenderer(chatLog, (toolCallId, approved) => {
    // Harness Spine: look up the full approval scope (approval_id, thread_id,
    // run_id) from the ThreadStore.  If the permit record is missing, do NOT
    // fall back to a scoped-less approval — refuse and let the user refresh.
    const store = getThreadStore();
    const activeThread = store.getActiveThread();
    const permit = activeThread?.pendingPermits.find(
      (p) => p.toolCallId === toolCallId,
    );
    if (!permit || !permit.approvalId || !permit.runId) {
      chatRenderer.showError(
        "审批记录缺失，无法提交。请刷新会话状态后重试。",
      );
      return;
    }
    const approvalId = permit.approvalId;
    const threadId = activeThread?.id ?? permit.threadId;
    const runId = permit.runId;
    if (approved) {
      void window.desktop.permitToolCall(toolCallId, approvalId, threadId, runId);
      return;
    }
    void window.desktop.denyToolCall(toolCallId, undefined, approvalId, threadId, runId);
  });
  const contextUsageRing = new ContextUsageRing(contextUsageMount);

  function applyTheme(): void {
    document.documentElement.dataset.theme = uiState.theme;
    window.localStorage.setItem("electromind-desktop-theme", uiState.theme);
    const lightOn = uiState.theme === "light";
    titlebarSwitch.dataset.on = String(lightOn);
    titlebarSwitch.setAttribute("aria-pressed", String(lightOn));
    titlebarSwitchThumb.style.transform = lightOn ? "translateX(14px)" : "translateX(0)";
  }

  function applyWorkbenchChrome(): void {
    const leftHidden = uiState.sidebarDocked;
    workbench.dataset.leftCollapsed = String(uiState.leftCollapsed);
    workbench.dataset.sidebarDocked = String(uiState.sidebarDocked);
    workbench.style.setProperty(
      "--left-pane-width",
      leftHidden
        ? "0px"
        : `${uiState.leftCollapsed ? LEFT_COLLAPSED_WIDTH_PX : uiState.leftWidth}px`,
    );
    workbench.style.setProperty(
      "--left-gap",
      leftHidden || uiState.leftCollapsed ? "0px" : "8px",
    );
    // --right-pane-width / --right-gap are owned by the InspectorController
    // (D3.2): the Inspector is default-closed and contextually opened.
    historyDockButton.hidden = !uiState.sidebarDocked;
  }

  function applyPinState(): void {
    pinSidebarButton.classList.toggle("active", uiState.sidebarPinned);
    pinSidebarButton.title = uiState.sidebarPinned ? "取消钉住" : "钉住侧栏";
    pinSidebarButton.innerHTML = renderIcon(
      uiState.sidebarPinned ? "pin" : "pin-off",
    );
    window.localStorage.setItem(
      "electromind-desktop-sidebar-pinned",
      uiState.sidebarPinned ? "1" : "0",
    );
  }

  function syncComposerDock(forceOpen = false): void {
    if (uiState.sidebarPinned) {
      keepSidebarOpen = false;
      uiState.sidebarDocked = false;
      applyWorkbenchChrome();
      return;
    }

    const focused = document.activeElement === promptInput;
    const hasText = promptInput.value.trim().length > 0;
    const streaming = uiState.activityState === "running";
    const composing = focused || hasText || streaming;

    if (forceOpen) {
      keepSidebarOpen = true;
      uiState.sidebarDocked = false;
      uiState.leftCollapsed = false;
      applyWorkbenchChrome();
      return;
    }

    if (keepSidebarOpen) {
      if (!composing) {
        keepSidebarOpen = false;
      } else {
        uiState.sidebarDocked = false;
        applyWorkbenchChrome();
        return;
      }
    }

    uiState.sidebarDocked = composing;
    applyWorkbenchChrome();
  }

  let metaModalCloseTimer = 0;
  let metaModalRequestId = 0;
  let settingsModalCloseTimer = 0;
  let settingsRequestId = 0;
  let docsQrModalCloseTimer = 0;
  let newSessionModalCloseTimer = 0;
  let newSessionRequestId = 0;
  let newSessionDraft = {
    backend: "container" as SandboxBackendOption,
    projectPath: "",
    sshHost: "",
    sshWorkdir: "~/electromind",
    image: "electromind:latest",
  };
  let newSessionOptionsCache: NewSessionOptions | null = null;

  function closeThreadMetaModal(): void {
    if (threadMetaModal.hidden) {
      return;
    }
    metaModalRequestId += 1;
    threadMetaModal.classList.remove("is-open");
    window.clearTimeout(metaModalCloseTimer);
    metaModalCloseTimer = window.setTimeout(() => {
      threadMetaModal.hidden = true;
      threadMetaBody.innerHTML = "";
    }, 140);
  }

  async function openThreadMetaModal(threadId: string): Promise<void> {
    const session = uiState.sessions.find((item) => item.id === threadId);
    const requestId = metaModalRequestId + 1;
    metaModalRequestId = requestId;
    window.clearTimeout(metaModalCloseTimer);
    threadMetaBody.innerHTML = renderThreadMetaSkeleton();
    threadMetaModal.hidden = false;
    window.requestAnimationFrame(() => {
      if (metaModalRequestId === requestId) {
        threadMetaModal.classList.add("is-open");
      }
    });
    try {
      const meta = await window.desktop.getThreadMeta(threadId);
      if (threadMetaModal.hidden || metaModalRequestId !== requestId) {
        return;
      }
      threadMetaBody.innerHTML = renderThreadMeta(meta, session);
    } catch (error) {
      if (threadMetaModal.hidden || metaModalRequestId !== requestId) {
        return;
      }
      const message = error instanceof Error ? error.message : String(error);
      threadMetaBody.innerHTML = `
        <div class="thread-meta-error">${escapeHtml(message)}</div>
      `;
    }
  }

  function closeSettingsModal(): void {
    if (settingsModal.hidden) {
      return;
    }
    settingsRequestId += 1;
    settingsModal.classList.remove("is-open");
    window.clearTimeout(settingsModalCloseTimer);
    settingsModalCloseTimer = window.setTimeout(() => {
      settingsModal.hidden = true;
      settingsBody.innerHTML = "";
    }, 140);
  }

  function closeDocsQrModal(): void {
    if (docsQrModal.hidden) {
      return;
    }
    docsQrModal.classList.remove("is-open");
    window.clearTimeout(docsQrModalCloseTimer);
    docsQrModalCloseTimer = window.setTimeout(() => {
      docsQrModal.hidden = true;
    }, 140);
  }

  function openDocsQrModal(): void {
    window.clearTimeout(docsQrModalCloseTimer);
    docsQrModal.hidden = false;
    window.requestAnimationFrame(() => {
      docsQrModal.classList.add("is-open");
    });
    void paintDocsQr(docsQrCanvas).catch(() => {
      const ctx = docsQrCanvas.getContext("2d");
      if (ctx) {
        ctx.clearRect(0, 0, docsQrCanvas.width, docsQrCanvas.height);
      }
    });
  }

  function bindSettingsHealthPanel(initialEnv: EnvironmentCheck): void {
    let currentEnv = initialEnv;

    function attachHandlers(root: HTMLElement): void {
      bindHealthPanel(root, {
        onRefresh: async () => {
          currentEnv = await window.desktop.refreshEnvironmentCheck();
          replacePanel();
        },
        onCopyCommands: async () => {
          await navigator.clipboard.writeText(INSTALL_COMMANDS);
          toast("已复制安装命令", { type: "success" });
        },
        onInstallElectromind: async () => {
          const result = await window.desktop.installElectromindCli();
          if (!result.ok) {
            toast(result.error ?? "安装失败", { type: "error" });
            return;
          }
          currentEnv = await window.desktop.refreshEnvironmentCheck();
          replacePanel();
          toast("electromind 已安装", { type: "success" });
        },
      });
    }

    function replacePanel(): void {
      const existing = settingsBody.querySelector<HTMLElement>(".health-panel");
      if (!existing) {
        return;
      }
      const wrapper = document.createElement("div");
      wrapper.innerHTML = renderHealthPanel(currentEnv);
      const next = wrapper.firstElementChild;
      if (!(next instanceof HTMLElement)) {
        return;
      }
      existing.replaceWith(next);
      attachHandlers(next);
    }

    const panel = settingsBody.querySelector<HTMLElement>(".health-panel");
    if (panel) {
      attachHandlers(panel);
    }
  }

  async function openSettingsModal(): Promise<void> {
    const requestId = settingsRequestId + 1;
    settingsRequestId = requestId;
    window.clearTimeout(settingsModalCloseTimer);
    settingsBody.innerHTML = renderThreadMetaSkeleton();
    settingsModal.hidden = false;
    window.requestAnimationFrame(() => {
      if (settingsRequestId === requestId) {
        settingsModal.classList.add("is-open");
      }
    });
    try {
      const [settings, env] = await Promise.all([
        window.desktop.getSettings(),
        window.desktop.refreshEnvironmentCheck(),
      ]);
      if (settingsModal.hidden || settingsRequestId !== requestId) {
        return;
      }
      settingsBody.innerHTML = renderSettings(settings, env);
      bindSettingsHealthPanel(env);
    } catch (error) {
      if (settingsModal.hidden || settingsRequestId !== requestId) {
        return;
      }
      const message = error instanceof Error ? error.message : String(error);
      settingsBody.innerHTML = `
        <div class="thread-meta-error">${escapeHtml(message)}</div>
      `;
    }
  }

  let shortcutsModalCloseTimer = 0;
  const mentalModel = findRequired<HTMLElement>("[data-mental-model]");
  const mentalTrack = findRequired<HTMLElement>("[data-mental-track]");
  const mentalDots = findRequired<HTMLElement>("[data-mental-dots]");
  const mentalPrev = findRequired<HTMLButtonElement>("[data-mental-prev]");
  const mentalNext = findRequired<HTMLButtonElement>("[data-mental-next]");
  const mentalSlides = Array.from(
    mentalTrack.querySelectorAll<HTMLElement>(".mental-carousel-slide"),
  );
  let mentalSlideIndex = 0;

  function stopMentalModelDemo(): void {
    mentalModel.classList.remove("is-playing");
  }

  function applyMentalCarousel(index: number): void {
    const total = mentalSlides.length;
    if (total === 0) {
      return;
    }
    mentalSlideIndex = ((index % total) + total) % total;
    mentalTrack.style.transform = `translateX(-${mentalSlideIndex * 100}%)`;
    mentalDots.querySelectorAll<HTMLButtonElement>("[data-mental-dot]").forEach((dot, i) => {
      const active = i === mentalSlideIndex;
      dot.classList.toggle("active", active);
      dot.setAttribute("aria-selected", active ? "true" : "false");
    });
    mentalPrev.disabled = mentalSlideIndex === 0;
    mentalNext.disabled = mentalSlideIndex === total - 1;
  }

  function buildMentalCarouselDots(): void {
    mentalDots.innerHTML = mentalSlides
      .map(
        (_, index) => `
      <button
        type="button"
        class="mental-carousel-dot"
        data-mental-dot="${index}"
        role="tab"
        aria-label="第 ${index + 1} 页"
        aria-selected="false"
      ></button>
    `,
      )
      .join("");
  }

  function layoutMentalBridge(): void {
    const stage = mentalModel.querySelector<HTMLElement>("[data-mental-stage]");
    const artifacts = mentalModel.querySelector<HTMLElement>(".mental-nested-artifacts");
    const agent = mentalModel.querySelector<HTMLElement>(".mental-node-agent");
    const bridge = mentalModel.querySelector<HTMLElement>(".mental-bridge");
    if (!stage || !artifacts || !agent || !bridge) {
      return;
    }
    const stageRect = stage.getBoundingClientRect();
    const artifactsRect = artifacts.getBoundingClientRect();
    const agentRect = agent.getBoundingClientRect();
    if (stageRect.width < 1 || artifactsRect.width < 1 || agentRect.width < 1) {
      return;
    }
    const left = Math.max(0, artifactsRect.right - stageRect.left);
    const right = Math.max(0, stageRect.right - agentRect.left);
    const top =
      (artifactsRect.top + artifactsRect.bottom) / 2 - stageRect.top - 7;
    bridge.style.left = `${left}px`;
    bridge.style.right = `${right}px`;
    bridge.style.top = `${top}px`;
  }

  function playMentalModelDemo(): void {
    stopMentalModelDemo();
    void mentalModel.offsetWidth;
    mentalModel.classList.add("is-playing");
    applyMentalCarousel(0);
    // 节点入场动画会改 transform，结束后再量一次对齐虚线。
    window.requestAnimationFrame(() => {
      layoutMentalBridge();
      window.setTimeout(layoutMentalBridge, 1800);
    });
  }

  buildMentalCarouselDots();
  applyMentalCarousel(0);

  mentalPrev.addEventListener("click", () => {
    applyMentalCarousel(mentalSlideIndex - 1);
  });
  mentalNext.addEventListener("click", () => {
    applyMentalCarousel(mentalSlideIndex + 1);
  });
  mentalDots.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const dot = target.closest<HTMLButtonElement>("[data-mental-dot]");
    if (!dot) {
      return;
    }
    const index = Number(dot.dataset.mentalDot);
    if (Number.isFinite(index)) {
      applyMentalCarousel(index);
    }
  });

  function openShortcutsModal(): void {
    window.clearTimeout(shortcutsModalCloseTimer);
    shortcutsModal.hidden = false;
    playMentalModelDemo();
    window.requestAnimationFrame(() => {
      shortcutsModal.classList.add("is-open");
    });
  }

  function closeShortcutsModal(): void {
    if (shortcutsModal.hidden) {
      return;
    }
    shortcutsModal.classList.remove("is-open");
    stopMentalModelDemo();
    window.clearTimeout(shortcutsModalCloseTimer);
    shortcutsModalCloseTimer = window.setTimeout(() => {
      shortcutsModal.hidden = true;
    }, 140);
  }

  type ConfirmOptions = {
    title: string;
    message: string;
    confirmText?: string;
    cancelText?: string;
    tone?: "danger" | "primary";
  };
  let confirmModalCloseTimer = 0;
  let resolveConfirm: ((value: boolean) => void) | null = null;

  function settleConfirm(result: boolean): void {
    if (confirmModal.hidden) {
      return;
    }
    const resolve = resolveConfirm;
    resolveConfirm = null;
    confirmModal.classList.remove("is-open");
    window.clearTimeout(confirmModalCloseTimer);
    confirmModalCloseTimer = window.setTimeout(() => {
      confirmModal.hidden = true;
    }, 140);
    resolve?.(result);
  }

  // 自定义二次确认对话框，替代 Electron 原生 dialog，样式与其它 desktop-modal 一致。
  function openConfirm(options: ConfirmOptions): Promise<boolean> {
    // 上一个确认还没关就先按取消结算，避免 promise 泄漏。
    resolveConfirm?.(false);
    resolveConfirm = null;
    confirmTitle.textContent = options.title;
    confirmMessage.textContent = options.message;
    confirmAcceptButton.textContent = options.confirmText ?? "确认";
    confirmCancelButton.textContent = options.cancelText ?? "取消";
    confirmModal.classList.toggle("is-danger", options.tone !== "primary");
    window.clearTimeout(confirmModalCloseTimer);
    confirmModal.hidden = false;
    window.requestAnimationFrame(() => {
      confirmModal.classList.add("is-open");
      confirmAcceptButton.focus();
    });
    return new Promise<boolean>((resolve) => {
      resolveConfirm = resolve;
    });
  }

  confirmAcceptButton.addEventListener("click", () => settleConfirm(true));
  confirmCancelButton.addEventListener("click", () => settleConfirm(false));
  confirmModal.addEventListener("click", (event) => {
    if ((event.target as HTMLElement).closest("[data-confirm-cancel]")) {
      settleConfirm(false);
    }
  });

  function syncNewSessionDraftFromDom(): void {
    const projectInput = newSessionBody.querySelector<HTMLInputElement>("[data-project-path]");
    if (projectInput) {
      newSessionDraft.projectPath = projectInput.value.trim();
    }
    const imageEl = newSessionBody.querySelector<HTMLInputElement>("[data-image]");
    if (imageEl) {
      newSessionDraft.image = imageEl.value.trim() || "electromind:latest";
    }
    const sshHostEl = newSessionBody.querySelector<HTMLInputElement>("[data-ssh-host]");
    if (sshHostEl) {
      newSessionDraft.sshHost = sshHostEl.value.trim();
    }
    const sshWorkdirInput = newSessionBody.querySelector<HTMLInputElement>("[data-ssh-workdir]");
    if (sshWorkdirInput) {
      newSessionDraft.sshWorkdir = sshWorkdirInput.value.trim() || "~/electromind";
    }
  }

  function closeSshHostDropdown(): void {
    const dropdown = newSessionBody.querySelector<HTMLElement>("[data-ssh-dropdown]");
    if (!dropdown) {
      return;
    }
    const menu = dropdown.querySelector<HTMLElement>("[data-ssh-dropdown-menu]");
    const trigger = dropdown.querySelector<HTMLButtonElement>("[data-ssh-dropdown-toggle]");
    if (menu) {
      menu.hidden = true;
    }
    dropdown.classList.remove("is-open");
    trigger?.setAttribute("aria-expanded", "false");
  }

  function closeImageDropdown(): void {
    const dropdown = newSessionBody.querySelector<HTMLElement>("[data-image-dropdown]");
    if (!dropdown) {
      return;
    }
    const menu = dropdown.querySelector<HTMLElement>("[data-image-dropdown-menu]");
    const trigger = dropdown.querySelector<HTMLButtonElement>("[data-image-dropdown-toggle]");
    if (menu) {
      menu.hidden = true;
    }
    dropdown.classList.remove("is-open");
    trigger?.setAttribute("aria-expanded", "false");
  }

  function toggleSshHostDropdown(): void {
    closeImageDropdown();
    const dropdown = newSessionBody.querySelector<HTMLElement>("[data-ssh-dropdown]");
    if (!dropdown) {
      return;
    }
    const menu = dropdown.querySelector<HTMLElement>("[data-ssh-dropdown-menu]");
    const trigger = dropdown.querySelector<HTMLButtonElement>("[data-ssh-dropdown-toggle]");
    if (!menu || !trigger) {
      return;
    }
    const open = menu.hidden;
    menu.hidden = !open;
    dropdown.classList.toggle("is-open", open);
    trigger.setAttribute("aria-expanded", String(open));
  }

  function toggleImageDropdown(): void {
    closeSshHostDropdown();
    const dropdown = newSessionBody.querySelector<HTMLElement>("[data-image-dropdown]");
    if (!dropdown) {
      return;
    }
    const menu = dropdown.querySelector<HTMLElement>("[data-image-dropdown-menu]");
    const trigger = dropdown.querySelector<HTMLButtonElement>("[data-image-dropdown-toggle]");
    if (!menu || !trigger) {
      return;
    }
    const open = menu.hidden;
    menu.hidden = !open;
    dropdown.classList.toggle("is-open", open);
    trigger.setAttribute("aria-expanded", String(open));
  }

  function selectSshHost(host: string): void {
    newSessionDraft.sshHost = host;
    const input = newSessionBody.querySelector<HTMLInputElement>("[data-ssh-host]");
    const label = newSessionBody.querySelector<HTMLElement>("[data-ssh-host-label]");
    if (input) {
      input.value = host;
    }
    if (label) {
      label.textContent = host || "选择 Host…";
      label.classList.toggle("is-placeholder", !host);
    }
    newSessionBody.querySelectorAll<HTMLElement>("[data-ssh-host-option]").forEach((option) => {
      const active = option.getAttribute("value") === host;
      option.classList.toggle("active", active);
      option.setAttribute("aria-selected", String(active));
    });
    closeSshHostDropdown();
  }

  function selectImage(image: string): void {
    newSessionDraft.image = image;
    const input = newSessionBody.querySelector<HTMLInputElement>("[data-image]");
    const label = newSessionBody.querySelector<HTMLElement>("[data-image-label]");
    if (input) {
      input.value = image;
    }
    if (label) {
      label.textContent = image;
    }
    newSessionBody.querySelectorAll<HTMLElement>("[data-image-option]").forEach((option) => {
      const active = option.getAttribute("value") === image;
      option.classList.toggle("active", active);
      option.setAttribute("aria-selected", String(active));
    });
    closeImageDropdown();
  }

  function paintNewSessionForm(): void {
    if (!newSessionOptionsCache) {
      return;
    }
    newSessionBody.innerHTML = renderNewSessionForm(newSessionOptionsCache, newSessionDraft);
  }

  function closeNewSessionModal(): void {
    if (newSessionModal.hidden) {
      return;
    }
    newSessionRequestId += 1;
    newSessionModal.classList.remove("is-open");
    window.clearTimeout(newSessionModalCloseTimer);
    newSessionModalCloseTimer = window.setTimeout(() => {
      newSessionModal.hidden = true;
      newSessionBody.innerHTML = "";
      newSessionOptionsCache = null;
    }, 140);
  }

  async function openNewSessionModal(): Promise<void> {
    const requestId = newSessionRequestId + 1;
    newSessionRequestId = requestId;
    window.clearTimeout(newSessionModalCloseTimer);
    newSessionBody.innerHTML = renderThreadMetaSkeleton();
    newSessionModal.hidden = false;
    window.requestAnimationFrame(() => {
      if (newSessionRequestId === requestId) {
        newSessionModal.classList.add("is-open");
      }
    });
    try {
      const options = await window.desktop.getNewSessionOptions();
      if (newSessionModal.hidden || newSessionRequestId !== requestId) {
        return;
      }
      newSessionOptionsCache = options;
      // 安全规则：容器不可用时保持 container 选择（不自动降级为 local）。
      // 用户必须明确选择 local 并确认风险。
      const backends = options.availableBackends;
      if (!backends.includes(newSessionDraft.backend) && newSessionDraft.backend !== "container") {
        newSessionDraft.backend = "container";
      }
      newSessionDraft.projectPath = options.projectPath || uiState.runtime.projectPath;
      if (
        !newSessionDraft.image ||
        (options.availableImages.length > 0 && !options.availableImages.includes(newSessionDraft.image))
      ) {
        newSessionDraft.image = options.defaultImage || options.availableImages[0] || "electromind:latest";
      }
      if (
        newSessionDraft.backend === "ssh" &&
        !newSessionDraft.sshHost &&
        options.sshHosts.length > 0
      ) {
        newSessionDraft.sshHost = options.sshHosts[0];
      }
      paintNewSessionForm();
    } catch (error) {
      if (newSessionModal.hidden || newSessionRequestId !== requestId) {
        return;
      }
      const message = error instanceof Error ? error.message : String(error);
      newSessionBody.innerHTML = `
        <div class="thread-meta-error">${escapeHtml(message)}</div>
      `;
    }
  }

  async function confirmNewSession(): Promise<void> {
    syncNewSessionDraftFromDom();
    if (!newSessionDraft.projectPath) {
      return;
    }
    if (newSessionDraft.backend === "ssh" && !newSessionDraft.sshHost) {
      return;
    }
    // 安全规则：container 不可用时不允许创建会话，除非用户显式选择了 local
    if (newSessionDraft.backend === "container") {
      const available = newSessionOptionsCache?.availableBackends ?? [];
      if (!available.includes("container")) {
        return; // 按钮应为 disabled，这里做最后一道防线
      }
    }
    const options: ResetSessionOptions = {
      backend: newSessionDraft.backend,
      projectPath: newSessionDraft.projectPath,
    };
    if (
      newSessionDraft.backend === "container" ||
      newSessionDraft.backend === "docker" ||
      newSessionDraft.backend === "podman"
    ) {
      options.image = newSessionDraft.image.trim() || "electromind:latest";
    }
    if (newSessionDraft.backend === "ssh") {
      options.sshHost = newSessionDraft.sshHost;
      options.sshWorkdir = newSessionDraft.sshWorkdir || "~/electromind";
    }
    closeNewSessionModal();
    chatRenderer.showHistorySkeleton();
    setComposerHint("");
    uiState.activityState = "sleeping";
    applyActivityState();
    clearSandboxPanel();
    await window.desktop.resetSession(options);
    await refreshSessions();
    await refreshArtifacts();
  }

  function applyActivityState(): void {
    const running = uiState.activityState === "running";
    sendMessageButton.disabled = false;
    sendMessageButton.classList.toggle("is-stop", running);
    sendMessageButton.title = running ? "停止" : "发送";
    sendMessageButton.setAttribute("aria-label", running ? "停止" : "发送");
    sendMessageButton.innerHTML = running
      ? renderIcon("square")
      : renderIcon("arrow-up");

    const resourceMap = resourceSnapshot(uiState.activityState);
    (["cpu", "memory", "disk"] as ResourceKind[]).forEach((kind) => {
      const value = document.querySelector<HTMLElement>(`[data-resource-value="${kind}"]`);
      const bar = document.querySelector<HTMLElement>(`[data-resource-bar="${kind}"]`);
      if (!value || !bar) {
        return;
      }
      value.textContent = resourceMap[kind].value;
      bar.style.width = `${resourceMap[kind].percent}%`;
    });
  }

  function applyHeader(): void {
    taskTitle.textContent = currentSessionTitle(uiState.runtime, uiState.sessions);
    projectText.textContent = projectLabel(uiState.runtime);
    projectButton.title = uiState.runtime.projectPath;
    sandboxBackendIcon.innerHTML = renderIcon(sandboxBackendIconName(uiState.runtime));
    sandboxBackend.textContent = sandboxBackendLabel(uiState.runtime);
    sandboxPill.className = `center-pill center-pill-status ${sandboxPresenceClass(uiState.runtime)}`;
  }

  function renderSessions(): void {
    sessionList.innerHTML = renderSessionList(
      uiState.sessions,
      uiState.runtime.currentThreadId ?? "",
    );
    applyHeader();
  }

  interface SkillStateItem {
    name: string;
    description: string;
    source: string;
    sha256: string;
    status: "available" | "loaded" | "unavailable";
  }

  interface SkillDiagnosticPayload {
    code: string;
    message: string;
    path: string;
    severity: "warning" | "error";
  }

  interface SkillsStatePayload {
    thread_id: string;
    fingerprint: string;
    generation: number;
    digest: string;
    skills: SkillStateItem[];
    loaded: string[];
    loaded_this_run: string[];
    diagnostics: SkillDiagnosticPayload[];
  }

  interface ExecutionContextStatePayload {
    type: "ExecutionContextState";
    thread_id: string;
    target: string;
    profile_id: string;
    documents: ExecutionContextDocument[];
    diagnostics: SkillDiagnosticPayload[];
  }

  interface ExecutionContextDocument {
    remote_path: string;
    sha256: string;
    size: number;
    fetched_at: number;
  }

  function renderExecutionContext(): void {
    const ctx = uiState.executionContextState;
    const el = document.getElementById("execution-context-section");
    if (!el) return;

    if (!ctx || (!ctx.documents.length && !ctx.diagnostics.length)) {
      el.style.display = "none";
      return;
    }

    el.style.display = "";
    const docsHtml = ctx.documents
      .map(
        (d) =>
          `<li class="ec-doc">
            <span class="ec-path">${escapeHtml(d.remote_path)}</span>
            <span class="ec-meta">${formatBytes(d.size)} &middot; ${d.sha256.slice(0, 8)}</span>
          </li>`,
      )
      .join("");

    const diagHtml = ctx.diagnostics
      .map(
        (d) =>
          `<li class="ec-diag ec-diag-${d.severity}">
            <span class="ec-diag-code">${escapeHtml(d.code)}</span>
            <span class="ec-diag-msg">${escapeHtml(d.message)}</span>
          </li>`,
      )
      .join("");

    el.innerHTML =
      `<details open>
        <summary>执行上下文 <span class="ec-target">${escapeHtml(ctx.target)} &ndash; ${escapeHtml(ctx.profile_id)}</span></summary>
        ${docsHtml ? `<ul class="ec-docs">${docsHtml}</ul>` : ""}
        ${diagHtml ? `<ul class="ec-diags">${diagHtml}</ul>` : ""}
      </details>`;
  }

  function renderSkillList(): void {
    const state = uiState.skillsState;
    // Fallback to old skills list
    if (!state && uiState.skills.length > 0) {
      skillsList.innerHTML = uiState.skills
        .map(
          (skill) => `
            <div class="skill-item" title="${escapeHtml(skill.path)}">
              <span class="skill-name">${escapeHtml(skill.name)}</span>
              <span class="skill-desc">${escapeHtml(skill.description)}</span>
            </div>
          `,
        )
        .join("");
      return;
    }

    // 七: 实时目录（skills/list）非空时不走空状态（新装 Skill 也来自这里）
    const hasCatalog = !!uiState.skillsCatalog && uiState.skillsCatalog.length > 0;
    if (
      !hasCatalog &&
      (!state || (state.skills.length === 0 && state.diagnostics.length === 0))
    ) {
      skillsList.innerHTML = `
        <div class="session-empty">
          <div class="session-empty-title">暂无可用 Skill</div>
          <div class="session-empty-copy">当前项目和用户目录中未发现可用 Skill。支持项目 skills/、.agents/skills、.electromind/skills。</div>
        </div>
      `;
      return;
    }

    let html = "";

    // ── generation header ──
    if ((state?.generation ?? 0) > 0) {
      const shortDigest = state?.digest ? state.digest.slice(0, 8) : "";
      html += `<div class="skill-section-label">Skills · Generation ${state?.generation ?? 0}${shortDigest ? ` · ${shortDigest}` : ""}</div>`;
    }

    // ── available（七: Skills Manager —— 纯函数渲染，busy 态禁用按钮）──
    // 优先用 skills/list 实时目录（含操作后的新 Skill 与 trust_state）；
    // 回退到 SkillsState 快照。
    const sourceList: SkillViewItem[] =
      uiState.skillsCatalog && uiState.skillsCatalog.length > 0
        ? uiState.skillsCatalog
        : (state?.skills ?? []);
    const available = sourceList.filter((s) => s.status !== "loaded");
    if (available.length > 0) {
      html += `<div class="skill-section-label">可用 (${available.length})</div>`;
      html += renderSkillRows(available, uiState.skillsPanel.busy);
    }

    // ── loaded this run ──
    if (state?.loaded_this_run && state.loaded_this_run.length > 0) {
      html += `<div class="skill-section-label">本轮加载 (${state?.loaded_this_run?.length ?? 0})</div>`;
      for (const name of state?.loaded_this_run ?? []) {
        const skill = (state?.skills ?? []).find((s) => s.name === name);
        html += `
          <div class="skill-item skill-loaded" title="本轮 Run 中通过 use_skill 加载">
            <span class="skill-name">${escapeHtml(name)}</span>
            ${skill ? `<span class="skill-desc">${escapeHtml(skill.description)}</span>` : ""}
            <span class="skill-badge">✓</span>
          </div>`;
      }
    }

    // ── loaded (all-time) ──
    const loaded = (state?.skills ?? []).filter((s) => s.status === "loaded");
    if (loaded.length > 0 || (state?.loaded ?? []).length > 0) {
      const displayLoaded = loaded.length > 0 ? loaded : (state?.loaded ?? []).map((n) => ({ name: n, description: "", source: "", sha256: "", status: "loaded" as const }));
      html += `<div class="skill-section-label">本任务已加载</div>`;
      for (const skill of displayLoaded) {
        html += `
          <div class="skill-item skill-loaded" title="已激活">
            <span class="skill-name">${escapeHtml(skill.name)}</span>
            <span class="skill-desc">${escapeHtml(skill.description)}</span>
            <span class="skill-badge">✓</span>
          </div>`;
      }
    }

    // ── diagnostics ──
    if ((state?.diagnostics?.length ?? 0) > 0) {
      html += `<div class="skill-section-label">诊断</div>`;
      for (const d of state?.diagnostics ?? []) {
        const icon = d.severity === "error" ? "✗" : "⚠";
        html += `
          <div class="skill-item skill-diag skill-diag-${d.severity}" title="${escapeHtml(d.path)}">
            <span class="skill-name">${icon} ${escapeHtml(d.code)}</span>
            <span class="skill-desc">${escapeHtml(d.message)}</span>
          </div>`;
      }
    }

    skillsList.innerHTML = html;
  }

  /** P3.8: 渲染 HPC 提交记录（Inspector 任务页）。 */
  function renderJobsView(): void {
    const body = document.querySelector<HTMLElement>('[data-inspector-view="jobs"]');
    if (!body) {
      return;
    }
    const subs = uiState.hpcSubmissions;
    if (subs.length === 0) {
      body.innerHTML = `
        <div class="inspector-placeholder">暂无 HPC 任务记录。
          <div class="hpc-hint">提交经 hpc-submit skill 后，这里会显示 job 状态、rsess 会话与恢复信息。</div>
        </div>`;
      return;
    }
    const rows = subs.map((s) => {
      const stateCls = jobStateClass(s.state);
      const stateLabel = s.state || "unknown";
      return `
        <div class="hpc-job-card">
          <div class="hpc-job-head">
            <span class="hpc-job-id" title="${escapeHtml(s.submission_id)}">${escapeHtml(s.job_id || s.submission_id)}</span>
            <span class="hpc-job-state ${stateCls}">${escapeHtml(stateLabel)}</span>
          </div>
          <div class="hpc-job-meta">
            <div><span class="hpc-label">run</span> ${escapeHtml(s.run_id)}</div>
            <div><span class="hpc-label">rsess</span> ${escapeHtml(s.rsess_session || "—")}</div>
            <div><span class="hpc-label">workdir</span> ${escapeHtml(s.remote_workdir || "—")}</div>
            <div><span class="hpc-label">stdout</span> ${escapeHtml(s.stdout_path || "—")}</div>
            ${s.script_sha256 ? `<div><span class="hpc-label">script</span> <code>${escapeHtml(s.script_sha256.slice(0, 12))}…</code></div>` : ""}
            ${s.input_sha256 ? `<div><span class="hpc-label">input</span> <code>${escapeHtml(s.input_sha256.slice(0, 12))}…</code></div>` : ""}
          </div>
          ${s.state === "unknown" || !s.state ? `<div class="hpc-unknown-note">状态未知（查询失败或未 reconcile），未猜测为成功/失败。</div>` : ""}
        </div>`;
    }).join("");
    body.innerHTML = `
      <div class="file-panel-header"><span class="file-panel-title">HPC 任务</span></div>
      <div class="hpc-jobs-list">${rows}</div>`;
  }

  function jobStateClass(state: string): string {
    switch (state) {
      case "completed":
        return "hpc-state-ok";
      case "failed":
      case "timeout":
      case "oom":
        return "hpc-state-bad";
      case "running":
        return "hpc-state-run";
      case "queued":
        return "hpc-state-queue";
      default:
        return "hpc-state-unknown";
    }
  }

  function toggleSkillsPanel(show: boolean): void {
    if (show) {
      sessionList.hidden = true;
      skillsPanel.hidden = false;
      sectionLabel.textContent = "Skills";
      void window.desktop.sendWireCommand({ cmd: "skills" });
    } else {
      sessionList.hidden = false;
      skillsPanel.hidden = true;
      sectionLabel.textContent = "会话历史";
    }
  }

  function renderSandboxRootCard(): string {
    const backend =
      uiState.sandboxStatus.backend || uiState.runtime.sandboxBackend || "";
    const label = sandboxPathRootLabel(backend);
    const workdir = uiState.sandboxStatus.workdir.trim();
    const pathText =
      workdir ||
      (uiState.runtime.currentThreadId ? "待连接" : "未启动");
    return renderPathRootCard(pathText, label);
  }

  function renderTree(): void {
    const header = renderSandboxRootCard();
    if (uiState.sandboxTree.length === 0) {
      fileTree.innerHTML = `
        ${header}
        <div class="session-empty">
          <div class="session-empty-title">沙箱里还没有文件</div>
          <div class="session-empty-copy">沙箱连接后，这里会展示当前 workdir 的目录树。</div>
        </div>
      `;
      return;
    }
    fileTree.innerHTML = `${header}${renderTreeRows(
      uiState.sandboxTree,
      uiState.expandedTree,
    )}`;
  }

  function showTreeContextMenu(event: MouseEvent): void {
    event.preventDefault();
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const row = target.closest<HTMLElement>(".tree-row");
    if (!row) {
      return;
    }
    const nodePath = row.dataset.nodePath;
    const normalizedPath = nodePath ? normalizeProjectRelativePath(nodePath) : null;
    if (!nodePath || !normalizedPath) {
      return;
    }

    // Close any existing menu first, then set the path so hideTreeContextMenu
    // doesn't clear the new value.
    hideTreeContextMenu();
    contextNodePath = normalizedPath;

    // Position at pointer within the viewport.
    const rect = treeContextMenu.getBoundingClientRect();
    const menuWidth = rect.width || 180;
    const menuHeight = rect.height || 80;
    let left = event.clientX;
    let top = event.clientY;
    if (left + menuWidth > window.innerWidth) {
      left = window.innerWidth - menuWidth - 8;
    }
    if (top + menuHeight > window.innerHeight) {
      top = window.innerHeight - menuHeight - 8;
    }
    treeContextMenu.style.left = `${Math.max(0, left)}px`;
    treeContextMenu.style.top = `${Math.max(0, top)}px`;
    treeContextMenu.hidden = false;
  }

  function hideTreeContextMenu(): void {
    treeContextMenu.hidden = true;
    contextNodePath = "";
  }

  async function copyContextPath(mode: "absolute" | "relative"): Promise<void> {
    const projectPath = uiState.runtime.projectPath;
    // contextNodePath is always a normalized relative path or "" (project root).
    const rel = contextNodePath || ".";

    let path: string | null;
    if (mode === "relative") {
      path = rel;
    } else {
      path = buildAbsolutePath(projectPath, rel);
    }

    if (!path) {
      toast("路径无效", { type: "error" });
      hideTreeContextMenu();
      return;
    }

    try {
      await navigator.clipboard.writeText(path);
      const label = mode === "absolute" ? "绝对路径" : "相对路径";
      toast(`已复制${label}：${path}`, { type: "success" });
    } catch {
      toast("复制失败，请重试", { type: "error" });
    }
    hideTreeContextMenu();
  }

  function renderProjectTree(): void {
    hideTreeContextMenu();
    const header = renderPathRootCard(uiState.runtime.projectPath, "本机路径");
    if (uiState.projectTreeNodes.length === 0) {
      projectTree.innerHTML = `
        ${header}
        <div class="session-empty">
          <div class="session-empty-title">项目目录为空</div>
          <div class="session-empty-copy">绑定项目后，这里会展示项目目录树。</div>
        </div>
      `;
      return;
    }
    projectTree.innerHTML = `${header}${renderTreeRows(
      uiState.projectTreeNodes,
      uiState.expandedProjectTree,
    )}`;
  }

  function renderTerminal(): void {
    terminalPanel.innerHTML = renderTerminalEntries(uiState.terminalEntries);
  }

  function clearSandboxPanel(): void {
    uiState.sandboxTree = [];
    uiState.expandedTree = new Set();
    uiState.sandboxStatus = {
      threadId: "",
      backend: "",
      alive: false,
      workdir: "",
    };
    uiState.sandboxLoadedThreadId = "";
    uiState.terminalEntries = [];
    renderTree();
    renderTerminal();
  }

  function renderArtifactList(): void {
    artifactsList.innerHTML = renderArtifacts(
      uiState.artifacts,
      artifactRootPath(uiState.runtime),
    );
    if (artifactPreviewPath && !uiState.artifacts.some((item) => item.path === artifactPreviewPath)) {
      closeArtifactPreview();
    }
  }

  function closeArtifactPreview(): void {
    artifactPreviewPath = "";
    artifactsPanel.classList.remove("preview-open");
    artifactPreview.hidden = true;
    artifactPreview.innerHTML = "";
  }

  async function showArtifactPreview(filePath: string): Promise<void> {
    artifactPreviewPath = filePath;
    artifactsPanel.classList.add("preview-open");
    artifactPreview.hidden = false;
    artifactPreview.innerHTML = `<div class="artifact-preview-body artifact-preview-empty">加载中…</div>`;
    const preview = await window.desktop.readArtifact(filePath);
    if (artifactPreviewPath !== filePath) {
      return;
    }
    artifactPreview.innerHTML = renderArtifactPreview(preview);
  }

  function applyRightTab(): void {
    document.querySelectorAll<HTMLElement>("[data-view]").forEach((node) => {
      const active = node.dataset.view === uiState.activeTab;
      node.classList.toggle("active", active);
    });
    document.querySelectorAll<HTMLElement>("[data-tab]").forEach((node) => {
      const active = node.dataset.tab === uiState.activeTab;
      node.classList.toggle("active", active);
      if (node instanceof HTMLButtonElement) {
        node.setAttribute("aria-selected", active ? "true" : "false");
      }
    });
    rightFooter.dataset.tab = uiState.activeTab;
  }

  function appendTerminalEntry(kind: TerminalEntryKind, text: string): void {
    const normalized = summarize(text, 200);
    if (!normalized) {
      return;
    }
    uiState.terminalEntries.push({ kind, text: normalized });
    if (uiState.terminalEntries.length > 48) {
      uiState.terminalEntries.splice(0, uiState.terminalEntries.length - 48);
    }
    renderTerminal();
  }

  async function refreshSessions(): Promise<void> {
    uiState.sessions = await window.desktop.listThreads();
    renderSessions();
  }

  async function refreshArtifacts(): Promise<void> {
    uiState.artifacts = await window.desktop.listArtifacts();
    renderArtifactList();
  }

  async function refreshSandboxTree(): Promise<void> {
    uiState.sandboxTree = await window.desktop.listSandboxTree();
    uiState.sandboxLoadedThreadId = uiState.runtime.currentThreadId ?? "";
    uiState.expandedTree = new Set(
      uiState.sandboxTree
        .filter((node) => node.kind === "dir")
        .map((node) => node.id),
    );
    renderTree();
  }

  async function refreshProjectTree(): Promise<void> {
    const nodes = await window.desktop.listProjectTree();
    uiState.projectTreeNodes = nodes;
    uiState.projectLoadedPath = uiState.runtime.projectPath;
    uiState.expandedProjectTree = new Set(
      nodes.filter((node) => node.kind === "dir").map((node) => node.id),
    );
    // Single source of truth: the React Inspector Files panel reads the
    // ThreadStore, not the legacy uiState projection.
    threadStore.setProjectTreeNodes(nodes as never);
    renderProjectTree();
  }

  async function ensureProjectPanelLoaded(): Promise<void> {
    const projectPath = uiState.runtime.projectPath;
    if (!projectPath || uiState.projectLoadedPath === projectPath) {
      return;
    }
    await refreshProjectTree();
  }

  async function forceRefreshProjectPanel(): Promise<void> {
    const button = findRequired<HTMLButtonElement>("[data-refresh-project]");
    if (button.disabled) {
      return;
    }
    button.disabled = true;
    button.classList.add("is-busy");
    uiState.projectLoadedPath = "";
    try {
      await refreshProjectTree();
    } finally {
      button.disabled = false;
      button.classList.remove("is-busy");
    }
  }

  async function refreshSandboxStatus(): Promise<void> {
    const status = await window.desktop.getSandboxStatus();
    uiState.sandboxStatus = status;
    uiState.runtime = {
      ...uiState.runtime,
      sandboxBackend:
        status.threadId === uiState.runtime.currentThreadId ? status.backend : undefined,
      sandboxAlive:
        status.threadId === uiState.runtime.currentThreadId ? status.alive : undefined,
    };
    applyHeader();
    renderTree();
  }

  async function ensureSandboxPanelLoaded(): Promise<void> {
    const threadId = uiState.runtime.currentThreadId ?? "";
    if (!threadId || uiState.sandboxLoadedThreadId === threadId) {
      return;
    }
    // 先拉 status（workdir/backend），再拉目录树，避免根卡片短暂空白。
    await refreshSandboxStatus();
    await refreshSandboxTree();
  }

  async function forceRefreshSandboxPanel(): Promise<void> {
    const button = findRequired<HTMLButtonElement>("[data-refresh-sandbox]");
    if (button.disabled) {
      return;
    }
    button.disabled = true;
    button.classList.add("is-busy");
    // 清掉缓存标记，强制重新拉取当前 thread 的目录树。
    uiState.sandboxLoadedThreadId = "";
    try {
      await refreshSandboxStatus();
      await refreshSandboxTree();
    } finally {
      button.disabled = false;
      button.classList.remove("is-busy");
    }
  }

  function setComposerHint(message: string): void {
    const text = message.trim();
    errorText.textContent = text;
    errorText.title = text;
    composerHint.hidden = !text;
    composerHint.classList.toggle("is-error", Boolean(text));
  }

  function dismissComposerHint(): void {
    setComposerHint("");
    void window.desktop.clearLastError();
    if (uiState.activityState === "error" && uiState.runtime.status !== "error") {
      uiState.activityState = "sleeping";
      applyActivityState();
    }
  }

  function applyYoloButton(): void {
    const enabled = uiState.runtime.yoloMode === true;
    yoloButton.classList.toggle("active", enabled);
    yoloButton.title = enabled
      ? "自动审批：开启（点击关闭 YOLO 模式）"
      : "自动审批：关闭（点击开启 YOLO 模式）";
    yoloButton.setAttribute("aria-label", enabled ? "YOLO 已开启" : "YOLO 模式");
  }

  function applyRuntimeState(state: RuntimeState): void {
    uiState.runtime = state;
    if (state.status === "error") {
      uiState.activityState = "error";
    } else if (uiState.activityState === "error" && !state.lastError) {
      uiState.activityState = "sleeping";
    }
    setComposerHint(state.lastError ?? "");
    applyHeader();
    applyActivityState();
    applyYoloButton();
    applyExecutionRiskBar(state);
  }

  function applyExecutionRiskBar(state: RuntimeState): void {
    const bar = document.querySelector<HTMLElement>("[data-execution-risk-bar]");
    if (!bar) return;
    const es = state.executionState;
    // 无数据、已清除、或 thread_id 不匹配当前会话 → 隐藏
    if (!es || !es.mode) {
      bar.hidden = true;
      return;
    }
    if (es.thread_id && es.thread_id !== state.currentThreadId) {
      bar.hidden = true;
      return;
    }
    if (es.mode === "local") {
      bar.hidden = false;
      const text = bar.querySelector<HTMLElement>("[data-execution-risk-text]");
      if (text) text.textContent = es.warning ?? "本地执行：命令直接以当前用户权限运行，无隔离。";
    } else {
      bar.hidden = true;
    }
  }

  async function cancelRun(): Promise<void> {
    if (uiState.activityState !== "running") {
      return;
    }
    await window.desktop.sendWireCommand({ cmd: "cancel" });
  }

  async function sendMessage(): Promise<void> {
    // Harness Spine: sending during a running turn is allowed — the wire
    // enqueues the input and sends an input/state ACK back.
    const text = promptInput.value;
    if (!text.trim()) {
      return;
    }
    // Stable request_id for idempotent send + retry: reuse the pending
    // request's ID when the user re-sends the same text after a failure;
    // otherwise generate a fresh one.
    let requestId: string;
    if (pendingInputRequest && pendingInputRequest.text === text) {
      requestId = pendingInputRequest.requestId;
    } else {
      requestId = `req-${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`;
    }
    pendingInputRequest = { text, requestId };
    // Optimistic item in ThreadStore (single source of truth); the wire
    // input/state ACK reconciles it with the real message_id.
    const threadId = uiState.runtime.currentThreadId ?? "";
    if (threadId) {
      threadStore.addOptimisticInput(threadId, requestId, text);
    }
    promptInput.value = "";
    resizePrompt(promptInput);
    setComposerHint("");
    threadStore.setActivityState("running");
    applyActivityState();
    appendTerminalEntry("command", text);
    try {
      await window.desktop.sendUserInput(text, requestId);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (threadId) {
        threadStore.addErrorItem(threadId, message);
      }
      threadStore.setActivityState("error");
      applyActivityState();
      // Keep pendingInputRequest so a retry reuses the same request_id.
    }
  }

  /** Send input from the React Composer (with delivery mode). */
  async function sendComposerInput(
    text: string,
    delivery: string,
    mode: string,
    skill?: string,
  ): Promise<void> {
    if (!text.trim()) return;
    // Propagate the session mode so the backend freezes it in RunSnapshot
    const activeThread = getThreadStore().getActiveThread();
    if (activeThread) {
      activeThread.sessionMode = mode as never;
    }
    const requestId = `req-${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`;
    pendingInputRequest = { text, requestId };
    // Optimistic item in ThreadStore (single source of truth)
    const threadId = uiState.runtime.currentThreadId ?? "";
    if (threadId) {
      threadStore.addOptimisticInput(threadId, requestId, text);
    }
    threadStore.setActivityState("running");
    applyActivityState();
    appendTerminalEntry("command", text);
    try {
      // P3: Auto Model policy 随 Run 携带（后端 ModelResolver 解析）
      const modelPolicy = modelPolicyString(
        getThreadStore().getActiveThread()?.model,
      );
      // P4: /skill 调用 —— skill 名随行（后端确定性激活）
      await window.desktop.sendUserInput(
        text,
        requestId,
        delivery,
        mode,
        modelPolicy,
        skill,
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (threadId) {
        threadStore.addErrorItem(threadId, message);
      }
      threadStore.setActivityState("error");
      applyActivityState();
    }
  }

  async function openLatestSession(): Promise<void> {
    const latest = uiState.sessions[0];
    if (!latest) {
      return;
    }
    chatRenderer.showHistorySkeleton();
    await window.desktop.resumeThread(latest.id);
  }

  function toggleTheme(): void {
    uiState.theme = uiState.theme === "dark" ? "light" : "dark";
    applyTheme();
  }

  /** Left sidebar resizer only — the right pane is a fixed-width
   *  Inspector owned by InspectorController (D3.2, no resizer). */
  function bindLeftResizer(): void {
    const handle = findRequired<HTMLElement>(`[data-resizer="left"]`);
    handle.addEventListener("pointerdown", (event) => {
      if (uiState.leftCollapsed) {
        return;
      }
      const startX = event.clientX;
      const startWidth = uiState.leftWidth;
      handle.setPointerCapture(event.pointerId);

      const onMove = (moveEvent: PointerEvent) => {
        const delta = moveEvent.clientX - startX;
        uiState.leftWidth = Math.max(200, Math.min(320, startWidth + delta));
        applyWorkbenchChrome();
      };

      const onUp = () => {
        handle.removeEventListener("pointermove", onMove);
        handle.removeEventListener("pointerup", onUp);
        handle.removeEventListener("pointercancel", onUp);
      };

      handle.addEventListener("pointermove", onMove);
      handle.addEventListener("pointerup", onUp);
      handle.addEventListener("pointercancel", onUp);
    });
  }

  function syncWireEvent(event: WireEvent): void {
    // Harness Spine: route ALL events to ThreadStore for persistence,
    // but only apply activity state for the currently selected thread.
    const eventThreadId: string = String(event.params?.thread_id ?? "");
    const currentId: string = uiState.runtime.currentThreadId ?? "";
    const isCurrentThread = !eventThreadId || eventThreadId === currentId;

    // Persist every event to ThreadStore (before any early return).
    // The store handles per-thread dedup, sequencing, and snapshot recovery.
    try {
      const store = getThreadStore();
      store.applyWireEvent(event.method, {
        ...(event.params as Record<string, unknown> ?? {}),
        thread_id: eventThreadId || currentId,
      });
    } catch { /* store not yet initialized */ }

    const subagent = unwrapSubagentEvent(event);
    if (subagent && isCurrentThread) {
      const label = subagent.name || "subagent";
      if (subagent.inner.method === "RunBegin") {
        appendTerminalEntry(
          "status",
          `[subagent:${label}] 开始：${String(subagent.inner.params.user_input ?? "")}`,
        );
      } else if (subagent.inner.method === "ReasoningDelta") {
        const text = String(subagent.inner.params.text ?? "").trim();
        if (text) {
          appendTerminalEntry("status", `[subagent:${label}] thinking: ${text}`);
        }
      } else if (subagent.inner.method === "TextDelta") {
        const text = String(subagent.inner.params.text ?? "").trim();
        if (text) {
          appendTerminalEntry("stdout", `[subagent:${label}] ${text}`);
        }
      } else if (subagent.inner.method === "ToolCallBegin") {
        appendTerminalEntry(
          "command",
          `[subagent:${label}] ${buildToolPreview(
            String(subagent.inner.params.name ?? ""),
            String(subagent.inner.params.arguments ?? ""),
          )}`,
        );
      } else if (subagent.inner.method === "ToolResult") {
        appendTerminalEntry(
          "stdout",
          `[subagent:${label}] ${String(subagent.inner.params.content ?? "")}`,
        );
      } else if (subagent.inner.method === "RunEnd") {
        appendTerminalEntry("status", `[subagent:${label}] 已结束。`);
      }
      applyActivityState();
      syncComposerDock();
      return;
    }

    // Protocol v2: only apply activity state for the currently selected thread.
    // Background thread events were saved to ThreadStore above; do not render.
    if (!isCurrentThread) {
      return; // Background thread — saved to store but not rendered
    }
    contextUsageRing.handleWireEvent(event);
    if (
      event.method === "RunBegin" ||
      event.method === "ReasoningDelta" ||
      event.method === "TextDelta" ||
      event.method === "ToolCallBegin"
    ) {
      // Activity state is a store projection — the subscription mirrors
      // it into uiState (single source of truth).
      if (isCurrentThread) {
        getThreadStore().setActivityState("running");
      }
      if (event.method === "RunBegin" && isCurrentThread) {
        setComposerHint("");
      }
    } else if (event.method === "RunEnd") {
      if (isCurrentThread) {
        getThreadStore().setActivityState("sleeping");
      }
      void refreshSessions();
      void refreshArtifacts();
    } else if (event.method === "HistoryReplay") {
      const threadId = String(event.params.thread_id ?? "");
      if (shouldClearExecutionContextOnReplay(
        threadId,
        uiState.runtime.currentThreadId ?? "",
      )) {
        getThreadStore().setActivityState("sleeping");
        setComposerHint("");
        uiState.executionContextState = null;
        renderExecutionContext();
      }
      void refreshSessions();
      void refreshArtifacts();
    } else if (event.method === "Error") {
      // Activity state via the store (single source of truth)
      getThreadStore().setActivityState("error");
      const message = String(event.params.message ?? "").trim();
      if (message) {
        setComposerHint(message);
      }
      // 新建/恢复会话失败时没有可用 thread，清掉沙箱侧状态避免显示陈旧目录。
      const where = String(event.params.where ?? "");
      if (where === "reset" || where === "resume" || where === "open") {
        clearSandboxPanel();
        uiState.executionContextState = null;
        renderExecutionContext();
        void refreshSessions();
      }
    }

    if (event.method === "Skills") {
      // Legacy compatibility: normalize to SkillsState
      const skillsParam = event.params.skills as Skill[] | undefined;
      uiState.skills = skillsParam ?? [];
      if (skillsParam && skillsParam.length > 0) {
        uiState.skillsState = {
          thread_id: "",
          fingerprint: "",
          generation: 0,
          digest: "",
          skills: skillsParam.map((s) => ({
            name: s.name,
            description: s.description,
            source: "",
            sha256: "",
            status: "available" as const,
          })),
          loaded: [],
          loaded_this_run: [],
          diagnostics: [],
        };
      }
      renderSkillList();
    }

    if (event.method === "skills/list" || event.method === "skills/reload") {
      // 实时目录（wire 响应，install/update/remove/trust 后的 reload 也是
      // 这个形状）：优先于冻结的 SkillsState 快照
      const params = event.params as { skills?: SkillViewItem[] };
      if (Array.isArray(params?.skills)) {
        uiState.skillsCatalog = params.skills;
        // 操作后的目录刷新到达 = 操作完成 → 清除面板 busy 态
        uiState.skillsPanel = { ...uiState.skillsPanel, busy: new Set() };
        renderSkillList();
      }
    }

    if (event.method === "SkillsState") {
      const state = event.params as unknown as SkillsStatePayload;
      // Only apply if this event is for the active task; 无活动线程时
      // 接受 agent 当前会话的 SkillsState（否则新装 Skill 永不刷新面板）
      if (state.thread_id && state.thread_id === uiState.runtime.currentThreadId) {
        uiState.skillsState = state;
      } else if (!state.thread_id || !uiState.runtime.currentThreadId) {
        uiState.skillsState = state;
      }
      // 新状态到达 = 操作后的目录刷新完成 → 清除面板 busy 态
      uiState.skillsPanel = { ...uiState.skillsPanel, busy: new Set() };
      renderSkillList();
    }

    if (event.method === "ExecutionContextState") {
      const state = event.params as unknown as ExecutionContextStatePayload;
      const transition = computeExecutionContextTransition(
        state,
        uiState.runtime.currentThreadId ?? "",
      );
      if (transition.kind === "noop") {
        return;
      }
      uiState.executionContextState =
        transition.kind === "clear" ? null : transition.state;
      renderExecutionContext();
    }

    if (event.method === "hpc/submissions") {
      const payload = event.params as unknown as HpcSubmissionsPayload;
      uiState.hpcSubmissions = payload?.submissions ?? [];
      renderJobsView();
    }

    if (event.method === "ToolCallBegin") {
      appendTerminalEntry(
        "command",
        buildToolPreview(
          String(event.params.name ?? ""),
          String(event.params.arguments ?? ""),
        ),
      );
    }
    if (event.method === "ToolResult") {
      appendTerminalEntry("stdout", String(event.params.content ?? ""));
    }
    if (event.method === "Error") {
      appendTerminalEntry("stderr", String(event.params.message ?? ""));
      // 七: Skills Manager 操作失败 → 面板错误提示
      const errMsg = String(event.params.message ?? "");
      if (errMsg.startsWith("skills/")) {
        uiState.skillsPanel = reduceSkillsAction(uiState.skillsPanel, {
          type: "end",
          name: "",
          ok: false,
          error: errMsg,
        });
        toast(errMsg, { type: "error" });
      }
    }
    if (event.method === "RunEnd") {
      appendTerminalEntry("status", "任务已结束，等待下一条指令。");
    }
    if (
      event.method === "RunBegin" ||
      event.method === "RunEnd" ||
      event.method === "Error"
    ) {
      void refreshSandboxStatus();
    }
    applyActivityState();
    syncComposerDock();
  }

  const mentionState = {
    open: false,
    items: [] as MentionFile[],
    active: 0,
    start: 0,
    end: 0,
    projectFiles: [] as MentionFile[],
    sandboxFiles: [] as MentionFile[],
    loaded: false,
    loadedKey: "",
  };

  async function loadMentionFiles(): Promise<void> {
    const key = `${uiState.runtime.projectPath}::${uiState.runtime.currentThreadId ?? ""}`;
    if (mentionState.loaded && mentionState.loadedKey === key) {
      return;
    }
    mentionState.loaded = true;
    mentionState.loadedKey = key;
    const [projectFiles, sandboxTree] = await Promise.all([
      window.desktop.listProjectFiles().catch(() => [] as string[]),
      window.desktop.listSandboxTree().catch(() => [] as SandboxTreeNode[]),
    ]);
    mentionState.projectFiles = projectFiles.map((filePath) => ({
      path: filePath,
      source: "project" as MentionSource,
    }));
    mentionState.sandboxFiles = flattenSandboxTree(sandboxTree).map((filePath) => ({
      path: filePath,
      source: "sandbox" as MentionSource,
    }));
  }

  function closeMention(): void {
    if (!mentionState.open) {
      return;
    }
    mentionState.open = false;
    mentionState.items = [];
    mentionPopup.hidden = true;
    mentionPopup.innerHTML = "";
  }

  function renderMentionPopup(): void {
    if (mentionState.items.length === 0) {
      mentionPopup.hidden = true;
      mentionPopup.innerHTML = "";
      return;
    }
    mentionPopup.innerHTML = mentionState.items
      .map((item, index) => {
        const iconName: DesktopIconName =
          item.source === "sandbox" ? "container" : "folder";
        const active = index === mentionState.active ? " active" : "";
        const prev = mentionState.items[index - 1];
        const divider =
          prev && prev.source !== item.source
            ? `<div class="mention-divider" role="separator"></div>`
            : "";
        return `
          ${divider}
          <button class="mention-item${active}" type="button" data-mention-index="${index}">
            <span class="mention-icon" aria-hidden="true">${renderIcon(iconName)}</span>
            <span class="mention-path">${escapeHtml(item.path)}</span>
            <span class="mention-source mention-source-${item.source}">${mentionSourceLabel(item.source)}</span>
          </button>
        `;
      })
      .join("");
    mentionPopup.hidden = false;
  }

  function updateMentionActive(delta: number): void {
    const count = mentionState.items.length;
    if (count === 0) {
      return;
    }
    mentionState.active = (mentionState.active + delta + count) % count;
    renderMentionPopup();
  }

  function applyMention(item: MentionFile): void {
    const value = promptInput.value;
    const before = value.slice(0, mentionState.start);
    const after = value.slice(mentionState.end);
    const insert = `@${mentionSourcePrefix(item.source)}:${item.path} `;
    promptInput.value = `${before}${insert}${after}`;
    const caret = before.length + insert.length;
    promptInput.setSelectionRange(caret, caret);
    closeMention();
    resizePrompt(promptInput);
    promptInput.focus();
  }

  async function refreshMention(): Promise<void> {
    const caret = promptInput.selectionStart ?? promptInput.value.length;
    const head = promptInput.value.slice(0, caret);
    const match = MENTION_MATCH.exec(head);
    if (!match) {
      closeMention();
      return;
    }
    const raw = match[1];
    mentionState.start = caret - raw.length - 1;
    mentionState.end = caret;
    await loadMentionFiles();
    const { source, query } = parseMentionQuery(raw);
    if (source === "project") {
      mentionState.items = filterMentions(mentionState.projectFiles, query);
    } else if (source === "sandbox") {
      mentionState.items = filterMentions(mentionState.sandboxFiles, query);
    } else {
      const project = filterMentions(mentionState.projectFiles, query);
      const sandbox = filterMentions(mentionState.sandboxFiles, query);
      const picked = mergeMentions(project, sandbox).slice(0, MENTION_LIMIT);
      mentionState.items = [
        ...picked.filter((item) => item.source === "project"),
        ...picked.filter((item) => item.source === "sandbox"),
      ];
    }
    mentionState.active = 0;
    mentionState.open = mentionState.items.length > 0;
    renderMentionPopup();
  }

  mentionPopup.addEventListener("mousedown", (event) => {
    const target = (event.target as HTMLElement).closest<HTMLElement>(
      "[data-mention-index]",
    );
    if (!target) {
      return;
    }
    event.preventDefault();
    const index = Number(target.dataset.mentionIndex);
    const item = mentionState.items[index];
    if (item) {
      applyMention(item);
    }
  });

  promptInput.addEventListener("input", () => {
    resizePrompt(promptInput);
    syncComposerDock();
    void refreshMention();
  });
  promptInput.addEventListener("focus", () => syncComposerDock());
  promptInput.addEventListener("blur", () => {
    window.setTimeout(() => {
      closeMention();
      syncComposerDock();
    }, 120);
  });
  promptInput.addEventListener("keydown", (event) => {
    if (mentionState.open) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        updateMentionActive(1);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        updateMentionActive(-1);
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        const item = mentionState.items[mentionState.active];
        if (item) {
          event.preventDefault();
          applyMention(item);
          return;
        }
      }
      if (event.key === "Escape") {
        event.preventDefault();
        closeMention();
        return;
      }
    }
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) {
      return;
    }
    event.preventDefault();
    // Harness Spine: Enter during running sends a steer/immediate input.
    // Cancel is triggered by Escape or the stop button, not Enter.
    void sendMessage();
  });
  resizePrompt(promptInput);

  historyDockButton.addEventListener("mousedown", (event) => {
    event.preventDefault();
  });
  historyDockButton.addEventListener("click", () => {
    syncComposerDock(true);
  });

  skillsButton.addEventListener("click", () => {
    toggleSkillsPanel(sessionList.hidden === false);
  });

  // ── 七: Skills Manager —— 安装 / 信任 / 更新 / 移除 / 刷新 ──────────
  function sendSkillManageCommand(cmd: string, params: Record<string, unknown>, name: string): void {
    uiState.skillsPanel = reduceSkillsAction(uiState.skillsPanel, {
      type: "begin",
      name,
    });
    renderSkillList();
    void window.desktop.sendWireCommand({ cmd, ...params } as WireCommand).catch((e: unknown) => {
      uiState.skillsPanel = reduceSkillsAction(uiState.skillsPanel, {
        type: "end",
        name,
        ok: false,
        error: String(e),
      });
      renderSkillList();
      toast(String(e), { type: "error" });
    });
    // wire 流按序处理：操作后立即 reload，面板以操作后的目录刷新
    window.setTimeout(() => {
      void window.desktop.sendWireCommand({ cmd: "skills/reload" }).catch(() => {});
    }, 80);
  }

  const skillsInstallSource = findRequired<HTMLInputElement>("[data-skills-install-source]");
  const skillsInstallTrust = findRequired<HTMLInputElement>("[data-skills-install-trust]");
  const skillsInstallBtn = findRequired<HTMLButtonElement>("[data-skills-install]");
  const skillsRefreshBtn = findRequired<HTMLButtonElement>("[data-skills-refresh]");

  skillsInstallBtn.addEventListener("click", () => {
    const source = skillsInstallSource.value.trim();
    if (!source) {
      toast("请输入 Git URL 或本地目录", { type: "error" });
      return;
    }
    sendSkillManageCommand(
      "skills/install",
      {
        source,
        trust: skillsInstallTrust.checked,
        scope: "user",
      },
      "install",
    );
    skillsInstallSource.value = "";
  });
  skillsInstallSource.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      skillsInstallBtn.click();
    }
  });
  skillsRefreshBtn.addEventListener("click", () => {
    void window.desktop.sendWireCommand({ cmd: "skills/reload" }).catch((e: unknown) => {
      toast(String(e), { type: "error" });
    });
  });

  skillsList.addEventListener("click", (ev) => {
    const target = ev.target as HTMLElement;
    const trustBtn = target.closest<HTMLElement>("[data-skill-trust]");
    const updateBtn = target.closest<HTMLElement>("[data-skill-update]");
    const removeBtn = target.closest<HTMLElement>("[data-skill-remove]");
    if (trustBtn) {
      const name = trustBtn.dataset.skillTrust ?? "";
      const wasTrusted = trustBtn.dataset.trusted === "1";
      sendSkillManageCommand("skills/trust", { name, granted: !wasTrusted }, name);
      return;
    }
    if (updateBtn) {
      const name = updateBtn.dataset.skillUpdate ?? "";
      sendSkillManageCommand("skills/update", { name }, name);
      return;
    }
    if (removeBtn) {
      const name = removeBtn.dataset.skillRemove ?? "";
      if (window.confirm(`确认移除 Skill「${name}」？`)) {
        sendSkillManageCommand("skills/remove", { name }, name);
      }
    }
  });

  // D3.4-2: bridge for the React Composer's skills button (vanilla owns
  // the skills panel; React never touches its DOM).
  window.addEventListener("electromind:skills-open", () => {
    skillsButton.click();
  });

  // D3.4-2: manual reconnect entry from the React Composer's disconnected
  // state (the auto scheduler stops at its attempt ceiling).
  window.addEventListener("electromind:reconnect", () => {
    void window.desktop.forceReconnect?.();
  });

  yoloButton.addEventListener("click", () => {
    const next = !uiState.runtime.yoloMode;
    uiState.runtime = { ...uiState.runtime, yoloMode: next };
    applyYoloButton();
    void window.desktop.setYoloMode(next).then((state) => {
      applyRuntimeState(state);
      if (state.yoloMode) {
        toast.warning("YOLO 已开启", {
          description: "工具调用将自动批准，请确认信任当前任务。",
        });
      } else {
        toast.info("YOLO 已关闭", {
          description: "工具调用需要手动批准。",
        });
      }
    });
  });

  sendMessageButton.addEventListener("click", () => {
    if (uiState.activityState === "running") {
      void cancelRun();
      return;
    }
    void sendMessage();
  });

  clearLastErrorButton.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    dismissComposerHint();
  });

  document.querySelectorAll<HTMLElement>("[data-theme-toggle]").forEach((button) => {
    button.addEventListener("click", toggleTheme);
  });

  document.querySelectorAll<HTMLElement>("[data-new-task]").forEach((button) => {
    button.addEventListener("click", () => {
      void openNewSessionModal();
    });
  });

  newSessionModal.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    if (target.closest("[data-new-session-close]") || target.closest("[data-new-session-cancel]")) {
      closeNewSessionModal();
      return;
    }
    const imageOption = target.closest<HTMLElement>("[data-image-option]");
    if (imageOption) {
      selectImage(imageOption.getAttribute("value") || "");
      return;
    }
    if (target.closest("[data-image-dropdown-toggle]")) {
      toggleImageDropdown();
      return;
    }
    const hostOption = target.closest<HTMLElement>("[data-ssh-host-option]");
    if (hostOption) {
      selectSshHost(hostOption.getAttribute("value") || "");
      return;
    }
    if (target.closest("[data-ssh-dropdown-toggle]")) {
      toggleSshHostDropdown();
      return;
    }
    if (!target.closest("[data-ssh-dropdown]")) {
      closeSshHostDropdown();
    }
    if (!target.closest("[data-image-dropdown]")) {
      closeImageDropdown();
    }
    const backendButton = target.closest<HTMLElement>("[data-backend]");
    if (backendButton?.dataset.backend) {
      syncNewSessionDraftFromDom();
      newSessionDraft.backend = backendButton.dataset.backend as SandboxBackendOption;
      if (
        newSessionDraft.backend === "ssh" &&
        !newSessionDraft.sshHost &&
        newSessionOptionsCache &&
        newSessionOptionsCache.sshHosts.length > 0
      ) {
        newSessionDraft.sshHost = newSessionOptionsCache.sshHosts[0];
      }
      if (
        (newSessionDraft.backend === "container" ||
          newSessionDraft.backend === "docker" ||
          newSessionDraft.backend === "podman") &&
        newSessionOptionsCache &&
        !newSessionDraft.image
      ) {
        newSessionDraft.image =
          newSessionOptionsCache.defaultImage ||
          newSessionOptionsCache.availableImages[0] ||
          "electromind:latest";
      }
      paintNewSessionForm();
      return;
    }
    if (target.closest("[data-pick-project]")) {
      void (async () => {
        syncNewSessionDraftFromDom();
        const picked = await window.desktop.pickDirectory(newSessionDraft.projectPath);
        if (!picked) {
          return;
        }
        newSessionDraft.projectPath = picked;
        paintNewSessionForm();
      })();
      return;
    }
    if (target.closest("[data-new-session-confirm]")) {
      void confirmNewSession();
    }
  });

  projectButton.addEventListener("click", async () => {
    const state = await window.desktop.selectProject();
    applyRuntimeState(state);
    uiState.projectLoadedPath = "";
    chatRenderer.showHistorySkeleton();
    uiState.activityState = "sleeping";
    applyActivityState();
    await window.desktop.resetSession();
    await Promise.all([
      refreshSessions(),
      refreshArtifacts(),
      ensureProjectPanelLoaded(),
    ]);
    // D3.2: after picking a project, surface its files in the Inspector.
    inspectorController.openTab("files");
  });

  settingsOpenButton.addEventListener("click", () => {
    void openSettingsModal();
  });

  documentationButton.addEventListener("click", () => {
    void window.desktop.openDocumentation();
  });

  const userMenu = findRequired<HTMLElement>("[data-user-menu]");
  const userMenuDropdown = findRequired<HTMLElement>("[data-user-menu-dropdown]");
  const userMenuToggles = Array.from(
    document.querySelectorAll<HTMLButtonElement>("[data-user-menu-toggle]"),
  );

  function layoutUserMenuDropdown(): void {
    const toggle = userMenu.querySelector<HTMLElement>("[data-user-menu-toggle]");
    if (!toggle) {
      return;
    }
    const rect = toggle.getBoundingClientRect();
    const width = Math.max(rect.width, 208);
    userMenuDropdown.style.position = "fixed";
    userMenuDropdown.style.left = `${Math.max(8, rect.left)}px`;
    userMenuDropdown.style.width = `${width}px`;
    userMenuDropdown.style.right = "auto";
    userMenuDropdown.style.top = "auto";
    userMenuDropdown.style.bottom = `${Math.max(8, window.innerHeight - rect.top + 8)}px`;
  }

  function setUserMenuOpen(open: boolean): void {
    userMenu.classList.toggle("is-open", open);
    userMenuDropdown.hidden = !open;
    for (const toggle of userMenuToggles) {
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    }
    if (open) {
      layoutUserMenuDropdown();
    }
  }

  function toggleUserMenu(): void {
    const next = userMenuDropdown.hidden;
    if (next && uiState.leftCollapsed) {
      uiState.leftCollapsed = false;
      uiState.sidebarDocked = false;
      applyWorkbenchChrome();
      window.requestAnimationFrame(() => {
        setUserMenuOpen(true);
      });
      return;
    }
    setUserMenuOpen(next);
  }

  for (const toggle of userMenuToggles) {
    toggle.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleUserMenu();
    });
  }

  findRequired<HTMLButtonElement>("[data-user-menu-wechat]").addEventListener(
    "click",
    () => {
      setUserMenuOpen(false);
      openDocsQrModal();
    },
  );

  findRequired<HTMLButtonElement>("[data-user-menu-settings]").addEventListener(
    "click",
    () => {
      setUserMenuOpen(false);
      void openSettingsModal();
    },
  );

  findRequired<HTMLButtonElement>("[data-user-menu-onboarding]").addEventListener(
    "click",
    () => {
      setUserMenuOpen(false);
      void window.desktop.getOnboardingState().then((state) => {
        onboarding.open(state);
      });
    },
  );

  findRequired<HTMLButtonElement>("[data-user-menu-docs]").addEventListener(
    "click",
    () => {
      setUserMenuOpen(false);
      void window.desktop.openDocumentation();
    },
  );

  document.addEventListener("mousedown", (event) => {
    if (userMenuDropdown.hidden) {
      return;
    }
    const target = event.target;
    if (!(target instanceof Node)) {
      return;
    }
    if (userMenu.contains(target)) {
      return;
    }
    if (
      target instanceof Element &&
      target.closest("[data-user-menu-toggle]")
    ) {
      return;
    }
    setUserMenuOpen(false);
  });

  document.addEventListener("mousedown", (event) => {
    if (treeContextMenu.hidden) {
      return;
    }
    const target = event.target;
    if (!(target instanceof Node)) {
      return;
    }
    if (treeContextMenu.contains(target)) {
      return;
    }
    // Allow right-click on project tree rows to reposition the menu
    // without dismissing it first.
    if (
      target instanceof Element &&
      target.closest("[data-project-tree] .tree-row")
    ) {
      return;
    }
    hideTreeContextMenu();
  });

  shortcutsOpenButton.addEventListener("click", () => {
    openShortcutsModal();
  });

  onboardingModal.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    if (target.closest("[data-onboarding-close]")) {
      if (!onboarding.tryDismiss()) {
        return;
      }
    }
  });

  shortcutsModal.addEventListener("click", (event) => {
    if (event.target === shortcutsModal || (event.target as HTMLElement).closest("[data-shortcuts-close]")) {
      closeShortcutsModal();
    }
  });

  titlebarSwitch.addEventListener("click", () => {
    toggleTheme();
  });

  pinSidebarButton.addEventListener("click", () => {
    uiState.sidebarPinned = !uiState.sidebarPinned;
    applyPinState();
    syncComposerDock();
  });

  findRequired<HTMLElement>("[data-collapse-left]").addEventListener("click", () => {
    uiState.leftCollapsed = true;
    uiState.sidebarDocked = false;
    applyWorkbenchChrome();
  });
  findRequired<HTMLElement>("[data-expand-left]").addEventListener("click", () => {
    uiState.leftCollapsed = false;
    uiState.sidebarDocked = false;
    applyWorkbenchChrome();
  });
  findRequired<HTMLElement>("[data-open-latest]").addEventListener("click", () => {
    void openLatestSession();
  });

  // D3.2: tab bar clicks go through the InspectorController — the store
  // is the single source of truth; the controller flips the views.
  document.querySelectorAll<HTMLElement>("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      const tab = button.dataset.tab;
      if (isInspectorTab(tab)) {
        inspectorController.openTab(tab);
      }
    });
  });

  findRequired<HTMLButtonElement>("[data-refresh-sandbox]").addEventListener("click", () => {
    void forceRefreshSandboxPanel();
  });
  refreshProjectButton.addEventListener("click", () => {
    void forceRefreshProjectPanel();
  });

  sessionList.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const deleteButton = target.closest<HTMLElement>("[data-thread-delete]");
    if (deleteButton) {
      const threadId = deleteButton.dataset.threadId;
      if (!threadId) {
        return;
      }
      const deletingCurrent = threadId === uiState.runtime.currentThreadId;
      const session = uiState.sessions.find((item) => item.id === threadId);
      const label = session?.title?.trim();
      void (async () => {
        const confirmed = await openConfirm({
          title: "删除会话",
          message: label
            ? `删除「${label}」后无法恢复，确认删除吗？`
            : "删除后无法恢复，确认删除这个会话吗？",
          confirmText: "删除",
          cancelText: "取消",
          tone: "danger",
        });
        if (!confirmed) {
          return;
        }
        const deleted = await window.desktop.deleteThread(threadId);
        if (!deleted) {
          return;
        }
        if (deletingCurrent) {
          chatRenderer.showHistorySkeleton();
          clearSandboxPanel();
        }
        await refreshSessions();
        if (deletingCurrent) {
          chatRenderer.clear();
        }
      })();
      return;
    }
    const metaButton = target.closest<HTMLElement>("[data-thread-meta]");
    if (metaButton) {
      const threadId = metaButton.dataset.threadId;
      if (threadId) {
        void openThreadMetaModal(threadId);
      }
      return;
    }
    const button = target.closest<HTMLElement>("[data-thread-open]");
    if (!button) {
      return;
    }
    const threadId = button.dataset.threadId;
    if (!threadId || threadId === uiState.runtime.currentThreadId) {
      return;
    }
    chatRenderer.showHistorySkeleton();
    clearSandboxPanel();
    void window.desktop.resumeThread(threadId);
  });

  threadMetaModal.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    if (target.closest("[data-thread-meta-close]")) {
      closeThreadMetaModal();
    }
  });

  settingsModal.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    if (target.closest("[data-settings-close]")) {
      closeSettingsModal();
    }
  });

  docsQrModal.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    if (target.closest("[data-docs-qr-close]")) {
      closeDocsQrModal();
      return;
    }
    if (target.closest("[data-docs-qr-open]")) {
      void window.desktop.openDocumentation();
    }
  });

  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (!confirmModal.hidden) {
        settleConfirm(false);
        return;
      }
      if (!userMenuDropdown.hidden) {
        setUserMenuOpen(false);
        return;
      }
      if (!treeContextMenu.hidden) {
        hideTreeContextMenu();
        return;
      }
      const sshMenu = newSessionBody.querySelector<HTMLElement>("[data-ssh-dropdown-menu]");
      if (!newSessionModal.hidden && sshMenu && !sshMenu.hidden) {
        closeSshHostDropdown();
        return;
      }
      if (!newSessionModal.hidden) {
        closeNewSessionModal();
      }
      if (!threadMetaModal.hidden) {
        closeThreadMetaModal();
      }
      if (!settingsModal.hidden) {
        closeSettingsModal();
      }
      if (!docsQrModal.hidden) {
        closeDocsQrModal();
      }
      if (!shortcutsModal.hidden) {
        closeShortcutsModal();
      }
      if (artifactPreviewPath) {
        closeArtifactPreview();
      }
      // P0 交互优先级：Esc 先关浮层/菜单（上面），再停止 Run —— 绝不默认批准。
      // 等待审批时停止 Run 会让审批随运行取消，不会放行工具调用。
      // P1: 停止动作经统一 Command Registry（run.stop）——
      // 快捷键与 Slash / Palette 执行同一命令。
      const activeThread = getThreadStore().getActiveThread();
      const hasPendingApproval = (activeThread?.pendingPermits?.length ?? 0) > 0;
      if (uiState.activityState === "running" || hasPendingApproval) {
        const reg = (window as unknown as Record<string, unknown>)
          .__electromindCommandRegistry as {
            execute: (
              id: string,
              ctx: unknown,
              args?: Record<string, unknown>,
            ) => Promise<unknown>;
          } | undefined;
        if (reg) {
          void reg.execute("run.stop", { store: getThreadStore() });
        } else {
          void cancelRun();
        }
      }
      return;
    }
    if (!event.metaKey) {
      return;
    }
    // P1: 其余快捷键全部经统一 Command Registry 解析（Cmd+K 面板 /
    // Cmd+. 模式 / Cmd+N 新建 / Cmd+L 聚焦输入 / Cmd+B Threads /
    // Cmd+I Inspector / Cmd+Shift+Enter 排队）。
    const reg = (window as unknown as Record<string, unknown>)
      .__electromindCommandRegistry as
      | {
          shortcutBinding: (s: string) => { id: string } | undefined;
          execute: (
            id: string,
            ctx: unknown,
            args?: Record<string, unknown>,
          ) => Promise<unknown>;
        }
      | undefined;
    const shortcut = pressedShortcut(event);
    if (reg && shortcut) {
      const binding = reg.shortcutBinding(shortcut);
      if (binding) {
        event.preventDefault();
        void reg.execute(binding.id, { store: getThreadStore() });
        return;
      }
    }
  });

  /** 组合键 → 规范化快捷键串（与 Registry 的 shortcut 字段同格式）。 */
  function pressedShortcut(event: KeyboardEvent): string {
    const parts: string[] = [];
    if (event.metaKey) parts.push("meta");
    if (event.ctrlKey) parts.push("ctrl");
    if (event.altKey) parts.push("alt");
    if (event.shiftKey) parts.push("shift");
    const key = event.key.toLowerCase();
    if (key === "escape") {
      return parts.join("+") || "";
    }
    if (key === "enter") parts.push("enter");
    else if (key === " " || key === "spacebar") parts.push("space");
    else if (key.length === 1) parts.push(key);
    else return "";
    return parts.join("+");
  }

  fileTree.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const button = target.closest<HTMLElement>("[data-tree-toggle]");
    if (!button) {
      return;
    }
    const treeId = button.dataset.treeToggle;
    if (!treeId) {
      return;
    }
    if (uiState.expandedTree.has(treeId)) {
      uiState.expandedTree.delete(treeId);
    } else {
      uiState.expandedTree.add(treeId);
    }
    renderTree();
  });

  projectTree.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const button = target.closest<HTMLElement>("[data-tree-toggle]");
    if (!button) {
      return;
    }
    const treeId = button.dataset.treeToggle;
    if (!treeId) {
      return;
    }
    if (uiState.expandedProjectTree.has(treeId)) {
      uiState.expandedProjectTree.delete(treeId);
    } else {
      uiState.expandedProjectTree.add(treeId);
    }
    renderProjectTree();
  });

  projectTree.addEventListener("contextmenu", (event) => {
    showTreeContextMenu(event);
  });

  treeContextMenu.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const item = target.closest<HTMLElement>("[data-context-copy]");
    if (!item) {
      return;
    }
    const mode = item.dataset.contextCopy as "absolute" | "relative" | undefined;
    if (mode === "absolute" || mode === "relative") {
      void copyContextPath(mode);
    }
  });

  artifactsList.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const openButton = target.closest<HTMLButtonElement>("[data-artifact-path]");
    if (openButton?.dataset.artifactPath) {
      void window.desktop.openArtifact(openButton.dataset.artifactPath);
      return;
    }
    const row = target.closest<HTMLElement>("[data-artifact-preview-path]");
    const previewPath = row?.dataset.artifactPreviewPath;
    if (!previewPath) {
      return;
    }
    void showArtifactPreview(previewPath);
  });

  artifactsList.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const row = target.closest<HTMLElement>("[data-artifact-preview-path]");
    const previewPath = row?.dataset.artifactPreviewPath;
    if (!previewPath) {
      return;
    }
    event.preventDefault();
    void showArtifactPreview(previewPath);
  });

  artifactPreview.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    if (target.closest("[data-artifact-preview-close]")) {
      closeArtifactPreview();
      return;
    }
    const openButton = target.closest<HTMLButtonElement>("[data-artifact-path]");
    if (openButton?.dataset.artifactPath) {
      void window.desktop.openArtifact(openButton.dataset.artifactPath);
    }
    // P4.4: 一键打开日志目录。
    if (target.closest("[data-open-log-dir]")) {
      void window.desktop.openLogDir();
    }
  });

  bindLeftResizer();

  // D3.2: contextual Inspector — default closed, opens on demand.
  // The controller owns right-pane chrome, Escape, pin/close, trigger
  // clicks, focus return and the plan/changes/jobs/runtime views.
  function handleInspectorTabChange(tab: InspectorTab): void {
    const changed = uiState.activeTab !== tab;
    uiState.activeTab = tab;
    applyRightTab();
    if (!changed) {
      return;
    }
    if (tab === "files") {
      void ensureProjectPanelLoaded();
    }
    if (tab === "artifacts") {
      void refreshArtifacts();
    }
    if (tab === "runtime") {
      void ensureSandboxPanelLoaded();
    }
    if (tab === "jobs") {
      void refreshHpcSubmissions();
    }
  }

  /** P3.8: 打开任务页时向 wire 请求该 thread 的 HPC 提交记录。 */
  async function refreshHpcSubmissions(): Promise<void> {
    const tid = uiState.runtime.currentThreadId ?? "";
    await window.desktop.sendWireCommand({ cmd: "hpc/submissions", thread_id: tid });
  }

  const inspectorController = new InspectorController({
    workbench,
    onTabChange: handleInspectorTabChange,
  });
  inspectorController.attach();

  const disposeAgentEvents = window.desktop.onAgentEvent((message) => {
    if (message.type === "wireEvent") {
      // Harness Spine: single source of truth — events go to ThreadStore
      // (and the vanilla state projection), NOT directly to the renderer.
      syncWireEvent(message.event);
      // Terminal input/state ACK → reconcile the optimistic item with the
      // real message_id, then clear the pending retry slot.
      if (message.event.method === "input/state") {
        const params = message.event.params ?? {};
        const ackState = String(params.state ?? "");
        const ackMessageId = String(params.message_id ?? "");
        const ackThreadId = String(params.thread_id ?? "");
        if (ackThreadId && ackMessageId) {
          threadStore.reconcileInput(
            ackThreadId,
            ackMessageId,
            ackState,
            pendingInputRequest?.requestId,
          );
        }
        if (["applied", "deferred", "rejected"].includes(ackState)) {
          pendingInputRequest = null;
        }
      }
      return;
    }
    const text = message.text.trim();
    if (!text || isRoutineWireLog(text)) {
      return;
    }
    // 非致命 stderr 用 sonner；真正的 lastError 仍走 composer hint。
    if (!errorText.textContent) {
      toast.warning(summarize(text, 72), {
        description: text.length > 72 ? text : undefined,
        duration: 4800,
      });
    }
    appendTerminalEntry("stderr", text);
  });

  // ── React Composer bridge ──────────────────────────────────────────
  // The React shell dispatches these events; the vanilla renderer owns
  // the wire bridge, so we consume them here.
  const handleComposerInput = (event: Event): void => {
    const detail = (event as CustomEvent).detail ?? {};
    const text = String(detail.text ?? "");
    const delivery = String(detail.delivery ?? "auto");
    const mode = String(detail.mode ?? "agent");
    // P4: /skill 调用 —— skill 名随行（sendUserInput 的 skill 字段）
    const skill = String(detail.skill ?? "");
    if (!text.trim()) return;
    void sendComposerInput(text, delivery, mode, skill || undefined);
  };
  const handleComposerStop = (): void => {
    void cancelRun();
  };
  window.addEventListener("electromind:user-input", handleComposerInput);
  window.addEventListener("electromind:stop", handleComposerStop);

  // ── P1: Command Registry 事件桥 ─────────────────────────────────
  // Registry 的 UI 命令通过事件打开 vanilla 浮层/面板 —— 与按钮绑定
  // 走同一批闭包，状态不会出现两套。
  window.addEventListener("electromind:open-shortcuts", () => {
    openShortcutsModal();
  });
  window.addEventListener("electromind:open-settings", () => {
    void openSettingsModal();
  });
  window.addEventListener("electromind:toggle-threads", () => {
    uiState.leftCollapsed = !uiState.leftCollapsed;
    uiState.sidebarDocked = false;
    applyWorkbenchChrome();
    syncComposerDock();
  });
  // P2: /full 等危险命令的二次确认 —— Registry 命令经此桥走 vanilla
  // confirm 模态；结果回发 electromind:confirm-resolved{requestId, ok}。
  window.addEventListener("electromind:confirm-request", (e) => {
    const d = (e as CustomEvent).detail as {
      requestId?: string;
      title?: string;
      message?: string;
      confirmText?: string;
      cancelText?: string;
    };
    if (!d || !d.requestId) return;
    void openConfirm({
      title: d.title ?? "确认",
      message: d.message ?? "",
      confirmText: d.confirmText,
      cancelText: d.cancelText,
    }).then((ok) => {
      window.dispatchEvent(
        new CustomEvent("electromind:confirm-resolved", {
          detail: { requestId: d.requestId, ok },
        }),
      );
    });
  });

  const disposeRuntimeState = window.desktop.onRuntimeState((state) => {
    const previousThreadId = uiState.runtime.currentThreadId;
    const previousProjectPath = uiState.runtime.projectPath;
    applyRuntimeState(state);
    if (state.currentThreadId !== previousThreadId) {
      clearSandboxPanel();
      void refreshSessions();
      void refreshArtifacts();
    }
    if (state.projectPath !== previousProjectPath) {
      uiState.projectLoadedPath = "";
      if (uiState.activeTab === "files") {
        void ensureProjectPanelLoaded();
      }
    }
  });

  const sandboxStatusTimer = window.setInterval(() => {
    if (uiState.sandboxLoadedThreadId === uiState.runtime.currentThreadId) {
      void refreshSandboxStatus();
    }
  }, 8000);

  window.addEventListener("beforeunload", () => {
    disposeAgentEvents();
    disposeRuntimeState();
    window.clearInterval(sandboxStatusTimer);
  });

  window.addEventListener("blur", () => {
    hideTreeContextMenu();
  });

  applyTheme();
  applyPinState();
  applyWorkbenchChrome();
  renderTerminal();
  applyRightTab();
  applyRuntimeState(initialRuntime);
  // Harness Spine: expose a live SessionManager so the React shell's
  // thread switch/new/delete callbacks actually work.
  const sessionManager = new SessionManager(window.desktop);
  (window as unknown as Record<string, unknown>).__electromindSM =
    sessionManager;
  void sessionManager.bootstrap();
  chatRenderer.showHistorySkeleton();
  await Promise.all([
    refreshSessions(),
    refreshArtifacts(),
    ensureProjectPanelLoaded(),
    window.desktop.requestHistoryReplay(),
  ]);
}

start().catch((error: unknown) => {
  finishBootSplash();
  const root = document.querySelector<HTMLDivElement>("#app");
  if (!root) {
    return;
  }
  // P4.5: 启动错误页用 textContent，不拼 innerHTML。
  const message = error instanceof Error ? error.message : String(error);
  const pre = document.createElement("pre");
  pre.style.padding = "16px";
  pre.style.whiteSpace = "pre-wrap";
  pre.textContent = message;
  root.textContent = "";
  root.appendChild(pre);
});
