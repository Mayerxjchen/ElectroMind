// 视图层入口（第 6 课）。
//
// 这段代码跑在 Webview 沙箱里：没有 Node，没有 vscode API，只有浏览器 DOM 和
// acquireVsCodeApi() 给的受限通道。第 6 课：把宿主转发的事件交给 ChatRenderer，
// 用户输入本地上屏 + 发给宿主。

import type {
  HostToView,
  SandboxMode,
  SlashCommand,
  ViewToHost,
} from "../protocol";
import { ChatRenderer } from "./render";
import { ContextUsageRing } from "./context-usage";

// acquireVsCodeApi 只能调用一次，返回视图与宿主通信的唯一句柄。
// 由 VS Code 注入到 webview 全局，类型没有官方声明，这里就近声明其形状。
declare function acquireVsCodeApi(): {
  postMessage(message: ViewToHost): void;
};

const vscodeApi = acquireVsCodeApi();

// textarea 自适应高度上限（px）：超过则内部滚动，避免输入区撑满整个视图。
const INPUT_MAX_HEIGHT_PX = 160;

/** 输入框旁的斜杠命令菜单：由后端下发的命令清单驱动，支持按 / 后文本过滤、
 *  上下键导航、回车/点击选中。选中后把 `/命令` 填进输入框并立即发送。 */
class SlashMenu {
  private commands: SlashCommand[] = [];
  private filtered: SlashCommand[] = [];
  private active = 0;
  private open = false;
  private preview = false;
  private hideTimer: number | undefined;

  constructor(
    private readonly menu: HTMLElement,
    private readonly input: HTMLTextAreaElement,
    private readonly onPick: () => void,
  ) { }

  /** 接收后端下发的命令清单。 */
  setCommands(commands: SlashCommand[]): void {
    this.commands = commands;
    if (this.preview) {
      this.show("");
      return;
    }
    if (this.input.value.startsWith("/")) {
      this.show(this.filterText());
    }
  }

  /** 斜杠按钮点击：菜单已开则收起；否则确保输入框以 / 起头并打开菜单。 */
  toggleFromButton(): void {
    this.cancelPreviewHide();
    if (this.open && !this.preview) {
      this.hide();
      return;
    }
    this.preview = false;
    if (!this.input.value.startsWith("/")) {
      this.input.value = "/";
    }
    this.input.focus();
    this.show(this.filterText());
  }

  /** 鼠标移到斜杠按钮时预览全部后端命令，不改动输入内容。 */
  previewFromButton(): void {
    this.cancelPreviewHide();
    this.preview = !this.input.value.startsWith("/");
    this.show(this.preview ? "" : this.filterText());
  }

  /** 给指针从按钮移动到浮层留出时间，避免菜单经过间隙时闪退。 */
  schedulePreviewHide(): void {
    if (!this.preview) {
      return;
    }
    this.cancelPreviewHide();
    this.hideTimer = window.setTimeout(() => this.hide(), 180);
  }

  cancelPreviewHide(): void {
    if (this.hideTimer === undefined) {
      return;
    }
    window.clearTimeout(this.hideTimer);
    this.hideTimer = undefined;
  }

  /** 输入内容变化：行首是 / 则按其后文本过滤展示，否则收起。 */
  syncFromInput(): void {
    this.preview = false;
    if (!this.input.value.startsWith("/")) {
      this.hide();
      return;
    }
    this.show(this.filterText());
  }

  /** 菜单打开时拦截方向键/回车/Esc；返回 true 表示已消费该事件。 */
  handleKeydown(event: KeyboardEvent): boolean {
    if (!this.open) {
      return false;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      this.move(1);
      return true;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      this.move(-1);
      return true;
    }
    if (event.key === "Enter" && !event.isComposing) {
      event.preventDefault();
      this.pickActive();
      return true;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      this.hide();
      return true;
    }
    return false;
  }

  hide(): void {
    this.cancelPreviewHide();
    this.open = false;
    this.preview = false;
    this.menu.hidden = true;
    this.menu.replaceChildren();
  }

  /** / 后已输入的过滤文本（去掉可能的空格，只取命令词部分）。 */
  private filterText(): string {
    return this.input.value.slice(1).split(/\s/)[0].toLowerCase();
  }

