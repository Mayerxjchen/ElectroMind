import { ChatRenderer } from "../../../vscode/src/webview/render";
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
  ArtifactPreview,
  ArtifactSummary,
  MentionFile,
  MentionSource,
  RuntimeState,
  SandboxStatus,
  SandboxTreeNode,
  Skill,
  ThreadMeta,
  ThreadSummary,
  WireEvent,
} from "../shared/protocol";
import { renderIcon, type DesktopIconName } from "./icons";

const INPUT_MAX_HEIGHT_PX = 160;
const LEFT_PANE_WIDTH_PX = 232;
const LEFT_COLLAPSED_WIDTH_PX = 44;
const RIGHT_PANE_WIDTH_PX = 352;
const RIGHT_COLLAPSED_WIDTH_PX = 44;

type ThemeMode = "dark" | "light";
type PanelTab = "sandbox" | "terminal" | "artifacts";
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
  if (backend === "docker" || backend === "podman") {
    return "container";
  }
  if (backend === "ssh") {
    return "globe";
  }
  return "server";
}

function sessionSandboxLabel(backend: string): string {
  if (backend === "docker" || backend === "podman") {
    return "container";
  }
  if (backend === "ssh") {
    return "ssh";
  }
  return "local";
}

function sessionSandboxIconName(backend: string): DesktopIconName {
  if (backend === "docker" || backend === "podman") {
    return "container";
  }
  if (backend === "ssh") {
    return "globe";
  }
  return "hard-drive";
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
          <button class="session-meta-button" type="button" data-thread-meta data-thread-id="${escapeHtml(session.id)}" title="查看会话信息">
            ${renderIcon("circle-alert")}
          </button>
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

function renderSettings(settings: AppSettings): string {
  if (!settings.exists) {
    return `
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

function renderArtifacts(artifacts: ArtifactSummary[], rootPath: string): string {
  const header = `
    <div class="artifact-root">
      <div class="artifact-root-label">本机路径</div>
      <div class="artifact-root-path" title="${escapeHtml(rootPath)}">${escapeHtml(rootPath)}</div>
    </div>
  `;
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
          <button class="titlebar-action" type="button" data-shortcuts-open title="快捷键" aria-label="快捷键">
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
              <div class="user-chip">
                <span class="user-avatar">${escapeHtml(appInfo.userName.charAt(0).toUpperCase())}</span>
                <span class="user-name">${escapeHtml(appInfo.userName)}</span>
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
              <button class="collapsed-icon user" type="button" title="${escapeHtml(appInfo.userName)}">
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
                    class="history-dock-dot"
                    data-history-dock
                    hidden
                    title="展开会话列表"
                    aria-label="展开会话列表"
                  >
                    ${renderIcon("history")}
                  </button>
                  <span class="desktop-composer-hint" data-last-error></span>
                </div>
                <button class="composer-btn primary" data-send-message title="发送">
                  ${renderIcon("arrow-up")}
                </button>
              </div>
            </div>
          </div>
        </section>

        <div class="pane-resizer" data-resizer="right"></div>

        <aside class="pane pane-right" data-right-pane>
          <div class="pane-expanded">
            <div class="pane-topbar right-topbar">
              <div class="tab-group" role="tablist" aria-label="右侧面板">
                <button class="tab-button active" type="button" data-tab="sandbox">沙箱</button>
                <button class="tab-button" type="button" data-tab="terminal">Log</button>
                <button class="tab-button" type="button" data-tab="artifacts">
                  Artifacts
                  <span class="tab-badge" data-artifact-count>0</span>
                </button>
              </div>
              <span class="panel-lamp sleeping" data-panel-lamp aria-hidden="true"></span>
            </div>

            <div class="right-content">
              <section class="right-view active" data-view="sandbox">
                <div class="file-panel">
                  <div class="file-panel-header">文件系统</div>
                  <div class="file-tree" data-file-tree></div>
                </div>
              </section>

              <section class="right-view" data-view="terminal">
                <div class="terminal-panel" data-terminal-panel></div>
              </section>

              <section class="right-view" data-view="artifacts">
                <div class="artifacts-panel" data-artifacts-panel>
                  <div class="file-panel-header">用户产物</div>
                  <div class="artifacts-list" data-artifacts-list></div>
                  <div class="artifact-preview" data-artifact-preview hidden></div>
                </div>
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
            <button class="collapsed-icon" type="button" data-tab="sandbox" title="沙箱">
              ${renderIcon("folder-tree")}
            </button>
            <button class="collapsed-expand collapsed-expand-bottom" type="button" data-expand-right title="展开右栏">
              ${renderIcon("panel-right-open")}
            </button>
          </div>
        </aside>
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
      <div class="desktop-modal" data-shortcuts-modal hidden>
        <div class="desktop-modal-backdrop" data-shortcuts-close></div>
        <section class="desktop-modal-card shortcuts-modal-card" role="dialog" aria-modal="true" aria-labelledby="shortcuts-title">
          <div class="desktop-modal-header">
            <div id="shortcuts-title" class="desktop-modal-title">快捷键</div>
            <button class="modal-close-button" type="button" data-shortcuts-close title="关闭" aria-label="关闭">
              ${renderIcon("x")}
            </button>
          </div>
          <div class="desktop-modal-body">
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
                <span class="shortcut-label">打开快捷键面板</span>
                <div class="shortcut-keys">
                  <kbd class="key-modifier">
                    <span class="key-icon">⌘</span>
                    <span class="key-label">Command</span>
                  </kbd>
                  <kbd>K</kbd>
                </div>
              </div>
            </div>
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

async function start(): Promise<void> {
  const [appInfo, initialRuntime] = await Promise.all([
    window.desktop.getAppInfo(),
    window.desktop.getRuntimeState(),
  ]);
  renderShell(appInfo, initialRuntime);

  const workbench = findRequired<HTMLElement>("[data-workbench]");
  const sessionList = findRequired<HTMLElement>("[data-session-list]");
  const sectionLabel = findRequired<HTMLElement>("[data-section-label]");
  const skillsPanel = findRequired<HTMLElement>("[data-skills-panel]");
  const skillsList = findRequired<HTMLElement>("[data-skills-list]");
  const fileTree = findRequired<HTMLElement>("[data-file-tree]");
  const terminalPanel = findRequired<HTMLElement>("[data-terminal-panel]");
  const artifactsList = findRequired<HTMLElement>("[data-artifacts-list]");
  const artifactsPanel = findRequired<HTMLElement>("[data-artifacts-panel]");
  const artifactPreview = findRequired<HTMLElement>("[data-artifact-preview]");
  const artifactCount = findRequired<HTMLElement>("[data-artifact-count]");
  const chatLog = findRequired<HTMLElement>("[data-chat-log]");
  const promptInput = findRequired<HTMLTextAreaElement>("#prompt");
  const mentionPopup = findRequired<HTMLElement>("[data-mention-popup]");
  const sendMessageButton = findRequired<HTMLButtonElement>("[data-send-message]");
  const errorText = findRequired<HTMLElement>("[data-last-error]");
  const taskTitle = findRequired<HTMLElement>("[data-task-title]");
  const projectButton = findRequired<HTMLElement>("[data-select-project]");
  const projectText = findRequired<HTMLElement>("[data-project-label]");
  const sandboxBackendIcon = findRequired<HTMLElement>("[data-sandbox-backend-icon]");
  const sandboxBackend = findRequired<HTMLElement>("[data-sandbox-backend]");
  const sandboxPill = findRequired<HTMLElement>("[data-sandbox-pill]");
  const panelLamp = findRequired<HTMLElement>("[data-panel-lamp]");
  const resourceStrip = findRequired<HTMLElement>("[data-resource-strip]");
  const rightFooter = findRequired<HTMLElement>("[data-right-footer]");
  const threadMetaModal = findRequired<HTMLElement>("[data-thread-meta-modal]");
  const threadMetaBody = findRequired<HTMLElement>("[data-thread-meta-body]");
  const settingsOpenButton = findRequired<HTMLButtonElement>("[data-settings-open]");
  const documentationButton = findRequired<HTMLButtonElement>("[data-docs-open]");
  const shortcutsOpenButton = findRequired<HTMLButtonElement>("[data-shortcuts-open]");
  const shortcutsModal = findRequired<HTMLElement>("[data-shortcuts-modal]");
  const titlebarSwitch = findRequired<HTMLElement>("[data-titlebar-switch]");
  const titlebarSwitchThumb = findRequired<HTMLElement>("[data-titlebar-switch-thumb]");
  const settingsModal = findRequired<HTMLElement>("[data-settings-modal]");
  const settingsBody = findRequired<HTMLElement>("[data-settings-body]");

  const uiState = {
    theme: readStoredTheme(),
    activeTab: "sandbox" as PanelTab,
    leftCollapsed: false,
    rightCollapsed: false,
    sidebarDocked: false,
    sidebarPinned: readStoredSidebarPinned(),
    leftWidth: LEFT_PANE_WIDTH_PX,
    rightWidth: RIGHT_PANE_WIDTH_PX,
    activityState: "sleeping" as ActivityState,
    terminalEntries: [] as TerminalEntry[],
    expandedTree: new Set<string>(["app"]),
    sandboxTree: [] as SandboxTreeNode[],
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
  const pinSidebarButton = findRequired<HTMLButtonElement>("[data-pin-sidebar]");
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
      const settings = await window.desktop.getSettings();
      if (settingsModal.hidden || settingsRequestId !== requestId) {
        return;
      }
      settingsBody.innerHTML = renderSettings(settings);
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

  function openShortcutsModal(): void {
    window.clearTimeout(shortcutsModalCloseTimer);
    shortcutsModal.hidden = false;
    window.requestAnimationFrame(() => {
      shortcutsModal.classList.add("is-open");
    });
  }

  function closeShortcutsModal(): void {
    if (shortcutsModal.hidden) {
      return;
    }
    shortcutsModal.classList.remove("is-open");
    window.clearTimeout(shortcutsModalCloseTimer);
    shortcutsModalCloseTimer = window.setTimeout(() => {
      shortcutsModal.hidden = true;
    }, 140);
  }

  function applyActivityState(): void {
    const stateClass = uiState.activityState;
    panelLamp.className = `panel-lamp ${stateClass}`;
    const running = uiState.activityState === "running";
    sendMessageButton.disabled = running;
    sendMessageButton.title = running ? "正在执行" : "发送";
    sendMessageButton.setAttribute("aria-label", running ? "正在执行" : "发送");
    sendMessageButton.innerHTML = running
      ? renderIcon("loader-circle", "desktop-icon spinning")
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

  function renderTree(): void {
    if (uiState.sandboxTree.length === 0) {
      fileTree.innerHTML = `
        <div class="session-empty">
          <div class="session-empty-title">沙箱里还没有文件</div>
          <div class="session-empty-copy">沙箱连接后，这里会展示当前 workdir 的目录树。</div>
        </div>
      `;
      return;
    }
    fileTree.innerHTML = renderTreeRows(uiState.sandboxTree, uiState.expandedTree);
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
      node.classList.toggle("active", node.dataset.view === uiState.activeTab);
    });
    document.querySelectorAll<HTMLElement>("[data-tab]").forEach((node) => {
      node.classList.toggle("active", node.dataset.tab === uiState.activeTab);
    });
    rightFooter.dataset.tab = uiState.activeTab;
    resourceStrip.classList.toggle("hidden", uiState.activeTab === "artifacts");
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
  }

  async function ensureSandboxPanelLoaded(): Promise<void> {
    const threadId = uiState.runtime.currentThreadId ?? "";
    if (!threadId || uiState.sandboxLoadedThreadId === threadId) {
      return;
    }
    await Promise.all([
      refreshSandboxTree(),
      refreshSandboxStatus(),
    ]);
  }

  function applyRuntimeState(state: RuntimeState): void {
    uiState.runtime = state;
    if (state.status === "error") {
      uiState.activityState = "error";
    } else if (uiState.activityState === "error") {
      uiState.activityState = "sleeping";
    }
    errorText.textContent = state.lastError ?? "";
    applyHeader();
    applyActivityState();
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
    if (
      event.method === "RunBegin" ||
      event.method === "ReasoningDelta" ||
      event.method === "TextDelta" ||
      event.method === "ToolCallBegin"
    ) {
      uiState.activityState = "running";
    } else if (event.method === "RunEnd" || event.method === "HistoryReplay") {
      uiState.activityState = "sleeping";
      void refreshSessions();
      void refreshArtifacts();
    } else if (event.method === "Error") {
      uiState.activityState = "error";
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

  sendMessageButton.addEventListener("click", () => {
    void sendMessage();
  });

  document.querySelectorAll<HTMLElement>("[data-theme-toggle]").forEach((button) => {
    button.addEventListener("click", toggleTheme);
  });

  document.querySelectorAll<HTMLElement>("[data-new-task]").forEach((button) => {
    button.addEventListener("click", async () => {
      chatRenderer.showHistorySkeleton();
      uiState.activityState = "sleeping";
      applyActivityState();
      await window.desktop.resetSession();
      await refreshSessions();
      await refreshArtifacts();
    });
  });

  projectButton.addEventListener("click", async () => {
    const state = await window.desktop.selectProject();
    applyRuntimeState(state);
    chatRenderer.showHistorySkeleton();
    uiState.activityState = "sleeping";
    applyActivityState();
    await window.desktop.resetSession();
    await refreshSessions();
    await refreshArtifacts();
  });

  settingsOpenButton.addEventListener("click", () => {
    void openSettingsModal();
  });

  documentationButton.addEventListener("click", () => {
    void window.desktop.openDocumentation();
  });

  shortcutsOpenButton.addEventListener("click", () => {
    openShortcutsModal();
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
      if (tab !== "sandbox" && tab !== "terminal" && tab !== "artifacts") {
        return;
      }
      uiState.activeTab = tab;
      uiState.rightCollapsed = false;
      applyWorkbenchChrome();
      applyRightTab();
      if (tab === "sandbox") {
        void ensureSandboxPanelLoaded();
      }
    });
  });

  sessionList.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
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

  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (!threadMetaModal.hidden) {
        closeThreadMetaModal();
      }
      if (!settingsModal.hidden) {
        closeSettingsModal();
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
    if (!errorText.textContent) {
      errorText.textContent = text;
    }
    appendTerminalEntry("stderr", text);
  });

  const disposeRuntimeState = window.desktop.onRuntimeState((state) => {
    const previousThreadId = uiState.runtime.currentThreadId;
    applyRuntimeState(state);
    if (state.currentThreadId !== previousThreadId) {
      clearSandboxPanel();
      void refreshSessions();
      void refreshArtifacts();
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
    window.desktop.requestHistoryReplay(),
  ]);
}

start().catch((error: unknown) => {
  const root = document.querySelector<HTMLDivElement>("#app");
  if (!root) {
    return;
  }
  const message = error instanceof Error ? error.message : String(error);
  root.innerHTML = `<pre>${escapeHtml(message)}</pre>`;
});
