/**
 * 原子写（P1.2）：临时文件 + fsync + rename，崩溃不留下半写 JSON。
 * 覆盖前把当前文件复制为 `<name>.bak`（上一个完好版本，P1.3 恢复用）。
 */
import { closeSync, copyFileSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, renameSync, writeSync } from "node:fs";
import path from "node:path";

export function atomicWriteJsonFile(filePath: string, value: unknown): void {
  const target = path.resolve(filePath);
  mkdirSync(path.dirname(target), { recursive: true });

  // 覆盖前保留上一个完好版本
  if (existsSync(target)) {
    try {
      copyFileSync(target, `${target}.bak`);
    } catch {
      // 备份失败不阻断写
    }
  }

  const tmpPath = `${target}.${process.pid}.${Date.now()}.tmp`;
  const fd = openSync(tmpPath, "w");
  try {
    const payload = `${JSON.stringify(value, null, 2)}\n`;
    writeSync(fd, payload);
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
  renameSync(tmpPath, target);
}

export function readJsonLoose<T>(filePath: string): T | undefined {
  try {
    const raw = readFileSync(filePath, "utf8");
    return JSON.parse(raw) as T;
  } catch {
    return undefined;
  }
}
