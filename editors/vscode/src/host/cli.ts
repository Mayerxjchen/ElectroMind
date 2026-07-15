// 解析 / 安装全局 pagent CLI（uv tool install），不依赖当前工作区目录。

import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { delimiter, join } from "node:path";

import * as vscode from "vscode";

/** GUI 启动的编辑器常缺少 shell PATH；补上 uv tool 默认 bin。 */
export function enrichedPath(base = process.env.PATH ?? ""): string {
  const home = homedir();
  const extras = [
    join(home, ".local", "bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
  ];
  const parts = [...extras, ...base.split(delimiter).filter(Boolean)];
  return [...new Set(parts)].join(delimiter);
}

/** 把配置里的 command 解析成可 spawn 的绝对路径（尽量）。 */
export function resolveCliCommand(command: string): string {
  const trimmed = command.trim() || "pagent";
  if (trimmed.includes("/") || trimmed.includes("\\")) {
    return trimmed.replace(/^~/, homedir());
  }
  const local = join(homedir(), ".local", "bin", trimmed);
  if (existsSync(local)) {
    return local;
  }
  try {
    const found = execFileSync("/bin/sh", ["-c", `command -v ${shellQuote(trimmed)}`], {
      encoding: "utf8",
      env: { ...process.env, PATH: enrichedPath() },
    }).trim();
    if (found) {
      return found;
    }
  } catch {
    // fall through
  }
  return trimmed;
}

export function cliExists(command: string): boolean {
  const resolved = resolveCliCommand(command);
  if (resolved.includes("/") || resolved.includes("\\")) {
    return existsSync(resolved);
  }
  try {
    execFileSync("/bin/sh", ["-c", `command -v ${shellQuote(resolved)}`], {
      encoding: "utf8",
      env: { ...process.env, PATH: enrichedPath() },
      stdio: ["ignore", "pipe", "ignore"],
    });
    return true;
  } catch {
    return false;
  }
}

/** monorepo 根（editors/vscode 的上两级）；开发期可选 editable install。 */
export function detectRepoRoot(extensionUri: vscode.Uri): string | undefined {
  const root = vscode.Uri.joinPath(extensionUri, "..", "..").fsPath;
  return existsSync(join(root, "pyproject.toml")) ? root : undefined;
}

/**
 * 确保本机有 pagent CLI。没有则引导 `uv tool install pagent`。
 * 若能定位本仓库，额外提供 editable 安装（开发用）。
 */
export async function ensurePagentCli(
  extensionUri: vscode.Uri,
  output: vscode.OutputChannel,
  configuredCommand = "pagent",
): Promise<string | undefined> {
  if (cliExists(configuredCommand)) {
    return resolveCliCommand(configuredCommand);
  }

  const repoRoot = detectRepoRoot(extensionUri);
  const installPyPI = "uv tool install pagent";
  const installEditable = "本仓库 editable 安装";
  const copyCmd = "复制安装命令";

  const buttons = repoRoot
    ? [installPyPI, installEditable, copyCmd]
    : [installPyPI, copyCmd];

  const pick = await vscode.window.showWarningMessage(
    "未找到全局 pagent CLI。请先：uv tool install pagent",
    ...buttons,
  );

  if (pick === copyCmd) {
    const cmd = "uv tool install pagent";
    await vscode.env.clipboard.writeText(cmd);
    void vscode.window.showInformationMessage(`已复制：${cmd}`);
    return undefined;
  }

  if (pick !== installPyPI && pick !== installEditable) {
    return undefined;
  }

  const uv = resolveCliCommand("uv");
  if (!cliExists("uv") && !existsSync(uv)) {
    void vscode.window.showErrorMessage(
      "未找到 uv。请先安装 uv：https://docs.astral.sh/uv/",
    );
    return undefined;
  }

  const uvBin = existsSync(uv) ? uv : "uv";
  const uvArgs =
    pick === installEditable && repoRoot
      ? ["tool", "install", "--editable", "--force", repoRoot]
      : ["tool", "install", "--force", "pagent"];

  output.appendLine(`[setup] ${uvBin} ${uvArgs.join(" ")}`);
  try {
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: "正在 uv tool install pagent…",
      },
      async () => {
        execFileSync(uvBin, uvArgs, {
          encoding: "utf8",
          env: { ...process.env, PATH: enrichedPath() },
          stdio: ["ignore", "pipe", "pipe"],
        });
      },
    );
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    output.appendLine(`[setup] install failed: ${detail}`);
    void vscode.window.showErrorMessage(
      `pagent 安装失败：${detail}。也可在终端执行：uv tool install pagent`,
    );
    return undefined;
  }

  if (!cliExists(configuredCommand)) {
    void vscode.window.showErrorMessage(
      "安装完成但仍找不到 pagent，请确认 ~/.local/bin 在 PATH 中。",
    );
    return undefined;
  }

  const path = resolveCliCommand(configuredCommand);
  output.appendLine(`[setup] pagent -> ${path}`);
  void vscode.window.showInformationMessage(`pagent 已安装：${path}`);
  return path;
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}
