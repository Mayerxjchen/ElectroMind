import { execFileSync } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";

import { enrichedPath, resolveCliCommand } from "../shared/agent";
import {
  DEFAULT_MODEL,
  mergeProviderToml,
  providerFieldFromToml,
  type ProviderSetup,
} from "../shared/provider-config";
import type { EnvironmentCheck, OnboardingState, SandboxBackendOption } from "../shared/protocol";

const DEFAULT_SANDBOX_IMAGE = "pagent:latest";

function desktopSettingsPath(): string {
  return path.join(homedir(), ".pagent", "desktop.json");
}

function pagentConfigPath(): string {
  return path.join(homedir(), ".pagent", "pagent.toml");
}

function pagentDataHomePath(): string {
  return path.join(homedir(), ".pagent");
}

function tildePath(full: string): string {
  const home = homedir();
  return full.startsWith(home) ? `~${full.slice(home.length)}` : full;
}

function walkDirectorySizeBytes(dir: string): number | undefined {
  let total = 0;
  const stack = [dir];
  while (stack.length > 0) {
    const current = stack.pop();
    if (!current) {
      break;
    }
    let entries;
    try {
      entries = readdirSync(current, { withFileTypes: true });
    } catch {
      return undefined;
    }
    for (const entry of entries) {
      const full = path.join(current, entry.name);
      try {
        if (entry.isDirectory()) {
          stack.push(full);
        } else if (entry.isFile()) {
          total += statSync(full).size;
        }
      } catch {
        // permission denied, etc.
      }
    }
  }
  return total;
}

function directorySizeBytes(dir: string): number | undefined {
  if (!existsSync(dir)) {
    return 0;
  }
  if (process.platform !== "win32") {
    try {
      const out = execFileSync("du", ["-sk", dir], {
        encoding: "utf8",
        timeout: 120_000,
      }).trim();
      const kb = Number.parseInt(out.split(/\s+/)[0] ?? "", 10);
      if (Number.isFinite(kb) && kb >= 0) {
        return kb * 1024;
      }
    } catch {
      // fallback to walk
    }
  }
  return walkDirectorySizeBytes(dir);
}

function imageSizeBytes(runtime: "docker" | "podman", image: string): number | undefined {
  try {
    const out = execFileSync(runtime, ["image", "inspect", image, "--format", "{{.Size}}"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
      timeout: 20_000,
    }).trim();
    const bytes = Number.parseInt(out, 10);
    return Number.isFinite(bytes) && bytes >= 0 ? bytes : undefined;
  } catch {
    return undefined;
  }
}

function readDesktopJson(): Record<string, unknown> {
  try {
    return JSON.parse(readFileSync(desktopSettingsPath(), "utf8")) as Record<string, unknown>;
  } catch {
    return {};
  }
}

function writeDesktopJson(patch: Record<string, unknown>): void {
  const filePath = desktopSettingsPath();
  mkdirSync(path.dirname(filePath), { recursive: true });
  const existing = readDesktopJson();
  writeFileSync(
    filePath,
    `${JSON.stringify({ ...existing, ...patch }, null, 2)}\n`,
    "utf8",
  );
}