  private show(filter: string): void {
    this.filtered = this.commands.filter((c) =>
      c.name.toLowerCase().startsWith(filter),
    );
    if (this.filtered.length === 0) {
      this.open = false;
      this.menu.hidden = true;
      this.menu.replaceChildren();
      return;
    }
    this.active = 0;
    this.open = true;
    this.menu.hidden = false;
    this.render();
  }

  private move(step: number): void {
    const n = this.filtered.length;
    this.active = (this.active + step + n) % n;
    this.render();
  }

  private pickActive(): void {
    const command = this.filtered[this.active];
    if (!command) {
      return;
    }
    this.input.value = `/${command.name}`;
    this.hide();
    this.onPick();
  }

  private render(): void {
    this.menu.replaceChildren();
    this.filtered.forEach((command, index) => {
      const row = document.createElement("div");
      row.className = "slash-menu-item";
      if (index === this.active) {
        row.classList.add("active");
      }
      const name = document.createElement("code");
      name.className = "slash-menu-name";
      name.textContent = `/${command.name}`;
      const desc = document.createElement("span");
      desc.className = "slash-menu-desc";
      desc.textContent = command.summary;
      row.append(name, desc);
      // mousedown 而非 click：避免 textarea 先 blur 导致菜单在点击前被关掉。
      row.addEventListener("mousedown", (event) => {
        event.preventDefault();
        this.active = index;
        this.pickActive();
      });
      this.menu.appendChild(row);
    });
  }
}

/** 运行模式菜单：本机 / 容器 / SSH 三组，SSH 展开后列出 ~/.ssh/config 中的 Host 别名。 */

// Docker 鲸鱼图标
const DOCKER_SVG =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" ' +
  'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M22 12s-2-2.5-5-2.5c-.5 0-1 .1-1.5.2C15 7.5 12.5 6 9 6c-4 0-7 3-7 7h20z"/>' +
  '<rect x="3" y="13" width="3" height="2" rx=".3"/><rect x="7" y="13" width="3" height="2" rx=".3"/>' +
  '<rect x="11" y="13" width="3" height="2" rx=".3"/><rect x="7" y="10" width="3" height="2" rx=".3"/>' +
  '<rect x="11" y="10" width="3" height="2" rx=".3"/><rect x="11" y="7" width="3" height="2" rx=".3"/>' +
  '<path d="M22 13c0 2-2 4-5 4H3"/></svg>';

// Podman 鼹鼠图标
const PODMAN_SVG =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" ' +
  'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M12 4C8 4 5 7 5 11c0 2 .8 3.8 2 5l-1 4h12l-1-4c1.2-1.2 2-3 2-5 0-4-3-7-7-7z"/>' +
  '<circle cx="9.5" cy="10" r="1"/><circle cx="14.5" cy="10" r="1"/>' +
  '<path d="M10 13c.5.5 1.5.5 2 0"/><path d="M8 4c-1-2 0-3 1-3"/><path d="M16 4c1-2 0-3-1-3"/></svg>';

// 各模式对应的菜单图标、标签
class ModeMenu {
  private open = false;
  private sshHosts: string[] = [];
  private availableBackends: SandboxMode[] = ["local", "ssh"];

  constructor(
    private readonly menu: HTMLElement,
    private readonly onSelect: (mode: SandboxMode, sshHost?: string) => void,
  ) { }

  setSshHosts(hosts: string[]): void {
    this.sshHosts = hosts;
    if (this.open) {
      this.render();
    }
  }

  setAvailableBackends(backends: SandboxMode[]): void {
    this.availableBackends = backends;
    if (this.open) {
      this.render();
    }
  }

  toggle(): void {
    if (this.open) {
      this.hide();
    } else {
      this.show();
    }
  }

  show(): void {
    this.open = true;
    this.menu.hidden = false;
    this.render();
  }

  hide(): void {
    this.open = false;
    this.menu.hidden = true;
    this.menu.replaceChildren();
  }

  isOpen(): boolean {
    return this.open;
  }

  private makeItem(label: string, iconHtml: string, handler: () => void): HTMLDivElement {
    const item = document.createElement("div");
    item.className = "mode-menu-item";
    item.innerHTML = iconHtml + `<span>${label}</span>`;
    item.addEventListener("mousedown", (event) => {
      event.preventDefault();
      handler();
      this.hide();
    });
    return item;
  }

