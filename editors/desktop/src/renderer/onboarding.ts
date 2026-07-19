import { DEFAULT_MODEL } from "../shared/provider-config";
import type { EnvironmentCheck, OnboardingState, SandboxBackendOption } from "../shared/protocol";
import { INSTALL_COMMANDS } from "./environment-health";

type OnboardingDraft = {
  step: number;
  apiKey: string;
  model: string;
  baseUrl: string;
  preferredBackend: "local" | "container" | "ssh";
};

function escapeAttr(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;");
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderSetupStepper(currentStep: number): string {
  const steps = [
    { n: 1, label: "环境" },
    { n: 2, label: "API Key" },
    { n: 3, label: "沙箱" },
  ];
  return `
    <nav class="setup-stepper" aria-label="设置步骤">
      ${steps
        .map((step, index) => {
          const state =
            currentStep === step.n ? "is-active" : currentStep > step.n ? "is-done" : "";
          const connector =
            index < steps.length - 1
              ? `<span class="setup-stepper-connector ${currentStep > step.n ? "is-done" : ""}" aria-hidden="true"></span>`
              : "";
          return `
            <div class="setup-stepper-step ${state}">
              <span class="setup-stepper-dot">${currentStep > step.n ? "✓" : step.n}</span>
              <span class="setup-stepper-text">${step.label}</span>
            </div>
            ${connector}
          `;
        })
        .join("")}
    </nav>
  `;
}

function renderStepEnv(env: EnvironmentCheck): string {
  const rows = [
    {
      ok: env.uvInstalled,
      label: "uv",
      detail: env.uvInstalled ? "已安装" : "需要安装",
    },
    {
      ok: env.pagentInstalled,
      label: "pagent CLI",
      detail: env.pagentInstalled ? "已安装" : "需要安装",
    },
  ];
  const ready = env.uvInstalled && env.pagentInstalled;
  return `
    <div class="setup-pane">
      <p class="setup-lead">确认本机已安装运行依赖。默认使用 <strong>local</strong> 沙箱，无需 Docker。</p>
      <div class="setup-checklist">
        ${rows
          .map(
            (row) => `
          <div class="setup-check ${row.ok ? "is-ok" : "is-fail"}">
            <span class="setup-check-mark" aria-hidden="true">${row.ok ? "✓" : "!"}</span>
            <span class="setup-check-label">${row.label}</span>
            <span class="setup-check-detail">${row.detail}</span>
          </div>
        `,
          )
          .join("")}
      </div>
      ${
        ready
          ? `<p class="setup-ready">环境已就绪，可以继续。</p>`
          : `
        <div class="setup-fix">
          <pre class="setup-cmd">${escapeHtml(INSTALL_COMMANDS)}</pre>
          <div class="setup-fix-actions">
            <button class="new-session-secondary" type="button" data-setup-copy-cmd>复制命令</button>
            <button class="new-session-secondary" type="button" data-setup-install-pagent ${env.uvInstalled ? "" : "disabled"}>安装 pagent</button>
            <button class="new-session-secondary" type="button" data-setup-refresh>重新检测</button>
          </div>
        </div>
      `
      }
      ${
        ready
          ? `
        <div class="setup-fix-actions">
          <button class="new-session-secondary" type="button" data-setup-refresh>重新检测</button>
        </div>
      `
          : ""
      }
    </div>
  `;
}

function renderStepApiKey(draft: OnboardingDraft, env: EnvironmentCheck): string {
  if (env.apiKeyConfigured && !draft.apiKey) {
    return `
      <div class="setup-pane">
        <p class="setup-lead">已检测到 API Key，可直接下一步；若要更换，在下方填写。</p>
        <p class="setup-note">${escapeHtml(env.configPath)}</p>
        <label class="setup-field">
          <span class="setup-label">API Key（可选）</span>
          <input class="setup-input" data-onboarding-api-key type="password" placeholder="sk-..." autocomplete="off" />
        </label>
      </div>
    `;
  }
  return `
    <div class="setup-pane">
      <p class="setup-lead">配置模型服务 Key，将写入本地配置文件。</p>
      <p class="setup-note">${escapeHtml(env.configPath)}</p>
      <label class="setup-field">
        <span class="setup-label">API Key</span>
        <input class="setup-input" data-onboarding-api-key type="password" placeholder="sk-..." autocomplete="off" value="${escapeAttr(draft.apiKey)}" />
      </label>
      <label class="setup-field">
        <span class="setup-label">模型</span>
        <input class="setup-input" data-onboarding-model type="text" value="${escapeAttr(draft.model || DEFAULT_MODEL)}" />
      </label>
      <label class="setup-field">
        <span class="setup-label">Base URL（可选）</span>
        <input class="setup-input" data-onboarding-base-url type="text" placeholder="留空使用默认" value="${escapeAttr(draft.baseUrl)}" />
      </label>
    </div>
  `;
}

function renderStepSandbox(draft: OnboardingDraft, env: EnvironmentCheck): string {
  const canContainer = Boolean(env.containerRuntime);
  const cards = [
    { id: "local" as const, title: "本机", desc: "推荐 · 无需 Docker", disabled: false },
    {
      id: "container" as const,
      title: "容器",
      desc: canContainer
        ? env.sandboxImageExists
          ? `使用 ${env.sandboxImage}`
          : `缺少镜像 ${env.sandboxImage}`
        : "需要 docker / podman",
      disabled: !canContainer,
    },
    { id: "ssh" as const, title: "远程", desc: "新建任务时再填主机", disabled: false },
  ];
  return `
    <div class="setup-pane">
      <p class="setup-lead">选择默认沙箱偏好，之后仍可在「新建任务」里修改。</p>
      <div class="setup-choices">
        ${cards
          .map((card) => {
            const selected = draft.preferredBackend === card.id;
            return `
              <button
                class="setup-choice ${selected ? "is-selected" : ""}"
                type="button"
                data-onboarding-backend="${card.id}"
                ${card.disabled ? "disabled" : ""}
              >
                <span class="setup-choice-title">${card.title}</span>
                <span class="setup-choice-desc">${escapeHtml(card.desc)}</span>
              </button>
            `;
          })
          .join("")}
      </div>
    </div>
  `;
}

function isReady(env: EnvironmentCheck): boolean {
  return env.pagentInstalled && env.apiKeyConfigured;
}

export function renderOnboardingBody(
  draft: OnboardingDraft,
  env: EnvironmentCheck,
  blocked: boolean,
): string {
  let body = "";
  if (draft.step === 1) {
    body = renderStepEnv(env);
  } else if (draft.step === 2) {
    body = renderStepApiKey(draft, env);
  } else {
    body = renderStepSandbox(draft, env);
  }
  const backHidden = draft.step === 1 ? "hidden" : "";
  const nextLabel = draft.step === 3 ? "完成" : "下一步";
  return `
    ${
      blocked
        ? `<p class="setup-guard-banner">完成下列步骤后即可开始使用。</p>`
        : ""
    }
    ${renderSetupStepper(draft.step)}
    ${body}
    <div class="setup-footer">
      ${
        blocked
          ? `<span class="setup-footer-hint">配置完成前无法跳过</span>`
          : `<button class="new-session-secondary" type="button" data-onboarding-skip>稍后配置</button>`
      }
      <div class="setup-footer-main">
        <button class="new-session-secondary" type="button" data-onboarding-back ${backHidden}>上一步</button>
        <button class="new-session-primary" type="button" data-onboarding-next>${nextLabel}</button>
      </div>
    </div>
    <div class="setup-error" data-onboarding-error hidden></div>
  `;
}

export type OnboardingController = {
  open(state: OnboardingState): void;
  /** 当前是否处于硬拦截（不可关闭） */
  isBlocking(): boolean;
  /** 尝试关闭；硬拦截时返回 false */
  tryDismiss(): boolean;
};

export function mountOnboarding(options: {
  modal: HTMLElement;
  body: HTMLElement;
  onBlockedChange?: (blocked: boolean) => void;
  onDone: () => void;
}): OnboardingController {
  const { modal, body, onBlockedChange, onDone } = options;
  let draft: OnboardingDraft = {
    step: 1,
    apiKey: "",
    model: DEFAULT_MODEL,
    baseUrl: "",
    preferredBackend: "local",
  };
  let env: EnvironmentCheck;
  let blocked = false;

  function setBlocked(next: boolean): void {
    blocked = next;
    modal.classList.toggle("is-blocking", blocked);
    const closeBtn = modal.querySelector<HTMLButtonElement>("[data-onboarding-close]");
    if (closeBtn) {
      closeBtn.hidden = blocked;
    }
    onBlockedChange?.(blocked);
  }

  async function refreshEnv(): Promise<void> {
    env = await window.desktop.refreshEnvironmentCheck();
    setBlocked(!isReady(env));
  }

  function showError(message: string): void {
    const el = body.querySelector<HTMLElement>("[data-onboarding-error]");
    if (!el) {
      return;
    }
    if (!message) {
      el.hidden = true;
      el.textContent = "";
      return;
    }
    el.hidden = false;
    el.textContent = message;
  }

  function readDraftFromForm(): void {
    const apiKey = body.querySelector<HTMLInputElement>("[data-onboarding-api-key]")?.value ?? draft.apiKey;
    const model = body.querySelector<HTMLInputElement>("[data-onboarding-model]")?.value ?? draft.model;
    const baseUrl = body.querySelector<HTMLInputElement>("[data-onboarding-base-url]")?.value ?? draft.baseUrl;
    draft = { ...draft, apiKey, model, baseUrl };
  }

  function paint(): void {
    body.innerHTML = renderOnboardingBody(draft, env, blocked);
    bindBody();
  }

  async function finish(skipped = false): Promise<void> {
    if (skipped) {
      if (blocked || !isReady(env)) {
        showError("请先完成环境与 API Key 配置。");
        return;
      }
      await window.desktop.completeOnboarding({ skipped: true });
      close();
      onDone();
      return;
    }
    readDraftFromForm();
    if (!env.apiKeyConfigured && !draft.apiKey.trim()) {
      showError("请填写 API Key。");
      return;
    }
    if (draft.apiKey.trim()) {
      try {
        await window.desktop.saveProviderSetup({
          apiKey: draft.apiKey.trim(),
          model: draft.model.trim() || DEFAULT_MODEL,
          baseUrl: draft.baseUrl.trim() || undefined,
        });
        env = await window.desktop.refreshEnvironmentCheck();
      } catch (error) {
        showError(error instanceof Error ? error.message : String(error));
        return;
      }
    }
    if (!isReady(env)) {
      setBlocked(true);
      showError("请先安装 pagent 并配置 API Key。");
      paint();
      return;
    }
    try {
      await window.desktop.completeOnboarding({ preferredBackend: draft.preferredBackend });
    } catch (error) {
      showError(error instanceof Error ? error.message : String(error));
      return;
    }
    setBlocked(false);
    close();
    onDone();
  }

  function bindBody(): void {
    body.querySelector<HTMLButtonElement>("[data-setup-refresh]")?.addEventListener("click", () => {
      void (async () => {
        showError("");
        await refreshEnv();
        paint();
      })();
    });
    body.querySelector<HTMLButtonElement>("[data-setup-copy-cmd]")?.addEventListener("click", () => {
      void (async () => {
        await navigator.clipboard.writeText(INSTALL_COMMANDS);
        showError("已复制安装命令");
      })();
    });
    body.querySelector<HTMLButtonElement>("[data-setup-install-pagent]")?.addEventListener("click", () => {
      void (async () => {
        showError("正在安装 pagent…");
        const result = await window.desktop.installPagentCli();
        if (!result.ok) {
          showError(result.error ?? "安装失败");
          return;
        }
        showError("");
        await refreshEnv();
        paint();
      })();
    });

    body.querySelector<HTMLButtonElement>("[data-onboarding-back]")?.addEventListener("click", () => {
      readDraftFromForm();
      showError("");
      draft = { ...draft, step: Math.max(1, draft.step - 1) };
      paint();
    });
    body.querySelector<HTMLButtonElement>("[data-onboarding-next]")?.addEventListener("click", () => {
      void (async () => {
        readDraftFromForm();
        showError("");
        if (draft.step === 1) {
          if (!env.pagentInstalled) {
            showError("请先安装 pagent CLI。");
            return;
          }
          draft = { ...draft, step: 2 };
          paint();
          return;
        }
        if (draft.step === 2) {
          if (!env.apiKeyConfigured && !draft.apiKey.trim()) {
            showError("请填写 API Key。");
            return;
          }
          if (draft.apiKey.trim()) {
            try {
              await window.desktop.saveProviderSetup({
                apiKey: draft.apiKey.trim(),
                model: draft.model.trim() || DEFAULT_MODEL,
                baseUrl: draft.baseUrl.trim() || undefined,
              });
              await refreshEnv();
            } catch (error) {
              showError(error instanceof Error ? error.message : String(error));
              return;
            }
          }
          draft = { ...draft, step: 3 };
          paint();
          return;
        }
        await finish(false);
      })();
    });
    body.querySelector<HTMLButtonElement>("[data-onboarding-skip]")?.addEventListener("click", () => {
      void finish(true);
    });
    body.querySelectorAll<HTMLButtonElement>("[data-onboarding-backend]").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.disabled) {
          return;
        }
        const backend = button.dataset.onboardingBackend as SandboxBackendOption | undefined;
        if (backend === "local" || backend === "container" || backend === "ssh") {
          draft = { ...draft, preferredBackend: backend };
          paint();
        }
      });
    });
  }

  function close(): void {
    modal.classList.remove("is-open");
    modal.classList.remove("is-blocking");
    window.setTimeout(() => {
      modal.hidden = true;
    }, 200);
  }

  return {
    open(state: OnboardingState) {
      env = state.environment;
      const nextBlocked = state.blocked || !isReady(env);
      setBlocked(nextBlocked);
      draft = {
        step: 1,
        apiKey: "",
        model: DEFAULT_MODEL,
        baseUrl: "",
        preferredBackend: state.preferredBackend,
      };
      modal.hidden = false;
      // 硬拦截同步打开，避免等 rAF 时背后界面闪一帧
      if (nextBlocked) {
        modal.classList.add("is-open");
      } else {
        requestAnimationFrame(() => {
          modal.classList.add("is-open");
        });
      }
      paint();
    },
    isBlocking() {
      return blocked;
    },
    tryDismiss() {
      if (blocked) {
        return false;
      }
      void finish(true);
      return true;
    },
  };
}
