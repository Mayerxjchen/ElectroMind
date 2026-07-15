// 宿主层 —— 侧边栏 Webview 视图提供者（第 4 课）。
//
// WebviewViewProvider 是 VS Code 托管“视图容器里的 webview”的标准接口。
// VS Code 在用户首次展开该视图时调用 resolveWebviewView，把一个 WebviewView
// 交给我们填充 HTML。视图被折叠再展开时，VS Code 可能销毁并重建，所以不要在
// 这里持有一次性的长生命周期状态。
//
// 第 4 课：用户输入 → spawn `pagent --wire` 子进程 → 事件行/stderr 打进输出通道。

import * as vscode from "vscode";
import { execSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { resolve } from "node:path";

import type {
  HostToView,
  SandboxMode,
  SlashCommand,
  ThemeKind,
  ViewToHost,
} from "../protocol";
import { AgentBridge } from "./agent";
import { parseWireLine } from "./wire";

export class ChatViewProvider implements vscode.WebviewViewProvider {
  // 与 package.json 里 contributes.views 的视图 id 保持一致。
  public static readonly viewId = "pagent.chat";

  // 所有已挂载的 webview（侧栏视图 + 编辑器区面板）；事件广播到全部，保持两侧同步。
  private readonly webviews = new Set<vscode.Webview>();

  // pagent 子进程桥；首次发送时惰性创建，侧栏与编辑器面板共用一个。
  private bridge: AgentBridge | undefined;

  // 主题变化监听器；只挂一次，变化时广播给所有 webview。
  private themeSub: vscode.Disposable | undefined;

  // 编辑器区聊天面板（可停靠右侧、更宽）；单例，重复调用聚焦已有面板。
  private editorPanel: vscode.WebviewPanel | undefined;

  private historyLoadTimer: ReturnType<typeof setTimeout> | undefined;

  // extensionUri 用来把打包产物（dist/webview.js）转成 webview 能加载的受限 URI。
  // output 是“输出”面板里的一个通道，宿主侧日志打到这里，方便开发期观察。
  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly output: vscode.OutputChannel,
  ) { }

  /**
   * VS Code 在侧栏视图需要显示时调用一次，交给我们填充内容并接线消息通道。
   *
   * @param view 待填充的视图。view.webview 是真正的 webview 实例。
   */
  resolveWebviewView(view: vscode.WebviewView): void {
    this.attachWebview(view.webview);
    // 视图被销毁时（用户切走、窗口关闭）解绑；所有 webview 都没了才停子进程。
    view.onDidDispose(() => this.detachWebview(view.webview));
  }

  /** 命令「在编辑器区打开」：用 WebviewPanel 在编辑器区开一个更宽、可拖到右侧的聊天面板。
   *  侧栏视图受工作台约束无法设默认宽度或强制放右侧，编辑器面板可由用户自由停靠。
   *  单例：已存在则聚焦；与侧栏共用同一子进程桥，事件广播到两侧。 */
  openInEditor(): void {
    if (this.editorPanel) {
      this.editorPanel.reveal(vscode.ViewColumn.Beside);
      return;
    }
    // ViewColumn.Beside 在当前编辑器旁边开一列；用户可再拖到右侧编辑器组。
    // retainContextWhenHidden 让面板隐藏时保留 DOM，切回不丢已渲染的对话。
    const panel = vscode.window.createWebviewPanel(
      "pagent.chatEditor",
      "pagent 聊天",
      vscode.ViewColumn.Beside,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: this.localRoots(),
      },
    );
    this.editorPanel = panel;
    this.attachWebview(panel.webview);
    panel.onDidDispose(() => {
      this.detachWebview(panel.webview);
      this.editorPanel = undefined;
    });
  }

  /** webview 只能加载 dist/ 和 media/ 下的本地资源，收敛攻击面。 */
  private localRoots(): vscode.Uri[] {
    return [
      vscode.Uri.joinPath(this.extensionUri, "dist"),
      vscode.Uri.joinPath(this.extensionUri, "media"),
    ];
  }

  /** 挂载一个 webview（侧栏或编辑器面板）：填 HTML、接线消息、纳入广播集合、推主题。
   *  若子进程已在跑，补请一次 slash 清单（新面板错过了启动时的下发）。 */
  private attachWebview(webview: vscode.Webview): void {
    // enableScripts 默认关闭；聊天视图要跑 JS，必须显式打开。
    webview.options = {
      enableScripts: true,
      localResourceRoots: this.localRoots(),
    };
    webview.html = this.renderHtml(webview);
    // onDidReceiveMessage 收视图 postMessage 上来的消息。
    webview.onDidReceiveMessage((message: ViewToHost) => {
      this.handleMessage(message);
    });
    this.webviews.add(webview);

    // 主题同步：--vscode-* CSS 变量已随主题自动切换；这里额外把主题类别推给视图，
    // 供 CSS 变量覆盖不到的细节使用。
    void webview.postMessage({
      type: "theme",
      kind: themeKind(vscode.window.activeColorTheme),
    } satisfies HostToView);
    void this.postRuntimeOptions(webview);
    this.ensureThemeSub();
    this.bridge?.send({ cmd: "commands" });
  }

  /** 解绑一个 webview；集合空了才停子进程与主题监听，避免僵尸进程/泄漏。 */
  private detachWebview(webview: vscode.Webview): void {
    this.webviews.delete(webview);
    if (this.webviews.size > 0) {
      return;
    }
    this.disposeBridge();
    if (this.historyLoadTimer) {
      clearTimeout(this.historyLoadTimer);
      this.historyLoadTimer = undefined;
    }
    this.themeSub?.dispose();
    this.themeSub = undefined;
  }

  /** 主题变化监听只挂一次，变化时广播给所有 webview。 */
  private ensureThemeSub(): void {
    if (this.themeSub) {
      return;
    }
    // onDidChangeActiveColorTheme 在用户换主题时触发。
    this.themeSub = vscode.window.onDidChangeActiveColorTheme((theme) => {
      this.postTheme(theme);
    });
  }

  /** 处理视图发来的消息。第 6 课把用户输入转发给子进程；视图自己已上屏 user 气泡。 */
  private handleMessage(message: ViewToHost): void {
    if (message.type === "userInput") {
      this.ensureBridge().send({ cmd: "user", text: message.text });
      return;
    }
    if (message.type === "requestSlashCommands") {
      this.ensureBridge().send({ cmd: "commands" });
      return;
    }
    if (message.type === "setSandboxTarget") {
      void this.setSandboxTarget(message.mode, message.sshHost);
      return;
    }
    if (message.type === "setYoloMode") {
      void this.setYoloMode(message.enabled);
      return;
    }
    if (message.type === "requestRuntimeOptions") {
      void this.postRuntimeOptions();
      return;
    }
    // 审批：危险工具挂起时，用户点“批准/拒绝”把决定送回后端解开阻塞。
    // 无子进程时忽略（不会有挂起的审批）。
    if (message.type === "permit") {
      this.bridge?.send({ cmd: "permit", tool_call_id: message.toolCallId });
      return;
    }
    if (message.type === "deny") {
      this.bridge?.send({
        cmd: "deny",
        tool_call_id: message.toolCallId,
        reason: message.reason ?? "",
      });
      return;
    }
  }

  /** 标题栏「新会话」：让后端结束当前会话、开干净 thread。
   *  后端回发 HistoryReplay（空数组）驱动视图清屏，视图 DOM 统一由该事件重建。 */
  resetSession(): void {
    // 未起子进程时无需 reset；起了才发命令。
    this.bridge?.send({ cmd: "reset" });
  }

  /** 标题栏「恢复会话」：列出工作区已有 thread 供选择，选中后让后端切换并回放历史。
   *  列表用 metainfo.json 里的 title 面向用户展示，thread id（内部编号）降级为副标题。 */
  async resumeSession(): Promise<void> {
    const cwd = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!cwd) {
      void vscode.window.showWarningMessage("pagent：未打开工作区，无法列出会话。");
      return;
    }
    const threads = await this.listThreads(cwd);
    if (threads.length === 0) {
      void vscode.window.showInformationMessage("pagent：还没有可恢复的会话。");
      return;
    }
    // QuickPickItem：label 显示面向用户的标题，description 显示内部 thread id 供区分。
    const items = threads.map((thread) => ({
      label: thread.title || thread.id,
      description: thread.id,
    }));
    const picked = await vscode.window.showQuickPick(items, {
      placeHolder: "选择要恢复的会话",
    });
    if (!picked) {
      return;
    }
    // 未起子进程时先起（resume 也需要一个后端进程来加载 thread）。
    this.startHistoryLoading();
    this.ensureBridge().send({ cmd: "resume", thread_id: picked.description });
  }

  /** 读工作区 .pagent/threads/ 下的 thread：目录名当 id，metainfo.json 的 title 当展示名。
   *  缺目录返回空；缺 metainfo 或读失败则 title 留空，由调用方降级用 id。
   *  thread id 已含时间戳，倒序让更近的排前面。 */
  private async listThreads(cwd: string): Promise<{ id: string; title: string }[]> {
    // vscode.workspace.fs 是跨平台的虚拟文件系统 API，比 node:fs 更适合插件里读工作区。
    const root = vscode.Uri.joinPath(vscode.Uri.file(cwd), ".pagent", "threads");
    let entries: [string, vscode.FileType][];
    try {
      entries = await vscode.workspace.fs.readDirectory(root);
    } catch {
      return []; // 目录不存在（还没建过 thread）。
    }
    const ids = entries
      .filter(([, kind]) => kind === vscode.FileType.Directory)
      .map(([name]) => name)
      .sort()
      .reverse();
    const threads: { id: string; title: string }[] = [];
    for (const id of ids) {
      const title = await this.readThreadTitle(root, id);
      threads.push({ id, title });
    }
    return threads;
  }

  /** 读单个 thread 的 metainfo.json 取 title；文件缺失/解析失败则返回空串。 */
  private async readThreadTitle(root: vscode.Uri, id: string): Promise<string> {
    const metaUri = vscode.Uri.joinPath(root, id, "metainfo.json");
    try {
      const bytes = await vscode.workspace.fs.readFile(metaUri);
      const meta = JSON.parse(new TextDecoder().decode(bytes)) as { title?: string };
      return typeof meta.title === "string" ? meta.title : "";
    } catch {
      return "";
    }
  }

  /** 惰性创建子进程桥；把事件行与 stderr 打进输出通道。 */
  private ensureBridge(): AgentBridge {
    if (this.bridge) {
      return this.bridge;
    }
    // getConfiguration 读用户设置（package.json 的 contributes.configuration）。
    const config = vscode.workspace.getConfiguration("pagent");
    const command = config.get<string>("command", "uv");
    const configuredArgs = config.get<string[]>("args", ["run", "pagent", "--wire"]);
    const args = withRuntimeArgs(configuredArgs, {
      mode: this.sandboxMode(),
      sshHost: this.sshHost(),
      sshConfig: this.sshConfigPath(),
      yolo: this.yoloMode(),
    });
    // workspaceFolders[0] 是当前打开的第一个工作区根目录，作为子进程 cwd。
    const cwd = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;

    this.bridge = new AgentBridge({
      command,
      args,
      cwd,
      onLine: (line) => this.onEventLine(line),
      onStderr: (text) => this.output.append(text),
      onExit: (code) => {
        this.output.appendLine(`[wire] 子进程退出 code=${code}`);
        this.bridge = undefined;
        this.finishHistoryLoading(true);
        // 子进程退出后同步前端状态，确保 modeSwitching/yolo 被重置。
        void this.postRuntimeOptions();
      },
    });
    this.bridge.start();
    this.output.appendLine(`[wire] 启动 ${command} ${args.join(" ")}`);
    return this.bridge;
  }

  private sandboxMode(): SandboxMode {
    return vscode.workspace
      .getConfiguration("pagent")
      .get<SandboxMode>("sandboxMode", "local");
  }

  private sshHost(): string {
    return vscode.workspace.getConfiguration("pagent").get<string>("sshHost", "");
  }

  private sshConfigPath(): string {
    return vscode.workspace
      .getConfiguration("pagent")
      .get<string>("sshConfigPath", "~/.ssh/config");
  }

  private yoloMode(): boolean {
    return vscode.workspace.getConfiguration("pagent").get<boolean>("yoloMode", false);
  }

  /** 保存 sandbox 目标并重启 Wire 后端。 */
  private async setSandboxTarget(mode: SandboxMode, sshHost?: string): Promise<void> {
    const previous = this.sandboxMode();
    if (mode === previous && (mode !== "ssh" || sshHost === this.sshHost())) {
      // 模式未变，仍需重置前端 modeSwitching 状态。
      await this.postRuntimeOptions();
      return;
    }
    await this.postRuntimeOptions(undefined, true, { mode, sshHost });
    try {
      const config = vscode.workspace.getConfiguration("pagent");
      await config.update("sandboxMode", mode, vscode.ConfigurationTarget.Workspace);
      if (mode === "ssh" && sshHost) {
        await config.update("sshHost", sshHost, vscode.ConfigurationTarget.Workspace);
      }
      this.disposeBridge();
      this.ensureBridge();
      this.postToView({
        type: "event",
        method: "HistoryReplay",
        params: { messages: [] },
      });
      await this.postRuntimeOptions();
      this.output.appendLine(`[sandbox] 已切换到 ${mode}${sshHost ? `:${sshHost}` : ""}`);
    } catch (error) {
      await this.postRuntimeOptions();
      const detail = error instanceof Error ? error.message : String(error);
      void vscode.window.showErrorMessage(`pagent 模式切换失败：${detail}`);
    }
  }

  /** YOLO 改变审批 hook 装配，持久化后重启后端生效。 */
  private async setYoloMode(enabled: boolean): Promise<void> {
    await this.postRuntimeOptions(undefined, true, { yolo: enabled });
    await vscode.workspace
      .getConfiguration("pagent")
      .update("yoloMode", enabled, vscode.ConfigurationTarget.Workspace);
    this.disposeBridge();
    this.ensureBridge();
    await this.postRuntimeOptions();
    this.output.appendLine(`[permission] YOLO ${enabled ? "on" : "off"}`);
  }

  private disposeBridge(): void {
    this.bridge?.stop();
    this.bridge = undefined;
  }

  /** 插件停用时由 extension.ts 调用，确保子进程和定时器被回收。 */
  dispose(): void {
    this.disposeBridge();
    if (this.historyLoadTimer) {
      clearTimeout(this.historyLoadTimer);
      this.historyLoadTimer = undefined;
    }
    this.themeSub?.dispose();
    this.themeSub = undefined;
    this.editorPanel?.dispose();
    this.editorPanel = undefined;
  }

  /** 解析一行 Wire 事件；合法则转发给视图渲染，非法则记日志待排查。 */
  private onEventLine(line: string): void {
    const event = parseWireLine(line);
    if (event === null) {
      this.output.appendLine(`[event?] ${line}`);
      return;
    }
    this.output.appendLine(
      `[event] ${event.method} ${JSON.stringify(event.params)}`,
    );
    // SlashCommands 是后端下发的命令清单，转成 typed 消息供视图构建斜杠菜单，
    // 不进入事件渲染流（它不是对话内容）。其余事件（含 SlashResult）原样透传。
    if (event.method === "SlashCommands") {
      const commands = Array.isArray(event.params.commands)
        ? (event.params.commands as SlashCommand[])
        : [];
      this.postToView({ type: "slashCommands", commands });
      return;
    }
    this.postToView({
      type: "event",
      method: event.method,
      params: event.params,
    });
    if (event.method === "HistoryReplay") {
      this.finishHistoryLoading(false);
    }
  }

  private startHistoryLoading(): void {
    if (this.historyLoadTimer) {
      clearTimeout(this.historyLoadTimer);
    }
    this.postToView({ type: "historyLoading", loading: true });
    this.historyLoadTimer = setTimeout(() => {
      this.historyLoadTimer = undefined;
      this.postToView({ type: "historyLoading", loading: false, failed: true });
      void vscode.window.showWarningMessage("pagent：会话加载超时，请重试。");
    }, 15_000);
  }

  private finishHistoryLoading(failed: boolean): void {
    if (!this.historyLoadTimer) {
      return;
    }
    clearTimeout(this.historyLoadTimer);
    this.historyLoadTimer = undefined;
    this.postToView({ type: "historyLoading", loading: false, failed });
  }

  /** 宿主 → 所有已挂载 webview 广播消息，保持侧栏与编辑器面板同步。 */
  private postToView(message: HostToView): void {
    for (const webview of this.webviews) {
      void webview.postMessage(message);
    }
  }

  /** 把当前主题类别推给视图。 */
  private postTheme(theme: vscode.ColorTheme): void {
    this.postToView({ type: "theme", kind: themeKind(theme) });
  }

  /** 推送当前运行选项（sandbox 模式、SSH host 列表、YOLO 状态）给视图。
   *  可指定单个 webview（如首次挂载）或广播；overrides 用于切换中的预览态。 */
  private async postRuntimeOptions(
    target?: vscode.Webview,
    switching?: boolean,
    overrides?: { mode?: SandboxMode; sshHost?: string; yolo?: boolean },
  ): Promise<void> {
    const mode = overrides?.mode ?? this.sandboxMode();
    const sshHost = overrides?.sshHost ?? this.sshHost();
    const yolo = overrides?.yolo ?? this.yoloMode();
    const sshHosts = mode === "ssh" ? await readSshHosts(this.sshConfigPath()) : [];
    const availableBackends = detectAvailableBackends();
    const msg: HostToView = {
      type: "runtimeOptions",
      mode,
      sshHost,
      sshHosts,
      yolo,
      switching,
      availableBackends,
    };
    if (target) {
      void target.postMessage(msg);
    } else {
      this.postToView(msg);
    }
  }

  /** 生成视图 HTML。 */
  private renderHtml(webview: vscode.Webview): string {
    // asWebviewUri 把磁盘路径转成 webview 可用的 vscode-webview:// URI。
    const scriptUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "dist", "webview.js"),
    );
    const styleUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "media", "style.css"),
    );
    // Codicons：VS Code 官方图标字体，由 esbuild 拷进 dist（css + ttf 同目录）。
    const codiconUri = webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "dist", "codicon.css"),
    );

    // nonce 配合 CSP：只允许带此 nonce 的 <script> 执行，挡掉注入脚本。
    const nonce = makeNonce();

    // CSP 收紧 webview：默认禁止一切；样式与字体只放行本 webview 源（webview.cspSource），
    // 脚本只放行带本 nonce 的 <script>。font-src 供 codicon.ttf 加载。
    return `<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy"
    content="default-src 'none'; style-src ${webview.cspSource}; font-src ${webview.cspSource}; script-src 'nonce-${nonce}';" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <link rel="stylesheet" href="${codiconUri}" />
  <link rel="stylesheet" href="${styleUri}" />
</head>
<body>
  <div id="app"></div>
  <script nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
  }
}

/** 生成 CSP 用的一次性随机串。 */
function makeNonce(): string {
  const chars =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  let text = "";
  for (let i = 0; i < 32; i++) {
    text += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return text;
}

/** 把 vscode.ColorThemeKind 收敛成协议里的三类。 */
function themeKind(theme: vscode.ColorTheme): ThemeKind {
  if (theme.kind === vscode.ColorThemeKind.Light) {
    return "light";
  }
  if (
    theme.kind === vscode.ColorThemeKind.HighContrast ||
    theme.kind === vscode.ColorThemeKind.HighContrastLight
  ) {
    return "high-contrast";
  }
  return "dark";
}

/** 运行时参数覆盖：移除旧值后追加当前界面选择的 backend / ssh / permission-mode。 */
function withRuntimeArgs(
  args: string[],
  opts: { mode: SandboxMode; sshHost: string; sshConfig: string; yolo: boolean },
): string[] {
  // 需要移除再重写的参数名（带值型：--key value 或 --key=value）。
  const stripKeys = new Set([
    "--backend", "--ssh-host", "--ssh-config", "--permission-mode", "--auto",
  ]);
  const next: string[] = [];
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    // 检查 --key=value 形式。
    const eqKey = arg.includes("=") ? arg.slice(0, arg.indexOf("=")) : "";
    if (stripKeys.has(arg)) {
      index += 1; // 跳过值。
      continue;
    }
    if (eqKey && stripKeys.has(eqKey)) {
      continue;
    }
    next.push(arg);
  }
  next.push("--backend", opts.mode);
  if (opts.mode === "ssh" && opts.sshHost) {
    next.push("--ssh-host", opts.sshHost);
  }
  if (opts.sshConfig && opts.sshConfig !== "~/.ssh/config") {
    next.push("--ssh-config", opts.sshConfig);
  }
  if (opts.yolo) {
    next.push("--permission-mode", "auto");
  }
  return next;
}

/** 探测本机可用的容器 CLI，返回可展示的后端模式列表。local 始终可用。 */
function detectAvailableBackends(): SandboxMode[] {
  const backends: SandboxMode[] = ["local"];
  for (const cli of ["docker", "podman"] as const) {
    try {
      execSync(`which ${cli}`, { stdio: "pipe" });
      backends.push(cli);
    } catch {
      // CLI 不存在，不加入列表。
    }
  }
  // SSH 不依赖本地 CLI，只要 ~/.ssh/config 有 Host 条目就算可用，
  // 但这里统一加入，前端菜单在 SSH 组内按 sshHosts 是否为空来决定展示。
  backends.push("ssh");
  return backends;
}

/** 从 ~/.ssh/config 解析出显式 Host 别名（过滤掉通配 * 和 ? 的模式块）。 */
async function readSshHosts(configPath: string): Promise<string[]> {
  const expanded = configPath.replace(/^~/, homedir());
  try {
    const text = await readFile(resolve(expanded), "utf-8");
    const hosts: string[] = [];
    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) {
        continue;
      }
      const lower = trimmed.toLowerCase();
      if (!lower.startsWith("host ")) {
        continue;
      }
      const tokens = trimmed.slice(5).trim().split(/\s+/);
      for (const token of tokens) {
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
