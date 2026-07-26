// pagent home 固定为 ~/.pagent（与后端默认 prod 模式对齐）。
// 后端不带 --dev 时一律用 ~/.pagent；VS Code 扩展始终以该模式启动，
// 因此这里不再做「工作区下有没有 .pagent」的探测，避免与后端 home 分裂。

import { homedir } from "node:os";
import { join } from "node:path";

export function resolvePagentHome(): string {
  return join(homedir(), ".pagent");
}

export function homeConfigPath(): string {
  return join(resolvePagentHome(), "pagent.toml");
}

export function homeThreadsRoot(): string {
  return join(resolvePagentHome(), "threads");
}
