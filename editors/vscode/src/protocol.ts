// 宿主 ↔ 视图 消息协议。
//
// 宿主层和视图层跑在两个隔离环境，之间只能通过 postMessage 传可结构化克隆的对象。
// 这里集中定义两个方向的消息形状，两侧都 import，保证收发端字段一致、改一处即全改。

/** 视图 → 宿主：用户在视图里的操作。 */
export type ViewToHost =
  // 发送一条用户消息（以 / 开头的由后端识别为 slash 命令，不跑 Agent）。
  | { type: "userInput"; text: string }
  // 选择本机或 SSH Host；宿主持久化设置并重启后端。
  | { type: "setSandboxTarget"; mode: SandboxMode; sshHost?: string }
  // 开关 YOLO 自动审批；宿主持久化设置并重启后端。
  | { type: "setYoloMode"; enabled: boolean }
  // Webview 就绪或菜单打开前请求最新运行选项。
  | { type: "requestRuntimeOptions" }
  // 请求后端当前支持的 slash 命令；hover 菜单打开前按需同步。
  | { type: "requestSlashCommands" }
  // 批准一次挂起的工具调用（危险工具在执行前弹审批）。
  | { type: "permit"; toolCallId: string }
  // 拒绝一次挂起的工具调用；reason 会作为 tool result 回给模型。
  | { type: "deny"; toolCallId: string; reason?: string };

/** 一条 slash 命令的元信息（后端下发，前端填充斜杠菜单）。 */
export type SlashCommand = { name: string; summary: string };

/** 宿主 → 视图：宿主推给视图要渲染的内容。 */
export type HostToView =
  // 一条 Wire 事件（method 是事件类名，params 是其字段）。
  | { type: "event"; method: string; params: Record<string, unknown> }
  // 可用 slash 命令清单（后端启动时下发），供视图构建斜杠菜单。
  | { type: "slashCommands"; commands: SlashCommand[] }
  // 当前运行选项，驱动 sandbox 二级菜单和 YOLO 按钮。
  | {
    type: "runtimeOptions";
    mode: SandboxMode;
    sshHost?: string;
    sshHosts: string[];
    yolo: boolean;
    switching?: boolean;
    availableBackends: SandboxMode[];
  }
  // 会话历史加载状态；视图据此显示骨架并锁定输入。
  | { type: "historyLoading"; loading: boolean; failed?: boolean }
  // 纯诊断日志（如子进程退出、启动信息），视图可选择性展示。
  | { type: "log"; text: string }
  // 当前主题类别（亮/暗/高对比度），用于 CSS 变量覆盖不到的细节调整。
  | { type: "theme"; kind: ThemeKind };

/** VS Code 主题的粗分类，对应 vscode.ColorThemeKind。 */
export type ThemeKind = "light" | "dark" | "high-contrast";

export type SandboxMode = "local" | "docker" | "podman" | "ssh";
