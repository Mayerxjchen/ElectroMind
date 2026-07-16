import { ChatRenderer } from "../../../vscode/src/webview/render";
import type {
  AppInfo,
  ArtifactSummary,
  RuntimeState,
  SandboxStatus,
  SandboxTreeNode,
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

function sandboxLabel(runtime: RuntimeState): string {
  if (!runtime.currentThreadId) {
    return "sbx-local";
  }
  const suffix = runtime.currentThreadId.replace(/^thread-/, "").slice(-6);
  return `sbx-${suffix || "local"}`;
}

function projectLabel(runtime: RuntimeState): string {
  const path = runtime.projectPath;
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] || path || "default";
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

function sandboxPresenceLabel(runtime: RuntimeState): string {
  if (!runtime.currentThreadId) {
    return "未启动";
  }
  if (!runtime.sandboxBackend && runtime.sandboxAlive === undefined) {
    return "同步中";
  }
  if (runtime.sandboxAlive === true) {
    return "在线";
  }
  if (runtime.sandboxAlive === false) {
    return "离线";
  }
  return "检查中";
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
        <div class="session-empty-copy">点击上方的新建任务开始第一条对话。</div>
      </div>
    `;
  }

  return sessions
    .map((session) => {
      const isCurrent = session.id === currentThreadId;
      const relativeTime = session.relativeTime || "刚刚";
      return `
        <div
          class="session-item${isCurrent ? " current" : ""}"
          data-thread-id="${escapeHtml(session.id)}"
        >
          <button class="session-open" type="button" data-thread-open data-thread-id="${escapeHtml(session.id)}">
            <span class="session-status${isCurrent ? " current" : ""}"></span>
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

function renderArtifacts(artifacts: ArtifactSummary[]): string {
  if (artifacts.length === 0) {
    return `
      <div class="session-empty">
        <div class="session-empty-copy">当前项目还没有产物。</div>
      </div>
    `;
  }
  return artifacts.map((artifact) => `
    <div class="artifact-row">
      <span class="artifact-icon">${renderIcon(artifactIcon(artifact.name))}</span>
      <div class="artifact-main">
        <div class="artifact-name">${escapeHtml(artifact.name)}</div>
        <div class="artifact-meta">${formatBytes(artifact.size)} · ${new Date(artifact.mtimeMs).toLocaleString()}</div>
      </div>
      <button class="artifact-download" type="button" data-artifact-path="${escapeHtml(artifact.path)}">
        下载
      </button>
    </div>
  `).join("");
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
      <div class="desktop-titlebar" aria-hidden="true"></div>
      <div class="desktop-workbench" data-workbench>
        <aside class="pane pane-left" data-left-pane>
          <div class="pane-expanded">
            <div class="pane-topbar">
              <button class="new-task-button" type="button" data-new-task>新建任务</button>
            </div>
            <div class="pane-section-label">会话历史</div>
            <div class="session-list" data-session-list></div>
            <div class="left-footer">
              <div class="user-chip">
                <span class="user-avatar">P</span>
                <span class="user-name">pagent</span>
              </div>
              <div class="left-footer-actions">
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
              <button class="collapsed-icon user" type="button" title="当前用户">
                <span class="user-avatar small">P</span>
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
              <span class="center-pill center-pill-muted">
                <span class="center-pill-icon" aria-hidden="true">${renderIcon("layers")}</span>
                <span data-sandbox-id>${sandboxLabel(runtime)}</span>
              </span>
              <span class="center-pill">
                <span class="center-pill-icon" data-sandbox-backend-icon aria-hidden="true">${renderIcon(sandboxBackendIconName(runtime))}</span>
                <span data-sandbox-backend>${sandboxBackendLabel(runtime)}</span>
              </span>
              <span class="center-presence ${sandboxPresenceClass(runtime)}" data-sandbox-presence>
                <span class="status-dot"></span>
                <span class="center-presence-text" data-sandbox-presence-text>${sandboxPresenceLabel(runtime)}</span>
              </span>
            </div>
          </div>
          <div class="chat-log" data-chat-log></div>
          <div class="composer-dock">
            <div class="composer composer-floating">
              <textarea id="prompt" placeholder="给 pagent 下达任务，支持 @ 引用文件"></textarea>
              <div class="composer-actions">
                <div class="composer-actions-start">
                  <span class="desktop-composer-hint" data-last-error>${runtime.lastError ?? ""}</span>
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
                <div class="artifacts-panel">
                  <div class="file-panel-header">用户产物</div>
                  <div class="artifacts-list" data-artifacts-list></div>
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
            <button class="collapsed-expand" type="button" data-expand-right title="展开右栏">
              ${renderIcon("panel-right-open")}
            </button>
            <button class="collapsed-icon" type="button" data-tab="sandbox" title="沙箱">
              ${renderIcon("folder-tree")}
            </button>
            <div class="collapsed-right-status">
              <span class="panel-lamp sleeping" data-panel-lamp-mini aria-hidden="true"></span>
            </div>
          </div>
        </aside>
      </div>
      <div class="desktop-modal" data-thread-meta-modal hidden>
        <div class="desktop-modal-backdrop" data-thread-meta-close></div>
        <section class="desktop-modal-card" role="dialog" aria-modal="true" aria-labelledby="thread-meta-title">
          <div class="desktop-modal-header">
            <div id="thread-meta-title" class="desktop-modal-title">会话信息</div>
            <button class="icon-button" type="button" data-thread-meta-close title="关闭">
              ${renderIcon("x")}
            </button>
          </div>
          <div class="desktop-modal-body" data-thread-meta-body></div>
        </section>
      </div>
    </div>
  `;
}

function resizePrompt(prompt: HTMLTextAreaElement): void {
  prompt.style.height = "0px";
  prompt.style.height = `${Math.min(prompt.scrollHeight, INPUT_MAX_HEIGHT_PX)}px`;
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

async function start(): Promise<void> {
  const [appInfo, initialRuntime] = await Promise.all([
    window.desktop.getAppInfo(),
    window.desktop.getRuntimeState(),
  ]);
  renderShell(appInfo, initialRuntime);

  const workbench = findRequired<HTMLElement>("[data-workbench]");
  const sessionList = findRequired<HTMLElement>("[data-session-list]");
  const fileTree = findRequired<HTMLElement>("[data-file-tree]");
  const terminalPanel = findRequired<HTMLElement>("[data-terminal-panel]");
  const artifactsList = findRequired<HTMLElement>("[data-artifacts-list]");
  const artifactCount = findRequired<HTMLElement>("[data-artifact-count]");
  const chatLog = findRequired<HTMLElement>("[data-chat-log]");
  const promptInput = findRequired<HTMLTextAreaElement>("#prompt");
  const sendMessageButton = findRequired<HTMLButtonElement>("[data-send-message]");
  const errorText = findRequired<HTMLElement>("[data-last-error]");
  const taskTitle = findRequired<HTMLElement>("[data-task-title]");
  const projectButton = findRequired<HTMLElement>("[data-select-project]");
  const projectText = findRequired<HTMLElement>("[data-project-label]");
  const sandboxId = findRequired<HTMLElement>("[data-sandbox-id]");
  const sandboxBackendIcon = findRequired<HTMLElement>("[data-sandbox-backend-icon]");
  const sandboxBackend = findRequired<HTMLElement>("[data-sandbox-backend]");
  const sandboxPresence = findRequired<HTMLElement>("[data-sandbox-presence]");
  const sandboxPresenceText = findRequired<HTMLElement>("[data-sandbox-presence-text]");
  const panelLamp = findRequired<HTMLElement>("[data-panel-lamp]");
  const panelLampMini = findRequired<HTMLElement>("[data-panel-lamp-mini]");
  const resourceStrip = findRequired<HTMLElement>("[data-resource-strip]");
  const rightFooter = findRequired<HTMLElement>("[data-right-footer]");
  const threadMetaModal = findRequired<HTMLElement>("[data-thread-meta-modal]");
  const threadMetaBody = findRequired<HTMLElement>("[data-thread-meta-body]");

  const uiState = {
    theme: readStoredTheme(),
    activeTab: "sandbox" as PanelTab,
    leftCollapsed: false,
    rightCollapsed: false,
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
    runtime: initialRuntime,
  };

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
  }

  function applyWorkbenchChrome(): void {
    workbench.dataset.leftCollapsed = String(uiState.leftCollapsed);
    workbench.dataset.rightCollapsed = String(uiState.rightCollapsed);
    workbench.style.setProperty(
      "--left-pane-width",
      `${uiState.leftCollapsed ? LEFT_COLLAPSED_WIDTH_PX : uiState.leftWidth}px`,
    );
    workbench.style.setProperty(
      "--right-pane-width",
      `${uiState.rightCollapsed ? RIGHT_COLLAPSED_WIDTH_PX : uiState.rightWidth}px`,
    );
    workbench.style.setProperty(
      "--left-gap",
      uiState.leftCollapsed ? "0px" : "8px",
    );
    workbench.style.setProperty(
      "--right-gap",
      uiState.rightCollapsed ? "0px" : "8px",
    );
  }

  function closeThreadMetaModal(): void {
    threadMetaModal.hidden = true;
    threadMetaBody.innerHTML = "";
  }

  async function openThreadMetaModal(threadId: string): Promise<void> {
    const session = uiState.sessions.find((item) => item.id === threadId);
    threadMetaModal.hidden = false;
    threadMetaBody.innerHTML = `
      <div class="thread-meta-loading">正在读取会话信息...</div>
    `;
    try {
      const meta = await window.desktop.getThreadMeta(threadId);
      threadMetaBody.innerHTML = renderThreadMeta(meta, session);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      threadMetaBody.innerHTML = `
        <div class="thread-meta-error">${escapeHtml(message)}</div>
      `;
    }
  }

  function applyActivityState(): void {
    const stateClass = uiState.activityState;
    panelLamp.className = `panel-lamp ${stateClass}`;
    panelLampMini.className = `panel-lamp ${stateClass}`;

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
    sandboxId.textContent = sandboxLabel(uiState.runtime);
    sandboxBackendIcon.innerHTML = renderIcon(sandboxBackendIconName(uiState.runtime));
    sandboxBackend.textContent = sandboxBackendLabel(uiState.runtime);
    sandboxPresence.className = `center-presence ${sandboxPresenceClass(uiState.runtime)}`;
    sandboxPresenceText.textContent = sandboxPresenceLabel(uiState.runtime);
  }

  function renderSessions(): void {
    sessionList.innerHTML = renderSessionList(
      uiState.sessions,
      uiState.runtime.currentThreadId ?? "",
    );
    applyHeader();
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
    artifactsList.innerHTML = renderArtifacts(uiState.artifacts);
    artifactCount.textContent = String(uiState.artifacts.length);
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
  }

  promptInput.addEventListener("input", () => resizePrompt(promptInput));
  promptInput.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) {
      return;
    }
    event.preventDefault();
    void sendMessage();
  });
  resizePrompt(promptInput);

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

  findRequired<HTMLElement>("[data-collapse-left]").addEventListener("click", () => {
    uiState.leftCollapsed = true;
    applyWorkbenchChrome();
  });
  findRequired<HTMLElement>("[data-expand-left]").addEventListener("click", () => {
    uiState.leftCollapsed = false;
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

  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !threadMetaModal.hidden) {
      closeThreadMetaModal();
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
    const button = target.closest<HTMLButtonElement>("[data-artifact-path]");
    const artifactPath = button?.dataset.artifactPath;
    if (!artifactPath) {
      return;
    }
    void window.desktop.openArtifact(artifactPath);
  });

  bindResizer("left");
  bindResizer("right");

  const disposeAgentEvents = window.desktop.onAgentEvent((message) => {
    if (message.type === "wireEvent") {
      syncWireEvent(message.event);
      chatRenderer.handleEvent(message.event);
      return;
    }
    if (!errorText.textContent) {
      errorText.textContent = message.text.trim();
    }
    appendTerminalEntry("stderr", message.text);
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
