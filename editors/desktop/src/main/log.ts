/** P4.4: Desktop / Agent / Wire 日志落盘。
 *
 * 日志目录：``~/.electromind/logs/``
 *   - desktop.log  主进程自身事件（桥生命周期、崩溃重载、IPC）
 *   - agent.log    Agent（wire）stderr 原始流
 *   - wire.log     wire 事件流中用户不可见但需排查的协议日志
 *
 * 简单轮转：单个文件超过 5MB 时改名 ``<name>.1.log``（最多保留 1 份旧档），
 * 避免无限增长。
 */

import { appendFileSync, existsSync, mkdirSync, renameSync, statSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";

export const LOG_DIR = path.join(homedir(), ".electromind", "logs");

const MAX_LOG_BYTES = 5 * 1024 * 1024;

let _dirReady = false;

function ensureDir(): void {
  if (_dirReady) {
    return;
  }
  mkdirSync(LOG_DIR, { recursive: true });
  _dirReady = true;
}

function rotateIfNeeded(file: string): void {
  try {
    if (existsSync(file) && statSync(file).size > MAX_LOG_BYTES) {
      renameSync(file, `${file}.1.log`);
    }
  } catch {
    // 轮转失败不阻断写
  }
}

function write(name: string, line: string): void {
  try {
    ensureDir();
    const file = path.join(LOG_DIR, name);
    rotateIfNeeded(file);
    const ts = new Date().toISOString();
    appendFileSync(file, `[${ts}] ${line}\n`, "utf8");
  } catch {
    // 日志写盘失败不能拖垮主进程
  }
}

export const log = {
  desktop(line: string): void {
    write("desktop.log", line);
  },
  agent(line: string): void {
    write("agent.log", line);
  },
  wire(line: string): void {
    write("wire.log", line);
  },
};