function cliOnPath(command: string): boolean {
  try {
    execFileSync("/bin/sh", ["-c", `command -v ${shellQuote(command)}`], {
      encoding: "utf8",
      env: { ...process.env, PATH: enrichedPath() },
      stdio: ["ignore", "pipe", "ignore"],
    });
    return true;
  } catch {
    const resolved = resolveCliCommand(command);
    if (resolved.includes("/")) {
      return existsSync(resolved);
    }
    return false;
  }
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

function readSandboxImageName(): string {
  const configPath = pagentConfigPath();
  if (!existsSync(configPath)) {
    return DEFAULT_SANDBOX_IMAGE;
  }
  try {
    const text = readFileSync(configPath, "utf8");
    const sandbox = /\[sandbox\][\s\S]*?(?=\n\[|$)/.exec(text);
    if (sandbox) {
      const match = sandbox[0].match(/^\s*image\s*=\s*"([^"]+)"/m);
      if (match?.[1]) {
        return match[1];
      }
    }
  } catch {
    // ignore
  }
  return DEFAULT_SANDBOX_IMAGE;
}

function imageExists(runtime: "docker" | "podman", image: string): boolean {
  try {
    execFileSync(runtime, ["image", "inspect", image], {
      stdio: "pipe",
      timeout: 20_000,
    });
    return true;
  } catch {
    return false;
  }
}

export function hasConfiguredApiKey(): boolean {
  const fromEnv = process.env.DEEPSEEK_API_KEY?.trim();
  if (fromEnv) {
    return true;
  }
  const configPath = pagentConfigPath();
  if (!existsSync(configPath)) {
    return false;
  }
  try {
    const text = readFileSync(configPath, "utf8");
    return providerFieldFromToml(text, "api_key").length > 0;
  } catch {
    return false;
  }
}

export function getEnvironmentCheck(options?: {
  /** 是否统计磁盘占用（偏慢）；设置页自检为 true，启动挡墙为 false */
  includeDisk?: boolean;
}): EnvironmentCheck {
  const includeDisk = options?.includeDisk === true;
  const uvInstalled = cliOnPath("uv");
  const pagentInstalled = cliOnPath("pagent");
  const dockerInstalled = cliOnPath("docker");
  const podmanInstalled = cliOnPath("podman");
  const containerRuntime = dockerInstalled ? "docker" : podmanInstalled ? "podman" : undefined;
  const image = readSandboxImageName();
  const sandboxImageExists = containerRuntime
    ? imageExists(containerRuntime, image)
    : false;
  const dataHomePath = pagentDataHomePath();

  return {
    uvInstalled,
    uvPath: uvInstalled ? resolveCliCommand("uv") : undefined,
    pagentInstalled,
    pagentPath: pagentInstalled ? resolveCliCommand("pagent") : undefined,
    apiKeyConfigured: hasConfiguredApiKey(),
    dockerInstalled,
    podmanInstalled,
    containerRuntime,
    sandboxImage: image,
    sandboxImageExists,
    configPath: pagentConfigPath(),
    dataHomePath,
    dataHomeLabel: tildePath(dataHomePath),
    dataHomeBytes: includeDisk ? directorySizeBytes(dataHomePath) : undefined,
    sandboxImageBytes:
      includeDisk && containerRuntime && sandboxImageExists
        ? imageSizeBytes(containerRuntime, image)
        : undefined,
  };
}

/** 能正常对话的最低条件：CLI + API Key。 */
export function isEnvironmentReady(env: EnvironmentCheck): boolean {
  return env.pagentInstalled && env.apiKeyConfigured;
}

export function getOnboardingState(): OnboardingState {
  const data = readDesktopJson();
  // 启动挡墙走快速检测，不跑 du / 镜像体积
  const env = getEnvironmentCheck({ includeDisk: false });
  const completed = data.onboardingCompleted === true;
  const skipped = data.onboardingSkipped === true;
  const blocked = !isEnvironmentReady(env);
  const preferredBackend = data.preferredBackend;
  return {
    completed,
    skipped,
    blocked,
    // 未就绪必须挡墙；已就绪则只在未完成/未跳过时展示可选向导
    shouldShow: blocked || (!completed && !skipped),
    preferredBackend:
      preferredBackend === "local" ||
      preferredBackend === "container" ||
      preferredBackend === "ssh"
        ? preferredBackend
        : "local",
    environment: env,
  };
}

export function saveProviderSetup(setup: ProviderSetup): string {
  const apiKey = setup.apiKey.trim();
  if (!apiKey) {
    throw new Error("API Key 不能为空");
  }
  const configPath = pagentConfigPath();
  mkdirSync(path.dirname(configPath), { recursive: true });
  let text = "";
  try {
    text = readFileSync(configPath, "utf8");
  } catch {
    text = "";
  }
  const next = mergeProviderToml(text, {
    apiKey,
    model: setup.model.trim() || DEFAULT_MODEL,
    baseUrl: setup.baseUrl?.trim() || undefined,
  });
  writeFileSync(configPath, next, "utf8");
  try {
    chmodSync(configPath, 0o600);
  } catch {
    // Windows 等忽略
  }
  return configPath;
}

export function installPagentCli(): { ok: boolean; error?: string; pagentPath?: string } {
  if (!cliOnPath("uv")) {
    return { ok: false, error: "未找到 uv，请先安装：https://docs.astral.sh/uv/" };
  }
  const uvBin = resolveCliCommand("uv");
  try {
    execFileSync(uvBin, ["tool", "install", "--force", "pagent"], {
      encoding: "utf8",
      env: { ...process.env, PATH: enrichedPath() },
      stdio: ["ignore", "pipe", "pipe"],
      timeout: 300_000,
    });
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return { ok: false, error: detail };
  }
  if (!cliOnPath("pagent")) {
    return {
      ok: false,
      error: "安装完成但仍找不到 pagent，请确认 ~/.local/bin 在 PATH 中。",
    };
  }
  return { ok: true, pagentPath: resolveCliCommand("pagent") };
}

export function completeOnboarding(options?: {
  preferredBackend?: SandboxBackendOption;
  skipped?: boolean;
}): void {
  const env = getEnvironmentCheck();
  // 未就绪时禁止「稍后配置」：跳过无效，挡墙仍会再次打开
  if (options?.skipped) {
    if (!isEnvironmentReady(env)) {
      return;
    }
    writeDesktopJson({ onboardingSkipped: true });
    return;
  }
  if (!isEnvironmentReady(env)) {
    throw new Error("请先安装 pagent 并配置 API Key");
  }
  const patch: Record<string, unknown> = { onboardingCompleted: true, onboardingSkipped: false };
  if (options?.preferredBackend) {
    patch.preferredBackend = options.preferredBackend;
  }
  writeDesktopJson(patch);
}
