// 首次使用：检测 API Key，引导写入 ~/.pagent/pagent.toml。
// Setup 三项：api_key（必填）、model（可默认）、base_url（可留空）。

import { mkdir, readFile, writeFile, chmod } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";

import * as vscode from "vscode";

const USER_CONFIG_REL = join(".pagent", "pagent.toml");
export const DEFAULT_MODEL = "deepseek-v4-flash";

export type ProviderSetup = {
  apiKey: string;
  model: string;
  baseUrl?: string;
};

export function userConfigPath(): string {
  return join(homedir(), USER_CONFIG_REL);
}

/** 环境变量 / ~/.pagent / 工作区 pagent.toml 是否已有可用 Key。 */
export async function hasConfiguredApiKey(
  workspaceRoot?: string,
): Promise<boolean> {
  const fromEnv = process.env.DEEPSEEK_API_KEY?.trim();
  if (fromEnv) {
    return true;
  }
  const candidates = [userConfigPath()];
  if (workspaceRoot) {
    candidates.push(join(workspaceRoot, "pagent.toml"));
  }
  for (const path of candidates) {
    try {
      const text = await readFile(path, "utf8");
      if (providerFieldFromToml(text, "api_key").length > 0) {
        return true;
      }
    } catch {
      // 文件不存在则看下一个。
    }
  }
  return false;
}

/** 从 toml 文本取出 [provider] 某字段（够用的轻量解析，不引依赖）。 */
export function providerFieldFromToml(text: string, field: string): string {
  const match = text.match(new RegExp(`^\\s*${field}\\s*=\\s*(.*)$`, "m"));
  if (!match) {
    return "";
  }
  let raw = match[1].trim();
  if (raw.startsWith('"') && raw.endsWith('"')) {
    raw = raw.slice(1, -1).replace(/\\"/g, '"').replace(/\\\\/g, "\\");
  } else if (raw.startsWith("'") && raw.endsWith("'")) {
    raw = raw.slice(1, -1);
  }
  return raw.trim();
}

/** @deprecated 用 providerFieldFromToml(text, "api_key") */
export function providerApiKeyFromToml(text: string): string {
  return providerFieldFromToml(text, "api_key");
}

function tomlEscape(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

export function upsertProviderField(
  text: string,
  field: string,
  value: string,
): string {
  const keyLine = `${field} = "${tomlEscape(value)}"`;
  const pattern = new RegExp(`^\\s*${field}\\s*=\\s*.*$`, "m");
  if (pattern.test(text)) {
    return text.replace(pattern, keyLine);
  }
  const provider = text.match(/^\[provider\]\s*$/m);
  if (provider && provider.index !== undefined) {
    const at = provider.index + provider[0].length;
    return `${text.slice(0, at)}\n${keyLine}${text.slice(at)}`;
  }
  const suffix = text.endsWith("\n") || text.length === 0 ? "" : "\n";
  return `${text}${suffix}\n[provider]\n${keyLine}\n`;
}

export function removeProviderField(text: string, field: string): string {
  return text.replace(new RegExp(`^\\s*${field}\\s*=\\s*.*\\n?`, "m"), "");
}

export function upsertProviderApiKey(text: string, apiKey: string): string {
  return upsertProviderField(text, "api_key", apiKey);
}

/** 写入 ~/.pagent/pagent.toml 的 provider 段；目录不存在则创建。 */
export async function writeUserProvider(setup: ProviderSetup): Promise<string> {
  const apiKey = setup.apiKey.trim();
  if (!apiKey) {
    throw new Error("api_key 不能为空");
  }
  const model = setup.model.trim() || DEFAULT_MODEL;
  const baseUrl = setup.baseUrl?.trim() ?? "";

  const path = userConfigPath();
  await mkdir(join(homedir(), ".pagent"), { recursive: true });
  let text: string;
  try {
    text = await readFile(path, "utf8");
  } catch {
    text =
      "# 用户级 pagent 配置（跨项目）\n" +
      "# 合并顺序：bundled < ~/.pagent/pagent.toml < ./pagent.toml < CLI\n\n" +
      "[provider]\n";
  }
  text = upsertProviderField(text, "api_key", apiKey);
  text = upsertProviderField(text, "model", model);
  text = baseUrl
    ? upsertProviderField(text, "base_url", baseUrl)
    : removeProviderField(text, "base_url");

  await writeFile(path, text, "utf8");
  try {
    await chmod(path, 0o600);
  } catch {
    // Windows 等平台可能不支持 chmod，忽略。
  }
  return path;
}

export async function writeUserApiKey(apiKey: string): Promise<string> {
  return writeUserProvider({ apiKey, model: DEFAULT_MODEL });
}

/** 逐步弹出 api_key / model / base_url；取消任一步返回 false。 */
export async function promptAndSaveProvider(
  output?: vscode.OutputChannel,
): Promise<boolean> {
  const apiKey = await vscode.window.showInputBox({
    title: "pagent setup (1/3)",
    prompt: "API Key（必填），将保存到 ~/.pagent/pagent.toml",
    password: true,
    ignoreFocusOut: true,
    placeHolder: "sk-...",
    validateInput: (value) =>
      value.trim() ? undefined : "API Key 不能为空",
  });
  if (apiKey === undefined) {
    void vscode.window.showWarningMessage(
      "pagent：已取消 setup。可在命令面板运行 “pagent: Setup API Key” 重试。",
    );
    return false;
  }

  const model = await vscode.window.showInputBox({
    title: "pagent setup (2/3)",
    prompt: "模型 ID（回车用默认）",
    ignoreFocusOut: true,
    value: DEFAULT_MODEL,
    placeHolder: DEFAULT_MODEL,
  });
  if (model === undefined) {
    void vscode.window.showWarningMessage("pagent：已取消 setup。");
    return false;
  }

  const baseUrl = await vscode.window.showInputBox({
    title: "pagent setup (3/3)",
    prompt: "Base URL（可选；官方 DeepSeek 请留空）",
    ignoreFocusOut: true,
    placeHolder: "https://api.deepseek.com（留空=默认）",
  });
  if (baseUrl === undefined) {
    void vscode.window.showWarningMessage("pagent：已取消 setup。");
    return false;
  }

  const path = await writeUserProvider({
    apiKey,
    model: model.trim() || DEFAULT_MODEL,
    baseUrl: baseUrl.trim() || undefined,
  });
  output?.appendLine(`[setup] 已写入 ${path}`);
  void vscode.window.showInformationMessage(`pagent：配置已保存到 ${path}`);
  return true;
}

/** @deprecated 请用 promptAndSaveProvider */
export async function promptAndSaveApiKey(
  output?: vscode.OutputChannel,
  _options?: { prompt?: string },
): Promise<boolean> {
  return promptAndSaveProvider(output);
}

/**
 * 若尚未配置 Key，弹出 setup。
 * @returns true 表示已具备 Key（原本就有或刚写好）；false 表示用户取消。
 */
export async function ensureApiKeySetup(
  output?: vscode.OutputChannel,
  workspaceRoot?: string,
): Promise<boolean> {
  if (await hasConfiguredApiKey(workspaceRoot)) {
    return true;
  }
  return promptAndSaveProvider(output);
}
