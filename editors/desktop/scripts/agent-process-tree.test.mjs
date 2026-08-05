/** P4.1: AgentBridge 关闭时终止完整进程树，避免孤立进程。
 *
 * 启动一个 spawn 出孙进程的 wire 桩（sh -c 再 fork 一个 sleep），
 * 断言 stop() 后孙进程也被杀（进程组整体终止）。
 */

import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const esbuild = require("esbuild");

const MODULE_PATH = join(import.meta.dirname, "..", "src", "shared", "agent.ts");

let _module = null;

async function getModule() {
  if (_module) return _module;
  const tmpDir = mkdtempSync(join(tmpdir(), "agent-tree-test-"));
  const outFile = join(tmpDir, "agent.mjs");
  try {
    await esbuild.build({
      entryPoints: [MODULE_PATH],
      bundle: true,
      outfile: outFile,
      platform: "node",
      format: "esm",
      target: "node20",
      logLevel: "silent",
      absWorkingDir: join(import.meta.dirname, ".."),
    });
    _module = await import(outFile);
  } finally {
    rmSync(tmpDir, { recursive: true, force: true });
  }
  return _module;
}

test("AgentBridge.stop() kills the whole process tree (no orphan)", async () => {
  const { AgentBridge } = await getModule();
  // 桩命令写进临时文件（避免 -e 引号嵌套）：打印 READY + 派生 sleep 60，
  // 孙进程在同一个进程组里。
  const tmpDir = mkdtempSync(join(tmpdir(), "agent-tree-stub-"));
  const stubPath = join(tmpDir, "stub.cjs");
  writeFileSync(
    stubPath,
    "const {spawn}=require('child_process');" +
      "const c=spawn('sleep',['60'],{detached:false});" +
      "console.log('READY '+c.pid);" +
      "process.on('exit',()=>{try{c.kill()}catch{}});",
  );
  const collected = [];
  const errors = [];
  const bridge = new AgentBridge({
    command: "node",
    args: [stubPath],
    cwd: undefined,
    onLine: (line) => collected.push(line),
    onStderr: (text) => errors.push(text),
    onExit: () => {},
    onError: (e) => errors.push(String(e)),
  });
  bridge.start();

  // 等 READY 行出现（子进程已派生）
  await new Promise((resolve) => {
    const start = Date.now();
    const timer = setInterval(() => {
      if (collected.some((l) => l.startsWith("READY"))) {
        clearInterval(timer);
        resolve();
      } else if (Date.now() - start > 5000) {
        clearInterval(timer);
        resolve();
      }
    }, 25);
  });

  const ready = collected.find((l) => l.startsWith("READY"));
  assert.ok(ready, `stub 应打印 READY（含孙进程 pid）; lines=${JSON.stringify(collected)} err=${JSON.stringify(errors)}`);
  const grandchildPid = Number(ready.split(" ")[1]);
  assert.ok(Number.isInteger(grandchildPid) && grandchildPid > 0);

  // stop → 整组终止
  bridge.stop();
  await bridge.whenExited().catch(() => {});

  // 等 OS 回收
  await new Promise((r) => setTimeout(r, 200));
  let alive = true;
  try {
    execFileSync("kill", ["-0", String(grandchildPid)], { stdio: "ignore" });
  } catch {
    alive = false;
  }
  assert.equal(alive, false, "孙进程（sleep）应在 AgentBridge 关闭后退出，无孤立进程");
});
