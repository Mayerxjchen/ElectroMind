/** P3 Auto Model —— ModelSelection ↔ policy 字符串 / 展示标签。 */

import { test } from "node:test";
import assert from "node:assert/strict";

const m = await import(
  new URL("../src/renderer/react/model-policy.ts", import.meta.url)
);
const { modelPolicyString, modelSelectionFromPolicy, modelPolicyLabel } = m;

test("policy string: selection → wire value", () => {
  assert.equal(modelPolicyString({ kind: "auto" }), "auto");
  assert.equal(modelPolicyString({ kind: "profile", profile: "fast" }), "fast");
  assert.equal(modelPolicyString({ kind: "profile", profile: "balanced" }), "balanced");
  assert.equal(modelPolicyString({ kind: "profile", profile: "best" }), "best");
  assert.equal(modelPolicyString({ kind: "hybrid", profile: "plan-execute" }), "plan-execute");
  assert.equal(modelPolicyString({ kind: "named", modelId: "deepseek-v4-pro" }), "deepseek-v4-pro");
  assert.equal(modelPolicyString(null), "auto");
  assert.equal(modelPolicyString(undefined), "auto");
});

test("policy string: wire value → selection (round-trip)", () => {
  for (const policy of ["auto", "fast", "balanced", "best", "plan-execute", "deepseek-v4-pro"]) {
    const sel = modelSelectionFromPolicy(policy);
    assert.equal(modelPolicyString(sel), policy, `round-trip ${policy}`);
  }
  // 未知串按 named 处理（与后端 parse_model_policy 一致）
  assert.deepEqual(modelSelectionFromPolicy("custom-x"), { kind: "named", modelId: "custom-x" });
});

test("label: 文档展示格式", () => {
  assert.equal(modelPolicyLabel({ kind: "auto" }), "Auto");
  assert.equal(modelPolicyLabel({ kind: "profile", profile: "best" }), "Best");
  assert.equal(modelPolicyLabel({ kind: "hybrid", profile: "plan-execute" }), "Plan→Execute");
  assert.equal(modelPolicyLabel({ kind: "named", modelId: "deepseek-v4-pro" }), "deepseek-v4-pro");
  assert.equal(modelPolicyLabel(null), "Auto");
});
