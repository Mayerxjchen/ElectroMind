/** P5.1/P5.2: 打包时 Agent 二进制强制校验。
 *
 * - detectAgentArch 能识别本机 arm64 / x64 二进制（Mach-O CIGAM 兼容）。
 * - embedAgent 找不到 Agent 时默认抛错（禁止静默降级 Companion），
 *   显式 --allow-companion 才放行。
 *
 * 自包含：样例二进制用 process.execPath（node 本体，真实 Mach-O），
 * 发现目录用临时 dir（不依赖仓库根 dist/ 或 .venv 等环境残留）。
 */

import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { copyFileSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { test } from "node:test";

const require = createRequire(import.meta.url);

// package.js 用 CJS；node 本体是真实 Mach-O（macOS）或 ELF（Linux）。
const { detectAgentArch, embedAgent } = require("../scripts/package.js");

const SAMPLE_BIN = process.execPath;

// 合成最小 Mach-O 头（MH_MAGIC_64 + cputype），架构检测不依赖机器上
// 同时存在 arm64/x64 二进制，任何 Runner 上都可复现。
const MH_MAGIC_64 = 0xfeedfacf;
const CPU_ARM64 = 0x0100000c;
const CPU_X86_64 = 0x01000007;

function syntheticMachO(cputype) {
  const buf = Buffer.alloc(8);
  buf.writeUInt32LE(MH_MAGIC_64, 0);
  buf.writeInt32LE(cputype, 4);
  return buf;
}

test("detectAgentArch recognizes a real binary", () => {
  const arch = detectAgentArch(SAMPLE_BIN);
  assert.ok(arch === "arm64" || arch === "x64", `unexpected arch ${arch}`);
});

test("detectAgentArch reads synthetic Mach-O cputype", () => {
  const tmpDir = mkdtempSync(join(tmpdir(), "agent-synth-"));
  try {
    const arm = join(tmpDir, "arm-bin");
    const x64 = join(tmpDir, "x64-bin");
    require("node:fs").writeFileSync(arm, syntheticMachO(CPU_ARM64));
    require("node:fs").writeFileSync(x64, syntheticMachO(CPU_X86_64));
    assert.equal(detectAgentArch(arm), "arm64");
    assert.equal(detectAgentArch(x64), "x64");
  } finally {
    rmSync(tmpDir, { recursive: true, force: true });
  }
});

test("detectAgentArch returns null for a non-binary file", () => {
  assert.equal(detectAgentArch("package.json"), null);
});

test("embedAgent throws when no agent and not allow-companion", () => {
  const tmpDir = mkdtempSync(join(tmpdir(), "agent-missing-"));
  try {
    const appDir = join(tmpDir, "app");
    const emptyDist = join(tmpDir, "empty-dist");
    mkdirSync(emptyDist, { recursive: true });
    assert.throws(
      () => embedAgent(appDir, "", false, emptyDist),
      /P5\.2|禁止静默降级/,
    );
  } finally {
    rmSync(tmpDir, { recursive: true, force: true });
  }
});

test("embedAgent allows companion when explicitly requested", () => {
  const tmpDir = mkdtempSync(join(tmpdir(), "agent-comp-"));
  try {
    const appDir = join(tmpDir, "app");
    const emptyDist = join(tmpDir, "empty-dist");
    mkdirSync(emptyDist, { recursive: true });
    const ok = embedAgent(appDir, "", true, emptyDist);
    assert.equal(ok, false); // Companion 包，不嵌入
  } finally {
    rmSync(tmpDir, { recursive: true, force: true });
  }
});

test("embedAgent embeds an explicit agent binary", () => {
  const tmpDir = mkdtempSync(join(tmpdir(), "agent-embed-"));
  try {
    const appDir = join(tmpDir, "app");
    // 假 agent：可执行脚本，`version` 子命令输出与 Desktop 一致的版本号
    // （嵌入后 package.js 会真实执行它做版本校验）。
    const desktopVersion = JSON.parse(
      require("node:fs").readFileSync(join(import.meta.dirname, "..", "package.json"), "utf8"),
    ).version;
    const agentSrc = join(tmpDir, "agent-bin");
    require("node:fs").writeFileSync(
      agentSrc,
      `#!/bin/sh\necho "${desktopVersion}"\n`,
    );
    require("node:fs").chmodSync(agentSrc, 0o755);
    const ok = embedAgent(appDir, agentSrc, false);
    assert.equal(ok, true);
    // .app bundle 路径：appDir/<productName>.app/Contents/Resources/agent/electromind
    const embedded = join(appDir, "electromind Desktop.app", "Contents", "Resources", "agent", "electromind");
    assert.ok(require("node:fs").existsSync(embedded), "agent 应被嵌入");
    // 验收八：嵌入时写出 agent.sha256 清单
    assert.ok(
      require("node:fs").existsSync(join(embedded, "..", "agent.sha256")),
      "应生成 agent.sha256",
    );
  } finally {
    rmSync(tmpDir, { recursive: true, force: true });
  }
});

test("embedAgent throws on arch mismatch", () => {
  const tmpDir = mkdtempSync(join(tmpdir(), "agent-arch-"));
  try {
    const appDir = join(tmpDir, "app");
    // 合成与打包架构相反 cputype 的 Mach-O → 必然触发架构不匹配
    const opposite = process.arch === "arm64" ? CPU_X86_64 : CPU_ARM64;
    const agentSrc = join(tmpDir, "agent-bin");
    require("node:fs").writeFileSync(agentSrc, syntheticMachO(opposite));
    assert.throws(() => embedAgent(appDir, agentSrc, false), /架构/);
  } finally {
    rmSync(tmpDir, { recursive: true, force: true });
  }
});

test("embedAgent rejects explicit missing binary", () => {
  const tmpDir = mkdtempSync(join(tmpdir(), "agent-missingbin-"));
  try {
    const appDir = join(tmpDir, "app");
    assert.throws(
      () => embedAgent(appDir, join(tmpDir, "missing-bin"), false),
      /不存在/,
    );
  } finally {
    rmSync(tmpDir, { recursive: true, force: true });
  }
});