  private render(): void {
    this.menu.replaceChildren();
    const available = this.availableBackends;

    // 本机（local 始终可用）
    const localHeader = document.createElement("div");
    localHeader.className = "mode-menu-header";
    localHeader.textContent = "本机";
    this.menu.appendChild(localHeader);

    const localItem = this.makeItem("Local", '<i class="codicon codicon-device-desktop"></i>', () => this.onSelect("local"));
    this.menu.appendChild(localItem);

    // 容器组（仅展示本地已安装 CLI 的选项）
    const containerModes = available.filter((m) => m === "docker" || m === "podman");
    if (containerModes.length > 0) {
      const containerSep = document.createElement("div");
      containerSep.className = "mode-menu-sep";
      this.menu.appendChild(containerSep);

      const containerHeader = document.createElement("div");
      containerHeader.className = "mode-menu-header";
      containerHeader.textContent = "容器";
      this.menu.appendChild(containerHeader);

      if (containerModes.includes("docker")) {
        const dockerItem = this.makeItem("Docker", `<span class="mode-menu-svg">${DOCKER_SVG}</span>`, () => this.onSelect("docker"));
        this.menu.appendChild(dockerItem);
      }
      if (containerModes.includes("podman")) {
        const podmanItem = this.makeItem("Podman", `<span class="mode-menu-svg">${PODMAN_SVG}</span>`, () => this.onSelect("podman"));
        this.menu.appendChild(podmanItem);
      }
    }

    // SSH 组
    if (available.includes("ssh")) {
      const sshSep = document.createElement("div");
      sshSep.className = "mode-menu-sep";
      this.menu.appendChild(sshSep);

      const sshHeader = document.createElement("div");
      sshHeader.className = "mode-menu-header";
      sshHeader.textContent = "SSH";
      this.menu.appendChild(sshHeader);

      if (this.sshHosts.length > 0) {
        for (const host of this.sshHosts) {
          const item = this.makeItem(host, '<i class="codicon codicon-remote"></i>', () => this.onSelect("ssh", host));
          this.menu.appendChild(item);
        }
      } else {
        const sshItem = this.makeItem("SSH", '<i class="codicon codicon-remote"></i>', () => this.onSelect("ssh"));
        this.menu.appendChild(sshItem);
      }
    }
  }
}

