/** 验收六：IPC 参数运行时 Schema 校验。
 *
 * ipc-schema.ts 是纯逻辑模块（无 electron 依赖）——bundle 后在 node
 * 里直接测 validateIpcParams 的正反路径；另静态断言 shape 表里每个
 * 通道都注册在 main 进程（防幽灵 shape）。
 */

import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const esbuild = require("esbuild");

let _module = null;

async function getModule() {
  if (_module) return _module;
  const tmpDir = mkdtempSync(join(tmpdir(), "ipc-schema-test-"));
  const outFile = join(tmpDir, "ipc-schema.mjs");
  try {
    await esbuild.build({
      entryPoints: [
        join(import.meta.dirname, "..", "src", "preload", "ipc-schema.ts"),
      ],
      bundle: true,
      outfile: outFile,
      platform: "node",
      format: "esm",
      target: "node20",
      logLevel: "silent",
    });
    _module = await import(outFile);
  } finally {
    rmSync(tmpDir, { recursive: true, force: true });
  }
  return _module;
}

test("validates shaped params: correct types pass", async () => {
  const { validateIpcParams } = await getModule();
  validateIpcParams("desktop:get-thread-meta", ["t1"]);
  validateIpcParams("desktop:set-yolo-mode", [true]);
  validateIpcParams("desktop:send-user-input", ["hello", "req-1", undefined, undefined]);
  validateIpcParams("desktop:send-user-input", ["hello"]);
  validateIpcParams("desktop:pick-directory", []);
  validateIpcParams("desktop:pick-directory", ["/tmp"]);
  validateIpcParams("desktop:permit-tool-call", [{ toolCallId: "tc-1" }]);
});

test("validates shaped params: wrong type rejected", async () => {
  const { validateIpcParams } = await getModule();
  assert.throws(() => validateIpcParams("desktop:get-thread-meta", [42]), /应为 string/);
  assert.throws(() => validateIpcParams("desktop:set-yolo-mode", ["yes"]), /应为 boolean/);
  assert.throws(() => validateIpcParams("desktop:send-user-input", []), /应为 string/);
  assert.throws(() => validateIpcParams("desktop:save-provider-setup", ["x"]), /应为 object/);
});

test("validates shaped params: too many args rejected", async () => {
  const { validateIpcParams } = await getModule();
  assert.throws(
    () => validateIpcParams("desktop:set-yolo-mode", [true, true]),
    /参数过多/,
  );
});

test("unshaped channels are no-arg: extra args rejected", async () => {
  const { validateIpcParams } = await getModule();
  validateIpcParams("desktop:get-app-info", []);
  assert.throws(
    () => validateIpcParams("desktop:get-app-info", ["x"]),
    /未声明参数 shape/,
  );
});

test("optional slots: absent ok, wrong type rejected, excess args rejected", async () => {
  const { validateIpcParams } = await getModule();
  // 可选位缺省 → 通过
  validateIpcParams("desktop:pick-directory", []);
  validateIpcParams("desktop:send-user-input", ["a", "b"]);
  validateIpcParams("desktop:send-user-input", ["a", "b", "c", "d"]);
  // 可选位填错类型 → 拒绝
  assert.throws(() => validateIpcParams("desktop:pick-directory", [7]), /应为 string/);
  assert.throws(
    () => validateIpcParams("desktop:send-user-input", ["a", "b", "c", 9]),
    /应为 string/,
  );
  // 超出 shape 长度 → 拒绝
  assert.throws(() => validateIpcParams("desktop:pick-directory", ["/tmp", 7]), /参数过多/);
});

test("every shaped channel is registered in main (no phantom shapes)", async () => {
  const { IPC_PARAM_SHAPES } = await getModule();
  const main = readFileSync(
    new URL("../src/main/index.ts", import.meta.url),
    "utf8",
  );
  const mainChannels = new Set();
  const re = /ipcMain\.handle\(\s*"([^"]+)"/g;
  let match;
  while ((match = re.exec(main)) !== null) {
    mainChannels.add(match[1]);
  }
  for (const channel of Object.keys(IPC_PARAM_SHAPES)) {
    assert.ok(mainChannels.has(channel), `shape 通道未注册在 main: ${channel}`);
  }
});
