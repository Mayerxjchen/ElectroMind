import {
  Activity,
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
  FolderTree,
  Globe,
  HardDrive,
  History,
  Layers,
  Minus,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Pin,
  PinOff,
  Plus,
  Server,
  X,
  createElement,
  type IconNode,
} from "lucide";

type DesktopIconName =
  | "activity"
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
  | "folder-tree"
  | "globe"
  | "hard-drive"
  | "history"
  | "layers"
  | "minus"
  | "moon"
  | "panel-left-close"
  | "panel-left-open"
  | "panel-right-close"
  | "panel-right-open"
  | "pin"
  | "pin-off"
  | "plus"
  | "server"
  | "x";

const iconRegistry: Record<DesktopIconName, IconNode> = {
  activity: Activity,
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
  "folder-tree": FolderTree,
  globe: Globe,
  "hard-drive": HardDrive,
  history: History,
  layers: Layers,
  minus: Minus,
  moon: Moon,
  "panel-left-close": PanelLeftClose,
  "panel-left-open": PanelLeftOpen,
  "panel-right-close": PanelRightClose,
  "panel-right-open": PanelRightOpen,
  pin: Pin,
  "pin-off": PinOff,
  plus: Plus,
  server: Server,
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
