// electromind home 固定为 ~/.electromind（与后端默认 prod 模式对齐）。
// 后端不带 --dev 时一律用 ~/.electromind；VS Code 扩展始终以该模式启动，
// 因此这里不再做「工作区下有没有 .electromind」的探测，避免与后端 home 分裂。

import { homedir } from "node:os";
import { join } from "node:path";

export function resolveElectromindHome(): string {
  return join(homedir(), ".electromind");
}

export function homeConfigPath(): string {
  return join(resolveElectromindHome(), "config.toml");
}

export function homeThreadsRoot(): string {
  return join(resolveElectromindHome(), "threads");
}
