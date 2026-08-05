/** P2.1: TS 科学文件 Parser 只用于快速预览 — 解析出的结果必须标"未验证"。
 *
 * 编译纯 TS 模块 (SciFileRecognizer.ts) 并断言：
 *   - cp2k_output / lammps_thermo / deepmd_curve / vasp_oszicar 结果
 *     summary.unverified === true
 *   - 纯文本 / 二进制不标未验证
 */

import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const esbuild = require("esbuild");

const MODULE_PATH = join(import.meta.dirname, "..", "src", "renderer", "parsers", "SciFileRecognizer.ts");

let _module = null;

async function getModule() {
  if (_module) return _module;
  const tmpDir = mkdtempSync(join(tmpdir(), "parser-unverified-test-"));
  const outFile = join(tmpDir, "recognizer.mjs");
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

test("cp2k_output summary is marked unverified", async () => {
  const mod = await getModule();
  const cp2kOut = "ENERGY| Total FORCE_EVAL ( QS ) energy (a.u.): -76.403173\n";
  const summary = mod.recognizeSciFile("run-1.out", cp2kOut, cp2kOut.length);
  assert.equal(summary.kind, "cp2k_output");
  assert.equal(summary.unverified, true);
});

test("lammps / deepmd / vasp parser kinds are marked unverified", async () => {
  const mod = await getModule();
  const lammps = "LAMMPS (29 Sep 2021)\n";
  const deepmd = "# step  loss  l2_energy\n0 0.1 0.2\n";
  const vasp = "  1 F= -.17123456E+02 E0= -.17123456E+02\n";
  assert.equal(mod.recognizeSciFile("log.lammps", lammps, lammps.length).unverified, true);
  assert.equal(mod.recognizeSciFile("lcurve.out", deepmd, deepmd.length).unverified, true);
  assert.equal(mod.recognizeSciFile("OSZICAR", vasp, vasp.length).unverified, true);
});

test("generic text and binary are not marked unverified", async () => {
  const mod = await getModule();
  const text = "hello world\n";
  assert.equal(mod.recognizeSciFile("note.txt", text, text.length).unverified, false);
  const bin = "\x00\x01\x02binary";
  assert.equal(mod.recognizeSciFile("data.bin", bin, bin.length).unverified, false);
});
