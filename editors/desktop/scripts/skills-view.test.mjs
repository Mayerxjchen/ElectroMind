/** 七: Skills Manager —— 纯视图逻辑单元测试（skills-view.ts）。
 *
 * 覆盖：操作按钮推导（builtin 不可管理 / trusted→撤销）、busy 禁用、
 * reducer 状态迁移、HTML 转义。
 */

import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const esbuild = require("esbuild");

let _module = null;

async function getModule() {
  if (_module) return _module;
  const tmpDir = mkdtempSync(join(tmpdir(), "skills-view-test-"));
  const outFile = join(tmpDir, "skills-view.mjs");
  try {
    await esbuild.build({
      entryPoints: [
        join(import.meta.dirname, "..", "src", "renderer", "skills-view.ts"),
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

const UNTRUSTED = {
  name: "demo-skill",
  skill_id: "demo-skill",
  scope: "user",
  trust_state: "untrusted",
};
const TRUSTED = { ...UNTRUSTED, trust_state: "trusted" };
const BUILTIN = { name: "cp2k", scope: "builtin", trust_state: "trusted" };

test("untrusted managed skill shows trust/update/remove", async () => {
  const { getSkillActions } = await getModule();
  assert.deepEqual(getSkillActions(UNTRUSTED), ["trust", "update", "remove"]);
});

test("trusted skill shows revoke instead of trust", async () => {
  const { getSkillActions } = await getModule();
  assert.deepEqual(getSkillActions(TRUSTED), ["revoke", "update", "remove"]);
});

test("builtin skill has no management actions", async () => {
  const { getSkillActions } = await getModule();
  assert.deepEqual(getSkillActions(BUILTIN), []);
});

test("renderSkillActions: busy disables buttons with 操作中 label", async () => {
  const { renderSkillActions } = await getModule();
  const html = renderSkillActions(UNTRUSTED, new Set(["demo-skill"]));
  assert.match(html, /disabled/);
  assert.match(html, /操作中…/);
  assert.doesNotMatch(html, />信任</);
});

test("renderSkillActions: idle shows labels; remove is danger", async () => {
  const { renderSkillActions } = await getModule();
  const html = renderSkillActions(TRUSTED, new Set());
  assert.match(html, /撤销信任/);
  assert.match(html, /skill-action-danger/);
  assert.match(html, /data-trusted="1"/);
});

test("renderSkillRows escapes skill content", async () => {
  const { renderSkillRows } = await getModule();
  const html = renderSkillRows(
    [{ name: 'evil"<x>', description: "<script>alert(1)</script>", scope: "user" }],
    new Set(),
  );
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});

test("reduceSkillsAction: begin → busy; end ok → cleared + result", async () => {
  const { initialSkillsPanelState, reduceSkillsAction } = await getModule();
  const s0 = initialSkillsPanelState();
  const s1 = reduceSkillsAction(s0, { type: "begin", name: "demo-skill" });
  assert.ok(s1.busy.has("demo-skill"));
  const s2 = reduceSkillsAction(s1, {
    type: "end",
    name: "demo-skill",
    ok: true,
    result: "已安装",
  });
  assert.equal(s2.busy.size, 0);
  assert.equal(s2.lastResult, "已安装");
  assert.equal(s2.lastError, null);
});

test("reduceSkillsAction: end fail → busy cleared + error", async () => {
  const { initialSkillsPanelState, reduceSkillsAction } = await getModule();
  const s1 = reduceSkillsAction(initialSkillsPanelState(), {
    type: "begin",
    name: "demo-skill",
  });
  const s2 = reduceSkillsAction(s1, {
    type: "end",
    name: "demo-skill",
    ok: false,
    error: "skills/install 失败: boom",
  });
  assert.equal(s2.busy.size, 0);
  assert.match(s2.lastError ?? "", /skills\/install 失败/);
});
