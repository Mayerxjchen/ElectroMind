import {
  CircleCheck,
  Info,
  OctagonX,
  TriangleAlert,
  X,
  createElement,
  type IconNode,
} from "lucide";

export type ToastType = "default" | "success" | "info" | "warning" | "error";

export type ToastOptions = {
  description?: string;
  duration?: number;
  type?: ToastType;
};

type ToastRecord = {
  id: string;
  title: string;
  description?: string;
  type: ToastType;
  duration: number;
  element: HTMLElement;
  timer: number;
};

const MAX_VISIBLE = 3;
const DEFAULT_DURATION = 4000;
const TOAST_WIDTH = 280;
const GAP = 10;

const TYPE_ICONS: Record<Exclude<ToastType, "default">, IconNode> = {
  success: CircleCheck,
  info: Info,
  warning: TriangleAlert,
  error: OctagonX,
};

let host: HTMLElement | undefined;
const toasts: ToastRecord[] = [];
let seq = 0;
let expanded = false;

function themeName(): "light" | "dark" {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function iconHtml(node: IconNode, className: string): string {
  return createElement(node, {
    width: 14,
    height: 14,
    class: className,
    "stroke-width": 1.85,
  }).outerHTML;
}

function ensureHost(): HTMLElement {
  if (host?.isConnected) {
    host.dataset.theme = themeName();
    return host;
  }
  const existing = document.querySelector<HTMLElement>("[data-sonner-toaster]");
  if (existing) {
    host = existing;
    host.dataset.theme = themeName();
    return existing;
  }
  const next = document.createElement("div");
  next.className = "sonner-toaster toaster group";
  next.dataset.sonnerToaster = "";
  next.dataset.theme = themeName();
  next.dataset.expanded = "false";
  next.setAttribute("aria-live", "polite");
  next.style.setProperty("--width", `${TOAST_WIDTH}px`);
  next.style.setProperty("--gap", `${GAP}px`);
  next.addEventListener("mouseenter", () => {
    expanded = true;
    next.dataset.expanded = "true";
    layoutStack();
  });
  next.addEventListener("mouseleave", () => {
    expanded = false;
    next.dataset.expanded = "false";
    layoutStack();
  });
  document.body.appendChild(next);
  host = next;
  return next;
}

function layoutStack(): void {
  const toaster = host;
  if (!toaster) {
    return;
  }
  toaster.dataset.theme = themeName();
  let offset = 0;
  let frontHeight = 0;
  toasts.forEach((item, index) => {
    const height = item.element.offsetHeight || 64;
    if (index === 0) {
      frontHeight = height;
    }
    item.element.dataset.front = index === 0 ? "true" : "false";
    item.element.dataset.index = String(index);
    item.element.style.setProperty("--index", String(index));
    item.element.style.setProperty("--offset", `${offset}px`);
    item.element.style.zIndex = String(1000 - index);
    if (expanded) {
      offset += height + GAP;
    } else {
      offset += 10;
    }
  });
  const collapsedExtra = Math.min(Math.max(toasts.length - 1, 0), 2) * 10;
  const total = expanded ? offset : frontHeight + collapsedExtra;
  toaster.style.height = `${Math.max(total, frontHeight)}px`;
}

function dismissToast(id: string): void {
  const index = toasts.findIndex((item) => item.id === id);
  if (index < 0) {
    return;
  }
  const [item] = toasts.splice(index, 1);
  window.clearTimeout(item.timer);
  item.element.dataset.removed = "true";
  window.setTimeout(() => {
    item.element.remove();
    layoutStack();
  }, 320);
  layoutStack();
}

function renderToast(record: Omit<ToastRecord, "element" | "timer">): HTMLElement {
  const el = document.createElement("div");
  el.className = "sonner-toast";
  el.dataset.sonnerToast = record.id;
  el.dataset.type = record.type;
  el.dataset.richColors = record.type === "default" ? "false" : "true";
  el.dataset.mounted = "false";
  el.setAttribute("role", "status");

  const typeIcon =
    record.type === "default" ? "" : iconHtml(TYPE_ICONS[record.type], "sonner-lucide");
  const closeIcon = iconHtml(X, "sonner-lucide");

  el.innerHTML = `
    <button type="button" class="sonner-toast-close" data-close-button aria-label="关闭">
      ${closeIcon}
    </button>
    ${typeIcon ? `<div class="sonner-toast-icon" data-icon>${typeIcon}</div>` : ""}
    <div class="sonner-toast-content" data-content>
      <div class="sonner-toast-title" data-title></div>
      ${record.description ? `<div class="sonner-toast-description" data-description></div>` : ""}
    </div>
  `;
  const title = el.querySelector("[data-title]");
  if (title) {
    title.textContent = record.title;
  }
  const description = el.querySelector("[data-description]");
  if (description && record.description) {
    description.textContent = record.description;
  }
  el.querySelector("[data-close-button]")?.addEventListener("click", () => {
    dismissToast(record.id);
  });
  return el;
}

function pushToast(title: string, options: ToastOptions = {}): string {
  const toaster = ensureHost();
  const id = `toast-${++seq}`;
  const type = options.type ?? "default";
  const duration = options.duration ?? DEFAULT_DURATION;
  const element = renderToast({
    id,
    title,
    description: options.description,
    type,
    duration,
  });
  const timer =
    duration > 0
      ? window.setTimeout(() => {
          dismissToast(id);
        }, duration)
      : 0;
  const record: ToastRecord = {
    id,
    title,
    description: options.description,
    type,
    duration,
    element,
    timer,
  };
  toasts.unshift(record);
  toaster.appendChild(element);
  window.requestAnimationFrame(() => {
    element.dataset.mounted = "true";
    layoutStack();
  });
  while (toasts.length > MAX_VISIBLE) {
    const oldest = toasts[toasts.length - 1];
    dismissToast(oldest.id);
  }
  return id;
}

function toastFn(title: string, options?: ToastOptions): string {
  return pushToast(title, options);
}

toastFn.success = (title: string, options?: Omit<ToastOptions, "type">) =>
  pushToast(title, { ...options, type: "success" });
toastFn.info = (title: string, options?: Omit<ToastOptions, "type">) =>
  pushToast(title, { ...options, type: "info" });
toastFn.warning = (title: string, options?: Omit<ToastOptions, "type">) =>
  pushToast(title, { ...options, type: "warning" });
toastFn.error = (title: string, options?: Omit<ToastOptions, "type">) =>
  pushToast(title, { ...options, type: "error" });
toastFn.dismiss = dismissToast;

export const toast = toastFn;

export function mountToaster(): void {
  ensureHost();
  const observer = new MutationObserver(() => {
    if (host) {
      host.dataset.theme = themeName();
    }
  });
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
}
