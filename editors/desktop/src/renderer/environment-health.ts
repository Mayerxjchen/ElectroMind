import type { EnvironmentCheck } from "../shared/protocol";

export type HealthItemId = "uv" | "pagent" | "apiKey" | "runtime" | "image";

export type HealthItem = {
  id: HealthItemId;
  label: string;
  ok: boolean;
  optional: boolean;
  detail: string;
};

export const INSTALL_COMMANDS =
  "curl -LsSf https://astral.sh/uv/install.sh | sh\nuv tool install --force pagent";

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  if (bytes < 1024 * 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export function buildHealthItems(env: EnvironmentCheck): HealthItem[] {
  return [
    {
      id: "uv",
      label: "uv",
      ok: env.uvInstalled,
      optional: false,
      detail: env.uvInstalled ? (env.uvPath ?? "已安装") : "未找到",
    },
    {
      id: "pagent",
      label: "pagent CLI",
      ok: env.pagentInstalled,
      optional: false,
      detail: env.pagentInstalled ? (env.pagentPath ?? "已安装") : "未找到",
    },
    {
      id: "apiKey",
      label: "API Key",
      ok: env.apiKeyConfigured,
      optional: false,
      detail: env.apiKeyConfigured ? "已配置" : "未配置",
    },
    {
      id: "runtime",
      label: "容器运行时",
      ok: Boolean(env.containerRuntime),
      optional: true,
      detail: env.containerRuntime ?? "未安装（local 沙箱可忽略）",
    },
    {
      id: "image",
      label: `镜像 ${env.sandboxImage}`,
      ok: env.sandboxImageExists,
      optional: true,
      detail: env.sandboxImageExists
        ? "已安装"
        : env.containerRuntime
          ? "未找到"
          : "未检测",
    },
  ];
}

function itemState(item: HealthItem): "ok" | "fail" | "optional" {
  if (item.ok) {
    return "ok";
  }
  return item.optional ? "optional" : "fail";
}

function formatDataHomeSize(env: EnvironmentCheck): string {
  if (env.dataHomeBytes === undefined) {
    return "无法读取";
  }
  return formatBytes(env.dataHomeBytes);
}

function formatImageDiskSize(env: EnvironmentCheck): string {
  if (!env.containerRuntime) {
    return "未检测";
  }
  if (!env.sandboxImageExists) {
    return "未安装";
  }
  if (env.sandboxImageBytes === undefined) {
    return "—";
  }
  return formatBytes(env.sandboxImageBytes);
}

function renderDiskUsage(env: EnvironmentCheck): string {
  const total =
    env.dataHomeBytes === undefined
      ? undefined
      : env.dataHomeBytes + (env.sandboxImageBytes ?? 0);
  return `
    <div class="health-disk">
      <div class="health-section-label">磁盘占用</div>
      <div class="health-disk-table">
        <div class="health-disk-row">
          <span class="health-disk-name" title="${escapeHtml(env.dataHomePath)}">${escapeHtml(env.dataHomeLabel)}</span>
          <span class="health-disk-size">${formatDataHomeSize(env)}</span>
        </div>
        <div class="health-disk-row">
          <span class="health-disk-name">镜像 ${escapeHtml(env.sandboxImage)}</span>
          <span class="health-disk-size">${formatImageDiskSize(env)}</span>
        </div>
        ${
          total === undefined
            ? ""
            : `
        <div class="health-disk-row is-total">
          <span class="health-disk-name">合计</span>
          <span class="health-disk-size">${formatBytes(total)}</span>
        </div>
        `
        }
      </div>
    </div>
  `;
}

/** 设置页：环境自检（诊断面板，不是首次向导） */
export function renderHealthPanel(env: EnvironmentCheck): string {
  const items = buildHealthItems(env);
  const requiredOk = items.filter((i) => !i.optional).every((i) => i.ok);

  return `
    <section class="health-panel">
      <div class="health-head">
        <div>
          <div class="health-title">环境自检</div>
          <div class="health-summary ${requiredOk ? "is-ok" : "is-warn"}">
            ${requiredOk ? "必需项就绪" : "有必需项未就绪"}
          </div>
        </div>
        <button class="new-session-secondary" type="button" data-health-refresh>重新检测</button>
      </div>
      <div class="health-list">
        ${items
          .map((item) => {
            const state = itemState(item);
            return `
              <div class="health-row is-${state}">
                <span class="health-light" aria-hidden="true"></span>
                <span class="health-name">${escapeHtml(item.label)}</span>
                <span class="health-detail">${escapeHtml(item.detail)}</span>
              </div>
            `;
          })
          .join("")}
      </div>
      ${renderDiskUsage(env)}
      <div class="health-actions">
        <button class="new-session-secondary" type="button" data-health-copy-cmd>复制安装命令</button>
        <button class="new-session-secondary" type="button" data-health-install-pagent ${env.uvInstalled ? "" : "disabled"}>安装 pagent</button>
      </div>
    </section>
  `;
}

export type HealthActionHandlers = {
  onRefresh: () => void | Promise<void>;
  onCopyCommands: () => void | Promise<void>;
  onInstallPagent: () => void | Promise<void>;
};

export function bindHealthPanel(root: HTMLElement, handlers: HealthActionHandlers): void {
  root.querySelector<HTMLButtonElement>("[data-health-refresh]")?.addEventListener("click", () => {
    void handlers.onRefresh();
  });
  root.querySelector<HTMLButtonElement>("[data-health-copy-cmd]")?.addEventListener("click", () => {
    void handlers.onCopyCommands();
  });
  root.querySelector<HTMLButtonElement>("[data-health-install-pagent]")?.addEventListener("click", () => {
    void handlers.onInstallPagent();
  });
}
