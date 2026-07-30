import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const renderer = readFileSync(
  new URL("../src/renderer/main.ts", import.meta.url),
  "utf8",
);
const css = readFileSync(
  new URL("../src/renderer/style.css", import.meta.url),
  "utf8",
);

// ---------------------------------------------------------------------------
// SkillsState payload normalization
// ---------------------------------------------------------------------------

test("SkillsState handler replaces skillsState in UI state", () => {
  assert.match(
    renderer,
    /event\.method\s*===\s*"SkillsState"/,
    "renderer must handle SkillsState events",
  );
  assert.match(
    renderer,
    /uiState\.skillsState\s*=/,
    "SkillsState must update uiState.skillsState",
  );
});

test("SkillsState ignores stale thread_id", () => {
  assert.match(
    renderer,
    /state\.thread_id\s*&&\s*state\.thread_id\s*===/,
    "SkillsState handler must check thread_id matches active task",
  );
});

test("old Skills method still normalizes to skillsState", () => {
  assert.match(
    renderer,
    /event\.method\s*===\s*"Skills"/,
    "renderer still handles legacy Skills events",
  );
  assert.match(
    renderer,
    /uiState\.skillsState\s*=\s*\{/,
    "legacy Skills must populate skillsState shape",
  );
});

// ---------------------------------------------------------------------------
// SkillsState rendering: sections
// ---------------------------------------------------------------------------

test("renderSkillList emits section labels for available and loaded", () => {
  assert.match(
    renderer,
    /可用/,
    "renderer must label available skills section",
  );
  assert.match(
    renderer,
    /本任务已加载/,
    "renderer must label loaded skills section",
  );
});

test("renderSkillList renders diagnostics when present", () => {
  assert.match(
    renderer,
    /skill-diag/,
    "renderer must support diagnostic items",
  );
  // skill-diag-${d.severity} produces error/warning classes at runtime.
  // In source it appears as a template literal:
  assert.match(
    renderer,
    /skill-diag-\$\{/,
    "renderer must template diagnostic severity into CSS class",
  );
});

test("renderSkillList renders loaded badge", () => {
  assert.match(
    renderer,
    /skill-loaded/,
    "renderer must apply loaded styling to activated skills",
  );
  assert.match(
    renderer,
    /skill-badge/,
    "renderer must show a badge on loaded skills",
  );
});

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

test("empty state shows discovery paths, not only ~/.electromind/skills", () => {
  assert.match(
    renderer,
    /skills\/|\.agents\/skills|\.electromind\/skills/,
    "empty state must list project discovery paths",
  );
  assert.match(
    renderer,
    /SkillsState|skillsState|暂无可用 Skill/,
    "empty state must reference skillsState or have proper message",
  );
});

// ---------------------------------------------------------------------------
// CSS for skill sections
// ---------------------------------------------------------------------------

test("CSS defines skill-section-label", () => {
  assert.match(
    css,
    /\.skill-section-label\s*\{/,
    "CSS must define .skill-section-label for section headings",
  );
});

test("CSS defines skill-loaded and skill-diag states", () => {
  assert.match(
    css,
    /\.skill-item\.skill-loaded\s*\{/,
    "CSS must style loaded skills distinctly",
  );
  assert.match(
    css,
    /\.skill-item\.skill-diag-error\s*\{/,
    "CSS must style error diagnostics with a red border",
  );
});
