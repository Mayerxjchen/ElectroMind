/** P3 /skill 视图纯逻辑测试（spec 2026-08-07 §P3）。
 *
 *  验收：
 *   - Picker 行按名称排序，含 Trusted/Untrusted 与 Built-in/Managed/Project 徽标
 *   - 信任判定 fail-closed（缺 trust_state → Untrusted）
 *   - /skill list 文本每行一个 Skill
 *   - /skill info 文本含 名称/描述/来源/信任/调用/状态/Digest
 */

import { test } from "node:test";
import assert from "node:assert/strict";

const view = await import(
  new URL("../src/renderer/react/skill-view.ts", import.meta.url)
);

const skill = (name, extra = {}) => ({
  name,
  description: `${name} desc`,
  source: `sources/${name}`,
  sha256: "0123456789abcdef",
  status: "available",
  trust_state: "trusted",
  invocation: "both",
  scope: "builtin",
  ...extra,
});

test("skillPickerRows: sorted by name with trust + source badges", () => {
  const rows = view.skillPickerRows([
    skill("zeta", { trust_state: "untrusted" }),
    skill("alpha"),
    skill("beta", { scope: "project" }),
  ]);
  assert.deepEqual(
    rows.map((r) => r.name),
    ["alpha", "beta", "zeta"],
    "按名称排序",
  );
  const alpha = rows.find((r) => r.name === "alpha");
  assert.equal(alpha.trustLabel, "Trusted");
  assert.equal(alpha.sourceLabel, "Built-in");
  assert.equal(alpha.trusted, true);
  const beta = rows.find((r) => r.name === "beta");
  assert.equal(beta.sourceLabel, "Project");
  const zeta = rows.find((r) => r.name === "zeta");
  assert.equal(zeta.trustLabel, "Untrusted");
  assert.equal(zeta.trusted, false);
});

test("skillPickerRows: missing trust_state is Untrusted (fail-closed)", () => {
  const rows = view.skillPickerRows([
    skill("ghost", { trust_state: undefined, status: "loaded" }),
  ]);
  assert.equal(rows[0].trustLabel, "Untrusted");
  assert.equal(rows[0].trusted, false);
});

test("sourceLabel: builtin/project/managed mapping", () => {
  assert.equal(view.sourceLabel("builtin"), "Built-in");
  assert.equal(view.sourceLabel("project"), "Project");
  assert.equal(view.sourceLabel("user"), "Managed");
  assert.equal(view.sourceLabel("admin"), "Managed");
  assert.equal(view.sourceLabel(undefined), "Managed");
});

test("skillListText: one line per skill with trust + source", () => {
  const text = view.skillListText([
    skill("cp2k"),
    skill("demo", { trust_state: "untrusted", scope: "user" }),
  ]);
  assert.equal(
    text,
    "cp2k · Trusted · Built-in\ndemo · Untrusted · Managed",
  );
});

test("skillListText: empty state", () => {
  assert.equal(view.skillListText([]), "未安装任何 Skill");
});

test("skillInfoText: includes name/description/source/trust/invocation/status/digest", () => {
  const text = view.skillInfoText(
    skill("cp2k", { invocation: "manual", trust_state: "untrusted" }),
  );
  assert.match(text, /名称: cp2k/);
  assert.match(text, /描述: cp2k desc/);
  assert.match(text, /来源: sources\/cp2k \(Built-in\)/);
  assert.match(text, /信任: Untrusted/);
  assert.match(text, /调用: manual/);
  assert.match(text, /状态: available/);
  assert.match(text, /Digest: 0123456789abcdef/);
});

// ── /skill doctor ───────────────────────────────────────────────────

test("skillDoctorText: empty catalog", () => {
  assert.equal(view.skillDoctorText([]), "Skills 目录为空");
});

test("skillDoctorText: healthy catalog counts trusted/untrusted", () => {
  const text = view.skillDoctorText([
    skill("cp2k"),
    skill("demo", { trust_state: "untrusted" }),
  ]);
  assert.match(text, /Skills 2 · Trusted 1 · Untrusted 1/);
  assert.doesNotMatch(text, /⚠/, "健康目录无告警");
  assert.doesNotMatch(text, /ℹ/, "无 model-only 明细");
});

test("skillDoctorText: missing trust_state flagged as fail-closed", () => {
  const text = view.skillDoctorText([
    skill("cp2k"),
    skill("ghost", { trust_state: undefined }),
  ]);
  assert.match(text, /1 个缺少 trust_state/);
  assert.match(text, /ghost/);
});

test("skillDoctorText: duplicate names flagged", () => {
  const text = view.skillDoctorText([skill("dup"), skill("dup")]);
  assert.match(text, /重复名称: dup/);
});

test("skillDoctorText: model-only detail listed", () => {
  const text = view.skillDoctorText([
    skill("cp2k"),
    skill("auto", { invocation: "model" }),
  ]);
  assert.match(text, /1 个仅模型可调用: auto/);
});
