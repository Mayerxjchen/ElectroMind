import { ChatRenderer } from "../../../vscode/src/webview/render";
import { ContextUsageRing } from "../../../vscode/src/webview/context-usage";
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
  WireEvent,
} from "../shared/protocol";
import { renderIcon, renderWechatIcon, type DesktopIconName } from "./icons";
import { paintDocsQr } from "./docs-qr";
import { mountToaster, toast } from "./toast";

const INPUT_MAX_HEIGHT_PX = 160;
const LEFT_PANE_WIDTH_PX = 232;
const LEFT_COLLAPSED_WIDTH_PX = 44;
const RIGHT_PANE_WIDTH_PX = 352;
const RIGHT_COLLAPSED_WIDTH_PX = 44;

type ThemeMode = "dark" | "light";
type PanelTab = "project" | "sandbox" | "terminal";
type ProjectPane = "files" | "artifacts";
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
  const value = window.localStorage.getItem("pagent-desktop-theme");
  return value === "light" ? "light" : "dark";
}

function readStoredSidebarPinned(): boolean {
  return window.localStorage.getItem("pagent-desktop-sidebar-pinned") === "1";
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
  const backends = options.availableBackends.length > 0
    ? options.availableBackends
    : (["local"] as SandboxBackendOption[]);
  const backend = backends.includes(draft.backend) ? draft.backend : backends[0];
  const sshHosts = options.sshHosts;
  const images = options.availableImages.length > 0
    ? options.availableImages
    : [options.defaultImage || "pagent:latest"];
  const image = draft.image && images.includes(draft.image)
    ? draft.image
    : (images.includes(options.defaultImage) ? options.defaultImage : images[0]);
  const isContainer =
    backend === "container" || backend === "docker" || backend === "podman";
  const backendCards = backends
    .map((item) => {
      const active = item === backend ? " active" : "";
      return `
        <button class="new-session-backend${active}" type="button" data-backend="${escapeHtml(item)}">
          <span class="new-session-backend-icon" aria-hidden="true">${renderIcon(sessionSandboxIconName(item))}</span>
          <span class="new-session-backend-copy">
            <span class="new-session-backend-label">${escapeHtml(sandboxBackendOptionLabel(item))}</span>
            <span class="new-session-backend-sub">${escapeHtml(sandboxBackendOptionSub(item))}</span>
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
      : `<input class="new-session-input" data-image type="text" value="${escapeHtml(image)}" placeholder="pagent:latest" spellcheck="false" />`
    }
        <div class="new-session-hint">本机 pagent 镜像；browser 可用于渲染 HTML / 导出 PDF。</div>
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
        <input class="new-session-input" data-ssh-workdir type="text" value="${escapeHtml(draft.sshWorkdir)}" placeholder="~/pagent" />
      </label>
    `
    : "";
  return `
    <div class="new-session-form">
      <div class="new-session-field">
        <span class="new-session-label">沙箱类型</span>
        <div class="new-session-backends" data-backend-list style="--backend-count: ${backends.length}">${backendCards}</div>
        <div class="new-session-hint" data-backend-hint>${escapeHtml(sandboxBackendOptionHint(backend))}</div>
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
        <button class="new-session-primary" type="button" data-new-session-confirm>创建会话</button>
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
        <div class="tree-row tree-row-file" style="--tree-indent:${indent}px">
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

function renderShell(appInfo: AppInfo, runtime: RuntimeState): void {
  const root = document.querySelector<HTMLDivElement>("#app");
  if (!root) {
    return;
  }

  root.innerHTML = `
    <div class="desktop-root">
    <div class="desktop-shell ${platformClass(appInfo)}" data-shell>
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
      <div class="desktop-workbench" data-workbench>
        <aside class="pane pane-left" data-left-pane>
          <div class="pane-expanded">
            <div class="pane-topbar">
              <button class="new-task-button" type="button" data-new-task>新建任务</button>
            </div>
            <div class="pane-section-label" data-section-label>会话历史</div>
            <div class="session-list" data-session-list></div>
            <div class="skills-panel" data-skills-panel hidden>
              <div class="skills-list" data-skills-list></div>
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
          </div>
          <div class="pane-collapsed">
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
          </div>
        </aside>

        <div class="pane-resizer" data-resizer="left"></div>

        <section class="pane pane-center">
          <div class="pane-topbar center-topbar">
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
          </div>
          <div class="chat-log" data-chat-log></div>
          <div class="composer-dock">
            <div class="mention-popup" data-mention-popup hidden></div>
            <div class="composer composer-floating">
              <textarea id="prompt" placeholder="给 pagent 下达任务，输入 @ 引用文件"></textarea>
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
          </div>
        </section>

        <div class="pane-resizer" data-resizer="right"></div>

        <aside class="pane pane-right" data-right-pane>
          <div class="pane-expanded">
            <div class="pane-topbar right-topbar">
              <div class="tab-group" role="tablist" aria-label="右侧面板">
                <button class="tab-button active" type="button" data-tab="project">项目</button>
                <button class="tab-button" type="button" data-tab="sandbox">沙箱</button>
                <button class="tab-button" type="button" data-tab="terminal">Log</button>
              </div>
            </div>

            <div class="right-content">
              <section class="right-view active" data-view="project">
                <div class="project-host" data-project-host data-project-pane="files">
                  <div class="file-panel-header project-host-header">
                    <div
                      class="jelly-switch"
                      data-project-pane-switch
                      data-pane="files"
                      role="tablist"
                      aria-label="项目视图"
                    >
                      <span class="jelly-switch-thumb" data-project-pane-thumb aria-hidden="true"></span>
                      <button
                        type="button"
                        class="jelly-switch-option active"
                        data-project-pane="files"
                        role="tab"
                        aria-selected="true"
                      >
                        目录
                      </button>
                      <button
                        type="button"
                        class="jelly-switch-option"
                        data-project-pane="artifacts"
                        role="tab"
                        aria-selected="false"
                      >
                        产物
                        <span class="tab-badge" data-artifact-count>0</span>
                      </button>
                    </div>
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
                  <div class="file-panel project-files-pane" data-project-files>
                    <div class="file-tree" data-project-tree></div>
                  </div>
                  <div class="artifacts-panel project-artifacts-pane" data-artifacts-panel hidden>
                    <div class="artifacts-list" data-artifacts-list></div>
                    <div class="artifact-preview" data-artifact-preview hidden></div>
                  </div>
                </div>
              </section>

              <section class="right-view" data-view="sandbox">
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

              <section class="right-view" data-view="terminal">
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
              <button class="icon-button collapse-right-button" type="button" data-collapse-right title="折叠右栏">
                ${renderIcon("panel-right-close")}
              </button>
            </div>
          </div>

          <div class="pane-collapsed">
            <button class="collapsed-icon" type="button" data-tab="project" title="项目">
              ${renderIcon("folder")}
            </button>
            <button class="collapsed-icon" type="button" data-tab="sandbox" title="沙箱">
              ${renderIcon("folder-tree")}
            </button>
            <button class="collapsed-expand collapsed-expand-bottom" type="button" data-expand-right title="展开右栏">
              ${renderIcon("panel-right-open")}
            </button>
          </div>
        </aside>
      </div>
    </div>
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
              <canvas data-docs-qr-canvas width="220" height="220" aria-label="pagent 文档站二维码"></canvas>
            </div>
            <p class="docs-qr-hint">微信扫一扫，在手机上阅读 pagent 文档</p>
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
                <span class="shortcut-label">收缩左侧</span>
                <div class="shortcut-keys">
                  <kbd class="key-modifier">
                    <span class="key-icon">⌘</span>
                    <span class="key-label">Command</span>
                  </kbd>
                  <kbd>L</kbd>
                </div>
              </div>
              <div class="shortcut-item">
                <span class="shortcut-label">收缩右侧</span>
                <div class="shortcut-keys">
                  <kbd class="key-modifier">
                    <span class="key-icon">⌘</span>
                    <span class="key-label">Command</span>
                  </kbd>
                  <kbd>R</kbd>
                </div>
              </div>
              <div class="shortcut-item">
                <span class="shortcut-label">打开本面板</span>
                <div class="shortcut-keys">
                  <kbd class="key-modifier">
                    <span class="key-icon">⌘</span>
                    <span class="key-label">Command</span>
                  </kbd>
                  <kbd>K</kbd>
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
    </div>
  `;
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
  renderShell(appInfo, initialRuntime);
  mountToaster();

  const workbench = findRequired<HTMLElement>("[data-workbench]");
  const sessionList = findRequired<HTMLElement>("[data-session-list]");
  const sectionLabel = findRequired<HTMLElement>("[data-section-label]");
  const skillsPanel = findRequired<HTMLElement>("[data-skills-panel]");
  const skillsList = findRequired<HTMLElement>("[data-skills-list]");
  const fileTree = findRequired<HTMLElement>("[data-file-tree]");
  const projectTree = findRequired<HTMLElement>("[data-project-tree]");
  const terminalPanel = findRequired<HTMLElement>("[data-terminal-panel]");
  const artifactsList = findRequired<HTMLElement>("[data-artifacts-list]");
  const artifactsPanel = findRequired<HTMLElement>("[data-artifacts-panel]");
  const artifactPreview = findRequired<HTMLElement>("[data-artifact-preview]");
  const artifactCount = findRequired<HTMLElement>("[data-artifact-count]");
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
  const resourceStrip = findRequired<HTMLElement>("[data-resource-strip]");
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

  const uiState = {
    theme: readStoredTheme(),
    activeTab: "project" as PanelTab,
    projectPane: "files" as ProjectPane,
    leftCollapsed: false,
    rightCollapsed: false,
    sidebarDocked: false,
    sidebarPinned: readStoredSidebarPinned(),
    leftWidth: LEFT_PANE_WIDTH_PX,
    rightWidth: RIGHT_PANE_WIDTH_PX,
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
    runtime: initialRuntime,
  };
  const historyDockButton = findRequired<HTMLButtonElement>("[data-history-dock]");
  const skillsButton = findRequired<HTMLButtonElement>("[data-skills-open]");
  const yoloButton = findRequired<HTMLButtonElement>("[data-yolo-toggle]");
  const contextUsageMount = findRequired<HTMLElement>("[data-context-usage-mount]");
  const pinSidebarButton = findRequired<HTMLButtonElement>("[data-pin-sidebar]");
  const projectHost = findRequired<HTMLElement>("[data-project-host]");
  const projectPaneSwitch = findRequired<HTMLElement>("[data-project-pane-switch]");
  const projectFilesPane = findRequired<HTMLElement>("[data-project-files]");
  const refreshProjectButton = findRequired<HTMLButtonElement>("[data-refresh-project]");
  let keepSidebarOpen = false;
  let artifactPreviewPath = "";

  renderArtifactList();

  const chatRenderer = new ChatRenderer(chatLog, (toolCallId, approved) => {
    if (approved) {
      void window.desktop.permitToolCall(toolCallId);
      return;
    }
    void window.desktop.denyToolCall(toolCallId);
  });
  const contextUsageRing = new ContextUsageRing(contextUsageMount);

  function applyTheme(): void {
    document.documentElement.dataset.theme = uiState.theme;
    window.localStorage.setItem("pagent-desktop-theme", uiState.theme);
    const lightOn = uiState.theme === "light";
    titlebarSwitch.dataset.on = String(lightOn);
    titlebarSwitch.setAttribute("aria-pressed", String(lightOn));
    titlebarSwitchThumb.style.transform = lightOn ? "translateX(14px)" : "translateX(0)";
  }

  function applyWorkbenchChrome(): void {
    const leftHidden = uiState.sidebarDocked;
    workbench.dataset.leftCollapsed = String(uiState.leftCollapsed);
    workbench.dataset.rightCollapsed = String(uiState.rightCollapsed);
    workbench.dataset.sidebarDocked = String(uiState.sidebarDocked);
    workbench.style.setProperty(
      "--left-pane-width",
      leftHidden
        ? "0px"
        : `${uiState.leftCollapsed ? LEFT_COLLAPSED_WIDTH_PX : uiState.leftWidth}px`,
    );
    workbench.style.setProperty(
      "--right-pane-width",
      `${uiState.rightCollapsed ? RIGHT_COLLAPSED_WIDTH_PX : uiState.rightWidth}px`,
    );
    workbench.style.setProperty(
      "--left-gap",
      leftHidden || uiState.leftCollapsed ? "0px" : "8px",
    );
    workbench.style.setProperty(
      "--right-gap",
      uiState.rightCollapsed ? "0px" : "8px",
    );
    historyDockButton.hidden = !uiState.sidebarDocked;
  }

  function applyPinState(): void {
    pinSidebarButton.classList.toggle("active", uiState.sidebarPinned);
    pinSidebarButton.title = uiState.sidebarPinned ? "取消钉住" : "钉住侧栏";
    pinSidebarButton.innerHTML = renderIcon(
      uiState.sidebarPinned ? "pin" : "pin-off",
    );
    window.localStorage.setItem(
      "pagent-desktop-sidebar-pinned",
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
    backend: "local" as SandboxBackendOption,
    projectPath: "",
    sshHost: "",
    sshWorkdir: "~/pagent",
    image: "pagent:latest",
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
        onInstallPagent: async () => {
          const result = await window.desktop.installPagentCli();
          if (!result.ok) {
            toast(result.error ?? "安装失败", { type: "error" });
            return;
          }
          currentEnv = await window.desktop.refreshEnvironmentCheck();
          replacePanel();
          toast("pagent 已安装", { type: "success" });
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
      newSessionDraft.image = imageEl.value.trim() || "pagent:latest";
    }
    const sshHostEl = newSessionBody.querySelector<HTMLInputElement>("[data-ssh-host]");
    if (sshHostEl) {
      newSessionDraft.sshHost = sshHostEl.value.trim();
    }
    const sshWorkdirInput = newSessionBody.querySelector<HTMLInputElement>("[data-ssh-workdir]");
    if (sshWorkdirInput) {
      newSessionDraft.sshWorkdir = sshWorkdirInput.value.trim() || "~/pagent";
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
      const backends = options.availableBackends;
      if (!backends.includes(newSessionDraft.backend)) {
        newSessionDraft.backend = backends[0] ?? "local";
      }
      newSessionDraft.projectPath = options.projectPath || uiState.runtime.projectPath;
      if (
        !newSessionDraft.image ||
        (options.availableImages.length > 0 && !options.availableImages.includes(newSessionDraft.image))
      ) {
        newSessionDraft.image = options.defaultImage || options.availableImages[0] || "pagent:latest";
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
    const options: ResetSessionOptions = {
      backend: newSessionDraft.backend,
      projectPath: newSessionDraft.projectPath,
    };
    if (
      newSessionDraft.backend === "container" ||
      newSessionDraft.backend === "docker" ||
      newSessionDraft.backend === "podman"
    ) {
      options.image = newSessionDraft.image.trim() || "pagent:latest";
    }
    if (newSessionDraft.backend === "ssh") {
      options.sshHost = newSessionDraft.sshHost;
      options.sshWorkdir = newSessionDraft.sshWorkdir || "~/pagent";
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

  function renderSkillList(): void {
    if (uiState.skills.length === 0) {
      skillsList.innerHTML = `
        <div class="session-empty">
          <div class="session-empty-title">暂无 Skills</div>
          <div class="session-empty-copy">在 ~/.pagent/skills/ 目录下放置技能即可。</div>
        </div>
      `;
      return;
    }
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

  function renderProjectTree(): void {
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
    artifactCount.textContent = String(uiState.artifacts.length);
    if (artifactPreviewPath && !uiState.artifacts.some((item) => item.path === artifactPreviewPath)) {
      closeArtifactPreview();
    }
  }

  function closeArtifactPreview(): void {
    artifactPreviewPath = "";
    artifactsPanel.classList.remove("preview-open");
    projectHost.classList.remove("preview-open");
    artifactPreview.hidden = true;
    artifactPreview.innerHTML = "";
  }

  async function showArtifactPreview(filePath: string): Promise<void> {
    artifactPreviewPath = filePath;
    artifactsPanel.classList.add("preview-open");
    projectHost.classList.add("preview-open");
    artifactPreview.hidden = false;
    artifactPreview.innerHTML = `<div class="artifact-preview-body artifact-preview-empty">加载中…</div>`;
    const preview = await window.desktop.readArtifact(filePath);
    if (artifactPreviewPath !== filePath) {
      return;
    }
    artifactPreview.innerHTML = renderArtifactPreview(preview);
  }

  function applyProjectPane(): void {
    const pane = uiState.projectPane;
    projectHost.dataset.projectPane = pane;
    projectPaneSwitch.dataset.pane = pane;
    projectFilesPane.hidden = pane !== "files";
    artifactsPanel.hidden = pane !== "artifacts";
    projectPaneSwitch
      .querySelectorAll<HTMLButtonElement>("[data-project-pane]")
      .forEach((button) => {
        const active = button.dataset.projectPane === pane;
        button.classList.toggle("active", active);
        button.setAttribute("aria-selected", active ? "true" : "false");
      });
    if (pane === "files") {
      refreshProjectButton.title = "刷新项目目录";
      refreshProjectButton.setAttribute("aria-label", "刷新项目目录");
    } else {
      refreshProjectButton.title = "刷新产物";
      refreshProjectButton.setAttribute("aria-label", "刷新产物");
    }
    resourceStrip.classList.toggle(
      "hidden",
      uiState.activeTab === "project" && pane === "artifacts",
    );
  }

  function applyRightTab(): void {
    document.querySelectorAll<HTMLElement>("[data-view]").forEach((node) => {
      node.classList.toggle("active", node.dataset.view === uiState.activeTab);
    });
    document.querySelectorAll<HTMLElement>("[data-tab]").forEach((node) => {
      node.classList.toggle("active", node.dataset.tab === uiState.activeTab);
    });
    rightFooter.dataset.tab = uiState.activeTab;
    applyProjectPane();
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
    uiState.projectTreeNodes = await window.desktop.listProjectTree();
    uiState.projectLoadedPath = uiState.runtime.projectPath;
    uiState.expandedProjectTree = new Set(
      uiState.projectTreeNodes
        .filter((node) => node.kind === "dir")
        .map((node) => node.id),
    );
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
  }

  async function cancelRun(): Promise<void> {
    if (uiState.activityState !== "running") {
      return;
    }
    await window.desktop.sendWireCommand({ cmd: "cancel" });
  }

  async function sendMessage(): Promise<void> {
    if (uiState.activityState === "running") {
      return;
    }
    const text = promptInput.value;
    if (!text.trim()) {
      return;
    }
    chatRenderer.addUser(text);
    promptInput.value = "";
    resizePrompt(promptInput);
    setComposerHint("");
    uiState.activityState = "running";
    applyActivityState();
    appendTerminalEntry("command", text);
    try {
      await window.desktop.sendUserInput(text);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      chatRenderer.showError(message);
      uiState.activityState = "error";
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

  function bindResizer(side: "left" | "right"): void {
    const handle = findRequired<HTMLElement>(`[data-resizer="${side}"]`);
    handle.addEventListener("pointerdown", (event) => {
      if ((side === "left" && uiState.leftCollapsed) || (side === "right" && uiState.rightCollapsed)) {
        return;
      }
      const startX = event.clientX;
      const startWidth = side === "left" ? uiState.leftWidth : uiState.rightWidth;
      handle.setPointerCapture(event.pointerId);

      const onMove = (moveEvent: PointerEvent) => {
        const delta = moveEvent.clientX - startX;
        if (side === "left") {
          uiState.leftWidth = Math.max(200, Math.min(320, startWidth + delta));
        } else {
          uiState.rightWidth = Math.max(300, Math.min(420, startWidth - delta));
        }
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
    contextUsageRing.handleWireEvent(event);
    if (
      event.method === "RunBegin" ||
      event.method === "ReasoningDelta" ||
      event.method === "TextDelta" ||
      event.method === "ToolCallBegin"
    ) {
      uiState.activityState = "running";
      if (event.method === "RunBegin") {
        setComposerHint("");
      }
    } else if (event.method === "RunEnd") {
      uiState.activityState = "sleeping";
      void refreshSessions();
      void refreshArtifacts();
    } else if (event.method === "HistoryReplay") {
      const threadId = String(event.params.thread_id ?? "");
      // 空 thread_id 通常是 reset/resume 失败后的占位回放，等后续 Error 定态。
      if (threadId) {
        uiState.activityState = "sleeping";
        setComposerHint("");
      }
      void refreshSessions();
      void refreshArtifacts();
    } else if (event.method === "Error") {
      uiState.activityState = "error";
      const message = String(event.params.message ?? "").trim();
      if (message) {
        setComposerHint(message);
      }
      // 新建/恢复会话失败时没有可用 thread，清掉沙箱侧状态避免显示陈旧目录。
      const where = String(event.params.where ?? "");
      if (where === "reset" || where === "resume" || where === "open") {
        clearSandboxPanel();
        void refreshSessions();
      }
    }

    if (event.method === "Skills") {
      uiState.skills = (event.params.skills as Skill[] | undefined) ?? [];
      renderSkillList();
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
    if (uiState.activityState === "running") {
      void cancelRun();
      return;
    }
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
          "pagent:latest";
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
  findRequired<HTMLElement>("[data-collapse-right]").addEventListener("click", () => {
    uiState.rightCollapsed = true;
    applyWorkbenchChrome();
  });
  findRequired<HTMLElement>("[data-expand-right]").addEventListener("click", () => {
    uiState.rightCollapsed = false;
    applyWorkbenchChrome();
  });
  findRequired<HTMLElement>("[data-open-latest]").addEventListener("click", () => {
    void openLatestSession();
  });

  document.querySelectorAll<HTMLElement>("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      const tab = button.dataset.tab;
      if (tab !== "project" && tab !== "sandbox" && tab !== "terminal") {
        return;
      }
      uiState.activeTab = tab;
      uiState.rightCollapsed = false;
      applyWorkbenchChrome();
      applyRightTab();
      if (tab === "sandbox") {
        void ensureSandboxPanelLoaded();
      }
      if (tab === "project") {
        if (uiState.projectPane === "files") {
          void ensureProjectPanelLoaded();
        } else {
          void refreshArtifacts();
        }
      }
    });
  });

  projectPaneSwitch
    .querySelectorAll<HTMLButtonElement>("[data-project-pane]")
    .forEach((button) => {
      button.addEventListener("click", () => {
        const pane = button.dataset.projectPane;
        if (pane !== "files" && pane !== "artifacts") {
          return;
        }
        if (pane === uiState.projectPane) {
          return;
        }
        if (pane === "files") {
          closeArtifactPreview();
        }
        uiState.projectPane = pane;
        applyProjectPane();
        if (pane === "files") {
          void ensureProjectPanelLoaded();
        } else {
          void refreshArtifacts();
        }
      });
    });

  findRequired<HTMLButtonElement>("[data-refresh-sandbox]").addEventListener("click", () => {
    void forceRefreshSandboxPanel();
  });
  refreshProjectButton.addEventListener("click", () => {
    if (uiState.projectPane === "artifacts") {
      void refreshArtifacts();
      return;
    }
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
      return;
    }
    if (!event.metaKey) {
      return;
    }
    if (event.key === "l" || event.key === "L") {
      event.preventDefault();
      uiState.leftCollapsed = !uiState.leftCollapsed;
      uiState.sidebarDocked = false;
      applyWorkbenchChrome();
      syncComposerDock();
    } else if (event.key === "r" || event.key === "R") {
      event.preventDefault();
      uiState.rightCollapsed = !uiState.rightCollapsed;
      applyWorkbenchChrome();
    } else if (event.key === "k" || event.key === "K") {
      event.preventDefault();
      openShortcutsModal();
    }
  });

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
  });

  bindResizer("left");
  bindResizer("right");

  const disposeAgentEvents = window.desktop.onAgentEvent((message) => {
    if (message.type === "wireEvent") {
      syncWireEvent(message.event);
      chatRenderer.handleEvent(message.event);
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
      if (uiState.activeTab === "project") {
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

  applyTheme();
  applyPinState();
  applyWorkbenchChrome();
  renderTerminal();
  applyRightTab();
  applyRuntimeState(initialRuntime);
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
  const message = error instanceof Error ? error.message : String(error);
  root.innerHTML = `<pre>${escapeHtml(message)}</pre>`;
});