const app = document.getElementById("app");
if (app) {
  app.innerHTML = `
    <div id="log" class="chat-log"></div>
    <div id="composer" class="composer">
      <div id="slash-menu" class="slash-menu" hidden></div>
      <div id="mode-menu" class="mode-menu" hidden></div>
      <textarea id="prompt" rows="1"
        placeholder="输入消息，回车发送，Shift+Enter 换行" autofocus></textarea>
      <div class="composer-actions">
        <div class="composer-actions-start">
          <button id="slash" type="button" class="composer-btn" title="斜杠命令"
            aria-label="斜杠命令" aria-haspopup="true"></button>
          <button id="sandbox-mode" type="button" class="mode-switch"
            title="切换运行模式" aria-label="当前运行模式：Local"
            aria-haspopup="true">
            <i class="codicon codicon-device-desktop"></i>
            <span>LOCAL</span>
          </button>
          <button id="yolo" type="button" class="composer-btn yolo-btn"
            title="自动审批：关闭（点击开启 YOLO 模式）" aria-label="YOLO 模式">
          </button>
        </div>
        <div class="composer-actions-end">
          <span id="context-usage-mount"></span>
          <button id="send" type="button" class="composer-btn primary"
            title="发送" aria-label="发送">
            <i class="codicon codicon-arrow-up"></i>
          </button>
        </div>
      </div>
    </div>
  `;

  const input = document.getElementById("prompt") as HTMLTextAreaElement;
  const log = document.getElementById("log") as HTMLDivElement;
  const sendBtn = document.getElementById("send") as HTMLButtonElement;
  const slashBtn = document.getElementById("slash") as HTMLButtonElement;
  const modeBtn = document.getElementById("sandbox-mode") as HTMLButtonElement;
  const yoloBtn = document.getElementById("yolo") as HTMLButtonElement;
  const slashMenu = document.getElementById("slash-menu") as HTMLDivElement;
  const modeMenuEl = document.getElementById("mode-menu") as HTMLDivElement;
  const contextUsageMount = document.getElementById("context-usage-mount") as HTMLSpanElement;

  let sandboxMode: SandboxMode = "local";
  let currentSshHost = "";
  let yoloEnabled = false;
  let modeSwitching = false;
  let historyLoading = false;

  // 斜杠方框图标（与命令卡同款内联 SVG），放进斜杠按钮。
  slashBtn.innerHTML =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<rect x="3" y="3" width="18" height="18" rx="4"/>' +
    '<line x1="14.5" y1="7" x2="9.5" y2="17"/></svg>';

  // 盖章图标（内联 SVG），放进 YOLO 按钮。
  yoloBtn.innerHTML =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M6 20h12"/>' +
    '<path d="M8 16v4h8v-4"/>' +
    '<path d="M8 16h8"/>' +
    '<path d="M12 16V8"/>' +
    '<circle cx="12" cy="5" r="3"/>' +
    '<path d="M9 5h6"/></svg>';

  // 审批回调：把用户在工具卡片上的批准/拒绝转成入站命令发给宿主。
  const renderer = new ChatRenderer(log, (toolCallId, approved) => {
    if (approved) {
      vscodeApi.postMessage({ type: "permit", toolCallId });
    } else {
      vscodeApi.postMessage({ type: "deny", toolCallId });
    }
  });
  const contextUsageRing = new ContextUsageRing(contextUsageMount);

  const slashMenuController = new SlashMenu(slashMenu, input, () => send());

  const modeMenuController = new ModeMenu(modeMenuEl, (mode, sshHost) => {
    modeSwitching = true;
    syncSendState();
    vscodeApi.postMessage({ type: "setSandboxTarget", mode, sshHost });
    // 安全超时：若宿主 8 秒内未回 runtimeOptions，强制解除锁定。
    setTimeout(() => {
      if (modeSwitching) {
        modeSwitching = false;
        syncSendState();
        updateModeBtn();
      }
    }, 8000);
  });

  const syncSendState = () => {
    input.disabled = historyLoading;
    slashBtn.disabled = historyLoading;
    modeBtn.disabled = historyLoading || modeSwitching;
    yoloBtn.disabled = historyLoading || modeSwitching;
    sendBtn.disabled = historyLoading || input.value.trim().length === 0;
  };

  // 按内容自适应高度：先归零再取 scrollHeight，封顶后转内部滚动。
  const autoResize = () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, INPUT_MAX_HEIGHT_PX)}px`;
  };

  // 发送：本地先上屏 user 气泡（slash 命令除外，结果由后端 SlashResult 卡渲染），
  // 再把输入 postMessage 给宿主，复位输入框。
  const send = () => {
    const text = input.value.trim();
    if (!text) {
      return;
    }
    slashMenuController.hide();
    modeMenuController.hide();
    if (!text.startsWith("/")) {
      renderer.addUser(text);
    }
    vscodeApi.postMessage({ type: "userInput", text });
    input.value = "";
    autoResize();
    syncSendState();
    input.focus();
  };

  // 各模式对应的图标和标签
  const MODE_DISPLAY: Record<SandboxMode, { label: string; icon: string; desc: string }> = {
    local: { label: "LOCAL", icon: "codicon codicon-device-desktop", desc: "Local" },
    docker: { label: "DOCKER", icon: "codicon codicon-package", desc: "Docker" },
    podman: { label: "PODMAN", icon: "codicon codicon-package", desc: "Podman" },
    ssh: { label: "SSH", icon: "codicon codicon-remote", desc: "SSH" },
  };

  // 更新模式按钮的图标和文字。
  const updateModeBtn = () => {
    const label = modeBtn.querySelector("span");
    const icon = modeBtn.querySelector("i");
    const display = MODE_DISPLAY[sandboxMode];
    if (sandboxMode === "ssh" && currentSshHost) {
      if (label) { label.textContent = currentSshHost.toUpperCase(); }
      if (icon) { icon.className = display.icon; }
      modeBtn.title = modeSwitching ? "正在切换…" : `当前：SSH (${currentSshHost})`;
    } else {
      if (label) { label.textContent = display.label; }
      if (icon) { icon.className = display.icon; }
      modeBtn.title = modeSwitching ? "正在切换…" : `当前：${display.desc}`;
    }
    modeBtn.setAttribute("aria-label", modeBtn.title);
  };

  // 更新 YOLO 按钮状态。
  const updateYoloBtn = () => {
    yoloBtn.classList.toggle("active", yoloEnabled);
    yoloBtn.title = yoloEnabled
      ? "自动审批：开启（点击关闭 YOLO 模式）"
      : "自动审批：关闭（点击开启 YOLO 模式）";
    yoloBtn.setAttribute("aria-label", yoloEnabled ? "YOLO 已开启" : "YOLO 模式");
  };

  // 回车发送、Shift+Enter 换行；输入法组合（isComposing）中的回车不触发发送。
  // 斜杠菜单打开时，方向键/回车/Esc 先交给菜单处理（导航/选中/关闭）。
  input.addEventListener("keydown", (event) => {
    if (slashMenuController.handleKeydown(event)) {
      return;
    }
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      send();
    }
  });
  // 输入时更新自适应高度；行首以 / 开头则联动打开/过滤斜杠菜单。
  input.addEventListener("input", () => {
    autoResize();
    syncSendState();
    slashMenuController.syncFromInput();
  });
  sendBtn.addEventListener("click", send);
  // 斜杠按钮：切换菜单显隐；打开时若输入框为空补一个 / 便于继续输入过滤。
  slashBtn.addEventListener("click", () => {
    slashMenuController.toggleFromButton();
    autoResize();
    syncSendState();
  });
  slashBtn.addEventListener("mouseenter", () => {
    vscodeApi.postMessage({ type: "requestSlashCommands" });
    slashMenuController.previewFromButton();
  });
  slashBtn.addEventListener("mouseleave", () => {
    slashMenuController.schedulePreviewHide();
  });
  slashMenu.addEventListener("mouseenter", () => {
    slashMenuController.cancelPreviewHide();
  });
  slashMenu.addEventListener("mouseleave", () => {
    slashMenuController.schedulePreviewHide();
  });

  // 模式按钮：点击弹出二级菜单。
  modeBtn.addEventListener("click", () => {
    if (modeMenuController.isOpen()) {
      modeMenuController.hide();
    } else {
      vscodeApi.postMessage({ type: "requestRuntimeOptions" });
      modeMenuController.show();
    }
  });

  // YOLO 按钮：切换自动审批。
  yoloBtn.addEventListener("click", () => {
    yoloEnabled = !yoloEnabled;
    updateYoloBtn();
    modeSwitching = true;
    syncSendState();
    vscodeApi.postMessage({ type: "setYoloMode", enabled: yoloEnabled });
    setTimeout(() => {
      if (modeSwitching) {
        modeSwitching = false;
        syncSendState();
      }
    }, 8000);
  });

  // 点击页面空白处收起模式菜单。
  document.addEventListener("mousedown", (event) => {
    if (!modeMenuController.isOpen()) {
      return;
    }
    const target = event.target as Node;
    if (modeMenuEl.contains(target) || modeBtn.contains(target)) {
      return;
    }
    modeMenuController.hide();
  });

  // 监听宿主回推的消息：事件交给渲染器，命令清单交给斜杠菜单，主题写 <body>。
  window.addEventListener("message", (event: MessageEvent<HostToView>) => {
    const message = event.data;
    if (message.type === "event") {
      const wireEvent = { method: message.method, params: message.params };
      contextUsageRing.handleWireEvent(wireEvent);
      renderer.handleEvent(wireEvent);
      return;
    }
    if (message.type === "slashCommands") {
      slashMenuController.setCommands(message.commands);
      return;
    }
    if (message.type === "runtimeOptions") {
      sandboxMode = message.mode;
      currentSshHost = message.sshHost ?? "";
      modeSwitching = message.switching === true;
      yoloEnabled = message.yolo;
      modeMenuController.setSshHosts(message.sshHosts);
      modeMenuController.setAvailableBackends(message.availableBackends);
      updateModeBtn();
      updateYoloBtn();
      syncSendState();
      return;
    }
    if (message.type === "historyLoading") {
      historyLoading = message.loading;
      log.setAttribute("aria-busy", String(historyLoading));
      if (historyLoading) {
        slashMenuController.hide();
        renderer.showHistorySkeleton();
      } else if (message.failed) {
        renderer.clear();
      }
      syncSendState();
      return;
    }
    if (message.type === "theme") {
      document.body.dataset.theme = message.kind;
      return;
    }
  });

  vscodeApi.postMessage({ type: "requestRuntimeOptions" });
  vscodeApi.postMessage({ type: "requestHistoryReplay" });
  syncSendState();
}
