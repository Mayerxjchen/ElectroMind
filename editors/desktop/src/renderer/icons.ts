import {
  Activity,
  ArrowLeft,
  ArrowUp,
  Box,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CodeXml,
  Container,
  Cpu,
  Database,
  File,
  FileJson,
  FileText,
  Folder,
  FolderOpen,
  FolderTree,
  Globe,
  HardDrive,
  History,
  Keyboard,
  LoaderCircle,
  Minus,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Pause,
  Pin,
  PinOff,
  Plug,
  Plus,
  RefreshCw,
  Server,
  Settings,
  Sparkles,
  Square,
  Terminal,
  Trash2,
  Wrench,
  X,
  Zap,
  createElement,
  type IconNode,
} from "lucide";

type DesktopIconName =
  | "activity"
  | "arrow-left"
  | "arrow-up"
  | "box"
  | "check"
  | "chevron-down"
  | "chevron-right"
  | "circle-alert"
  | "code-xml"
  | "container"
  | "cpu"
  | "database"
  | "file"
  | "file-json"
  | "file-text"
  | "folder"
  | "folder-open"
  | "folder-tree"
  | "globe"
  | "hard-drive"
  | "history"
  | "keyboard"
  | "loader-circle"
  | "minus"
  | "moon"
  | "pause"
  | "panel-left-close"
  | "panel-left-open"
  | "panel-right-close"
  | "panel-right-open"
  | "pin"
  | "pin-off"
  | "plug"
  | "plus"
  | "refresh-cw"
  | "server"
  | "settings"
  | "sparkles"
  | "square"
  | "terminal"
  | "trash-2"
  | "wrench"
  | "x"
  | "zap";

const iconRegistry: Record<DesktopIconName, IconNode> = {
  activity: Activity,
  "arrow-left": ArrowLeft,
  "arrow-up": ArrowUp,
  box: Box,
  check: Check,
  "chevron-down": ChevronDown,
  "chevron-right": ChevronRight,
  "circle-alert": CircleAlert,
  "code-xml": CodeXml,
  container: Container,
  cpu: Cpu,
  database: Database,
  file: File,
  "file-json": FileJson,
  "file-text": FileText,
  folder: Folder,
  "folder-open": FolderOpen,
  "folder-tree": FolderTree,
  globe: Globe,
  "hard-drive": HardDrive,
  history: History,
  keyboard: Keyboard,
  "loader-circle": LoaderCircle,
  minus: Minus,
  pause: Pause,
  moon: Moon,
  "panel-left-close": PanelLeftClose,
  "panel-left-open": PanelLeftOpen,
  "panel-right-close": PanelRightClose,
  "panel-right-open": PanelRightOpen,
  pin: Pin,
  "pin-off": PinOff,
  plug: Plug,
  plus: Plus,
  "refresh-cw": RefreshCw,
  server: Server,
  settings: Settings,
  sparkles: Sparkles,
  square: Square,
  terminal: Terminal,
  "trash-2": Trash2,
  wrench: Wrench,
  x: X,
  zap: Zap,
};

export function renderIcon(
  name: DesktopIconName,
  className = "desktop-icon",
): string {
  const iconNode = iconRegistry[name];
  const element = createElement(iconNode, {
    width: 16,
    height: 16,
    class: className,
    "stroke-width": 1.8,
  });
  return element.outerHTML;
}

/** 微信品牌双气泡图标（非 lucide）。 */
export function renderWechatIcon(className = "desktop-icon"): string {
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" ` +
    `viewBox="0 0 16 16" fill="currentColor" class="${className}" aria-hidden="true">` +
    `<path d="M11.176 14.429c-2.665 0-4.826-1.8-4.826-4.018 0-2.22 2.159-4.02 4.824-4.02S16 8.191 16 10.411c0 1.21-.65 2.301-1.666 3.036a.32.32 0 0 0-.12.366l.218.81a.6.6 0 0 1 .029.117.166.166 0 0 1-.162.162.2.2 0 0 1-.092-.03l-1.057-.61a.5.5 0 0 0-.256-.074.5.5 0 0 0-.142.021 5.7 5.7 0 0 1-1.576.22M9.064 9.542a.647.647 0 1 0 .557-1 .645.645 0 0 0-.646.647.6.6 0 0 0 .09.353Zm3.232.001a.646.646 0 1 0 .546-1 .645.645 0 0 0-.644.644.63.63 0 0 0 .098.356"/>` +
    `<path d="M0 6.826c0 1.455.781 2.765 2.001 3.656a.385.385 0 0 1 .143.439l-.161.6-.1.373a.5.5 0 0 0-.032.14.19.19 0 0 0 .193.193q.06 0 .111-.029l1.268-.733a.6.6 0 0 1 .308-.088q.088 0 .171.025a6.8 6.8 0 0 0 1.625.26 4.5 4.5 0 0 1-.177-1.251c0-2.936 2.785-5.02 5.824-5.02l.15.002C10.587 3.429 8.392 2 5.796 2 2.596 2 0 4.16 0 6.826m4.632-1.555a.77.77 0 1 1-1.54 0 .77.77 0 0 1 1.54 0m3.875 0a.77.77 0 1 1-1.54 0 .77.77 0 0 1 1.54 0"/>` +
    `</svg>`
  );
}

export type { DesktopIconName };
