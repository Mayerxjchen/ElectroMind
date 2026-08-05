/** D3.4 composer permission-copy tests.
 *
 *  Spec: "Permissions: Ask" / "Permissions: Auto for this run" — never a
 *  bare "Auto", never an ambiguous YOLO/lightning icon; one-time risk
 *  note on auto-approved runs.  The copy lives in a pure module (no React,
 *  since node --test strips .ts but not .tsx) so it is fully unit-tested.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

// Mutable localStorage stub — lets tests exercise the dismissal round-trip.
let stored = null;
globalThis.window = {
  localStorage: {
    getItem: (key) => (key === "electromind-permission-risk-dismissed" ? stored : null),
    setItem: (_key, value) => {
      stored = value;
    },
  },
};

const m = await import(
  new URL("../src/renderer/react/composer-permissions.ts", import.meta.url)
);

test("permissionText maps every autonomy level to an explicit phrase", () => {
  assert.equal(m.permissionText("prompt"), "Permissions: Ask");
  assert.equal(m.permissionText("auto-safe"), "Permissions: Auto for this run");
  assert.equal(m.permissionText("full-access"), "Permissions: Full access");
});

test("permissionText never returns a bare level name or an empty string", () => {
  for (const level of ["prompt", "auto-safe", "full-access"]) {
    const text = m.permissionText(level);
    assert.ok(text.length > 0, `${level} → non-empty`);
    // Never just the raw level ("Auto", "Full access" alone, "Prompt").
    assert.ok(!/^auto-safe$/i.test(text), `${level} → not bare level`);
    assert.ok(/^Permissions:/i.test(text), `${level} → explicit "Permissions:" prefix`);
  }
});

test("unknown future levels fall back to Ask, not to a bare Auto", () => {
  assert.equal(m.permissionText("whatever-future-level"), "Permissions: Ask");
});

test("only auto-approved levels are risky (need the risk note)", () => {
  assert.equal(m.autonomyIsRisky("prompt"), false);
  assert.equal(m.autonomyIsRisky("auto-safe"), true);
  assert.equal(m.autonomyIsRisky("full-access"), true);
  assert.equal(m.autonomyIsRisky("unknown"), false);
});

test("every risky level has risk-note copy", () => {
  assert.ok(m.riskNoteText("auto-safe").length > 0);
  assert.ok(m.riskNoteText("full-access").length > 0);
});

test("dismissal round-trips through localStorage", () => {
  stored = null;
  assert.equal(m.isRiskDismissed(), false);
  m.markRiskDismissed();
  assert.equal(m.isRiskDismissed(), true);
  assert.equal(stored, "1");
});

test("guarded when localStorage is blocked", () => {
  const origWindow = globalThis.window;
  globalThis.window = {
    localStorage: {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    },
  };
  try {
    assert.equal(m.isRiskDismissed(), false, "getItem throw → treated as not dismissed");
    assert.doesNotThrow(() => m.markRiskDismissed(), "setItem throw → best-effort, no crash");
  } finally {
    globalThis.window = origWindow;
  }
});
