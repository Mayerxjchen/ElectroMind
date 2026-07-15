// pagent home 二选一（与 Python pagentv4.paths.resolve_pagent_home 对齐）：
//   A <workspace>/.pagent  —— 目录存在，或工作区根有遗留 pagent.toml
//   B ~/.pagent

import { existsSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

export function resolvePagentHome(workspaceRoot?: string): string {
  if (workspaceRoot) {
    const project = join(workspaceRoot, ".pagent");
    try {
      if (statSync(project).isDirectory()) {
        return project;
      }
    } catch {
      // 不存在
    }
    if (existsSync(join(workspaceRoot, "pagent.toml"))) {
      return project;
    }
  }
  return join(homedir(), ".pagent");
}

export function homeConfigPath(workspaceRoot?: string): string {
  return join(resolvePagentHome(workspaceRoot), "pagent.toml");
}

export function homeThreadsRoot(workspaceRoot?: string): string {
  return join(resolvePagentHome(workspaceRoot), "threads");
}
