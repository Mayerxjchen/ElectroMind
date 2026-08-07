/** P0 Feature Flags 解析测试（spec 2026-08-07 §2）。
 *
 *  验收：
 *   - 缺省/非对象 → 全部回落默认值（fail-closed，默认 = 当前稳定桌面行为）
 *   - 部分覆盖：只写部分字段，其余回落默认
 *   - 非法类型（非 boolean）→ 该字段回落默认，不抛错
 *   - 未知字段忽略
 *   - 结果对象始终含且仅含 5 个 flag 键
 */

import { test } from "node:test";
import assert from "node:assert/strict";

const features = await import(
  new URL("../src/shared/features.ts", import.meta.url)
);

const KEYS = [
  "shell_v2",
  "compact_composer",
  "slash_skill_v2",
  "auto_model_v2",
  "legacy_skills_panel",
];

test("parseFeatures: defaults when missing / non-object", () => {
  for (const raw of [undefined, null, 42, "features", [], true]) {
    const out = features.parseFeatures(raw);
    assert.deepEqual(out, features.DEFAULT_FEATURES, `raw=${String(raw)}`);
  }
});

test("parseFeatures: defaults match current stable desktop behavior", () => {
  // 全部新功能默认关闭；旧 Skills 面板默认开启。
  assert.deepEqual(features.DEFAULT_FEATURES, {
    shell_v2: false,
    compact_composer: false,
    slash_skill_v2: false,
    auto_model_v2: false,
    legacy_skills_panel: true,
  });
});

test("parseFeatures: partial override keeps defaults for the rest", () => {
  const out = features.parseFeatures({ compact_composer: true });
  assert.equal(out.compact_composer, true);
  assert.equal(out.shell_v2, false);
  assert.equal(out.legacy_skills_panel, true);
});

test("parseFeatures: non-boolean values fail closed to defaults", () => {
  const out = features.parseFeatures({
    shell_v2: "yes",
    compact_composer: 1,
    slash_skill_v2: null,
    auto_model_v2: {},
    legacy_skills_panel: "false",
  });
  assert.deepEqual(out, features.DEFAULT_FEATURES);
});

test("parseFeatures: full override honored", () => {
  const out = features.parseFeatures({
    shell_v2: true,
    compact_composer: true,
    slash_skill_v2: true,
    auto_model_v2: true,
    legacy_skills_panel: false,
  });
  assert.deepEqual(out, {
    shell_v2: true,
    compact_composer: true,
    slash_skill_v2: true,
    auto_model_v2: true,
    legacy_skills_panel: false,
  });
});

test("parseFeatures: unknown keys ignored, result has exactly 5 keys", () => {
  const out = features.parseFeatures({ shell_v2: true, mystery: true });
  assert.deepEqual(Object.keys(out).sort(), [...KEYS].sort());
  assert.equal(out.mystery, undefined);
});

test("parseFeatures: return object is a fresh copy (no shared mutation)", () => {
  const a = features.parseFeatures({ legacy_skills_panel: false });
  const b = features.parseFeatures({});
  assert.equal(a.legacy_skills_panel, false);
  assert.equal(b.legacy_skills_panel, true);
  assert.notEqual(a, b);
});
