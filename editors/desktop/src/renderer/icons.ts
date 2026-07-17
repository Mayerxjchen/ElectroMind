import {
  Activity,
  ArrowLeft,
  ArrowUp,
  Box,
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
  Pin,
  PinOff,
  Plug,
  Plus,
  Server,
  Settings,
  Wrench,
  X,
  createElement,
  type IconNode,
} from "lucide";

type DesktopIconName =
  | "activity"
  | "arrow-left"
  | "arrow-up"
  | "box"
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
  | "panel-left-close"
  | "panel-left-open"
  | "panel-right-close"
  | "panel-right-open"
  | "pin"
  | "pin-off"
  | "plug"
  | "plus"
  | "server"
  | "settings"
  | "wrench"
  | "x";

const iconRegistry: Record<DesktopIconName, IconNode> = {
  activity: Activity,
  "arrow-left": ArrowLeft,
  "arrow-up": ArrowUp,
  box: Box,
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
  moon: Moon,
  "panel-left-close": PanelLeftClose,
  "panel-left-open": PanelLeftOpen,
  "panel-right-close": PanelRightClose,
  "panel-right-open": PanelRightOpen,
  pin: Pin,
  "pin-off": PinOff,
  plug: Plug,
  plus: Plus,
  server: Server,
  settings: Settings,
  wrench: Wrench,
  x: X,
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

export type { DesktopIconName };
