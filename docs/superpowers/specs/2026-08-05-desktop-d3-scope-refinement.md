# Desktop D3 — Scope Refinement: Information Architecture & Interaction Upgrade

> Status: active
> Date: 2026-08-05
> Supersedes: D3.0 "Codex-style Desktop design baseline" (docs/design) for scope decisions
> Status of prior phases: D3.1 (Projects→Threads nav) committed at 84d4cd0 / e3f7de3

## Judgement

D3 does NOT need a large-scale desktop rewrite. It shrinks to an **information
architecture + interaction layer upgrade**. The current UI is not far from
Codex style; the gaps are concentrated in four places: left nav, right
Inspector, task timeline, and Composer details. Resource-monitoring footer and
central topbar are already at or near target and are REMOVED from D3 work.

## Corrected D3 scope

```text
D3.1  Projects → Threads 左侧导航        (DONE — commits e3f7de3, 84d4cd0)
D3.2  按需 Inspector
D3.3  统一 Task Timeline
D3.4  Composer 交互精修
D3.5  视觉统一与体验验收
```

NOT in D3: full React migration, Wire rewrite, RunEngine rewrite, central topbar
rework, new resource monitoring, changes to Thread/Plan/Artifact backend
protocol, full componentization of vanilla DOM.

---

## D3.2 — On-demand Inspector (DONE — see implementation notes below)

### From current model

```text
常驻右栏 + 可拖动 Resizer + 用户主动折叠
```

### To

```text
默认关闭 + 上下文触发 + 可以固定 (pinned)
```

### Unified state

```ts
type InspectorTab =
  | "plan" | "changes" | "files" | "artifacts" | "jobs" | "runtime" | "logs";

type InspectorState = {
  open: boolean;
  pinned: boolean;
  activeTab: InspectorTab;
  selectedResourceId?: string;
};
```

Plan / Artifact / file preview must NOT each maintain their own right-panel
toggle.

### Open rules

| Trigger | Tab |
|---|---|
| Click Plan status | plan |
| Click file change | changes |
| Click Artifact | artifacts |
| Click Slurm Job | jobs |
| Click Local/SSH/Sandbox | runtime |
| Click Tool log | logs |
| Click project file | files |

### Close rules

- `Escape` closes non-pinned Inspector.
- Clicking the same trigger toggles it closed.
- Switching Thread: non-pinned Inspector auto-closes; pinned stays open but
  refreshes to the new Thread's content.
- After close, focus returns to the triggering element.

### Layout

```text
closed:  left 220px + central
open:    left 220px + central + Inspector 360–420px
```

No complex Resizer in D3. Fixed 380px first; 420px on wide windows; cover-style
Drawer on small windows.

### Responsive

```text
window ≥ 1280px  → Inspector pushes central content
window < 1280px  → Inspector overlays on the right
window < 900px   → left bar auto-shrinks or collapses
```

### Acceptance

- [x] Inspector default-closed at startup
- [x] Plan/Artifact/File/Job clicks open the correct tab
- [x] Escape closes
- [x] Focus returns after close
- [x] Pinned state is saved
- [x] 1280×800 main chat width ≥ 680px
- [x] Drawer causes no double horizontal scroll
- [x] Original Project/Sandbox/Log capabilities not lost

### Implementation notes (2026-08-05)

- **Modules**: `inspector-model.ts` (pure reducer + tab ids, unit-tested via
  `scripts/inspector-state.test.mjs`, 9 cases), `InspectorController.ts`
  (vanilla owner: chrome datasets, Escape, pin/close, trigger clicks, focus
  return, persistence, plan/changes/jobs/runtime views), `ThreadStore` gains
  `AppState.inspector` + `setInspector()` (single source of truth for both
  vanilla and React sides).
- **Tabs**: seven spec tabs (plan | changes | files | artifacts | jobs |
  runtime | logs).  Files = former 项目 view (jelly-switch 目录/产物 sub-pane
  removed — artifacts is now its own tab); runtime = former 沙箱 view + new
  status header (backend · alive dot · workdir · target/profile); logs =
  former Log view.  Plan / changes / jobs are new compact views rendered by
  the controller from ThreadStore (plan → `thread.plan`, changes →
  `thread.items[file_change]`, jobs → `thread.activeRun`).
- **Triggers**: timeline `file_change` blocks carry
  `data-inspector-tab="changes"` (+ item id); plan/artifact item attrs are
  pre-wired for D3.3.  Sandbox pill → runtime.  Project pill keeps its
  project-selector behavior and opens Files after selection.  Same-trigger
  click toggles closed; Escape closes non-pinned; focus returns to the
  trigger (re-queried by id because blocks re-render).
- **Thread switch**: store subscription dispatches `threadSwitched` —
  unpinned closes, pinned stays open and refreshes content, stale selection
  dropped.
- **Layout deviation (measured)**: the spec suggested a fixed 380px
  Inspector, but the 1280×800 chat ≥ 680px acceptance, with left 220px + two
  8px gaps, caps the Inspector at 364px at 1280.  Used **360px at
  1280–1535, 420px ≥ 1536** (inside the spec's 360–420 range) → chat =
  684px at 1280×800.  Left pane 232→220 per the D3.2 layout.  The right
  resizer is inert (fixed widths; the resizer element stays only as a grid
  spacer).
- **Responsive**: `< 1280px` → right drawer overlays (absolute, transform
  animation 180ms in / 120ms out, no double scroll); `< 900px` → left
  sidebar auto-collapses to the rail via media query (unless docked away);
  `prefers-reduced-motion` disables transitions.
- **Persistence**: `electromind-desktop-inspector-pinned` +
  `-inspector-last-tab` in localStorage; panel always starts closed.
- **Cmd+R** (was: toggle right panel) now toggles the Inspector via the
  controller.  React `InspectorShell.tsx` is untouched (not mounted; may be
  reused by D3.3 timeline panels).

---

## D3.3 — Unified Task Timeline (data layer DONE — commits 9b30613, 016496f, next)

Problem: main.ts too large (4364 lines), Tool/Plan/Artifact/Approval inserted
different ways, long tasks produce fragmented cards, hard to see "where the
agent is".

### Item types (only first-class)

```ts
type TimelineItem =
  | UserMessageItem | AssistantMessageItem | ActivityGroupItem
  | ApprovalItem | PlanItem | JobItem | ArtifactItem
  | RecoveryItem | ErrorItem;
```

Wire events ≠ UI items. New layer:

```text
Wire Event → ThreadStore → Timeline Projection → Timeline Renderer
```

### Activity Group

Project consecutive ToolCallBegin / ToolResult / CommandResult / FileChange /
ArtifactProduced into an ActivityGroup. Display:

```text
✓ Worked for 42s · 4 actions
  ✓ Read water64.xyz
  ✓ Generated CP2K input
  ✓ Ran input preflight
  ✓ Created validation report
```

### Aggregation boundaries (end current group)

- Assistant final text starts
- Approval Request appears
- Plan Proposed appears
- Job Submitted appears
- Run ends
- Tool fails
- Gap between tool activities exceeds threshold
- Subagent ownership change

### Expand rules

```text
Running    → current Action expanded
Completed  → auto-collapsed
Failed     → failed Action auto-expanded
Cancelled  → reason expanded
```

### Approval

Approval must render inline in the Timeline (target, workdir, risk,
[Deny] [Allow once]) — never requires opening the Inspector.

### Job / Artifact

Job is a first-class object whose status updates the SAME timeline item (no new
cards per state change). Artifact renders as a compact row; click opens
Inspector.

### Architecture constraints

Keep VirtualList; add TimelineProjection; extract renderer from main.ts
gradually; keep Wire Event input compatible; pin projection with tests. NO React
rewrite of the Timeline.

### Acceptance (data layer)

- [x] Consecutive tool calls aggregated (pure projection, tests 1–3)
- [ ] Completed Activity collapses by default (D3.4 visuals)
- [ ] Failed Activity auto-expands (D3.4 visuals)
- [ ] Approval operable inline (D3.4; ApprovalItem projected now)
- [x] Job status updates the same item (projection test 9)
- [x] Artifact click opens Inspector (D3.2 attrs preserved via adapter)
- [x] 5000 items: no visible perf regression (full < 100ms, step < 5ms)
- [x] Thread switch does not leak other threads' events (tests 11/20 + store test)
- [x] Timeline rebuilds from persisted state after resume (store test)

### Implementation notes (2026-08-05)

- **Chain**: Wire Event → ThreadStore (feed hooks) → TimelineProjection
  (pure fold) → `ThreadState.timeline: TimelineItem[]` (single source of
  truth) → `timeline-adapter.ts` → existing MessageRenderer cards.
- **Modules**: `timeline-types.ts` (first-class item union),
  `timeline-projection.ts` (`projectTimeline` full replay +
  `reduceTimeline` incremental, SAME step function — identity test 14),
  `timeline-adapter.ts` (TimelineItem → existing card shapes, visual
  parity by construction), `inspector-model`-style gating:
  `TIMELINE_PROJECTION_V2` (default on; localStorage
  `desktop.timelineProjection="v1"` opts out — remove the dual path
  before release).
- **Store integration**: feeds at appendThreadItem, ToolResult /
  applyDelta in-place mutations, approval/plan/artifact domain state,
  run lifecycle (RunBegin/RunEnd/run/started/run/completed); snapshot
  restore + HistoryReplay rebuild via the same fold.  ToolCallBegin
  items now persist `run_id` so rebuilds bind groups to the same run.
  Wire dedup (event_id/seq) precedes all feeds.
- **Reasoning** is folded into AssistantMessageItem with a
  `reasoning: true` marker (not a first-class TimelineItem — the spec
  union has none) so the adapter can render the existing collapsible
  block.
- **Known limits (documented)**: resolved approvals / finished runs do
  not survive snapshot rebuild (they live only in the live feed and in
  `pendingPermits`); artifact/plan/job/approval one-level items are
  skipped by the adapter until D3.4 (no cards today — parity).  Group
  ids for repeated runs get deterministic `:N` suffixes.
- **Tests**: 21 pure + 10 store + 9 adapter = 40 new cases; full suite
  124 green; D3.2 CDP 22/22 regression passed on the v2 build.

---

## D3.4 — Composer polish (React, exists: mode/model/autonomy)

Codex-style info hierarchy: `＋  Local▾  Plan▾  Ask▾  Model▾  ↑/■`.

- Attachment menu (first version): Add file / artifact / folder context /
  image / skill — hide or disable unsupported entries with a reason.
- Permission copy: "Permissions: Ask" / "Permissions: Auto for this run" —
  never YOLO / lightning icon / bare "Auto". Show a one-time risk note on Auto.
- Status feedback: running → Send becomes Stop; approval → composer stays
  editable but approval card takes priority; disconnected → composer disabled +
  reconnect entry; no model → editable, guide config on send; context near cap →
  text + accessible notice, not just a ring.

### Acceptance

- [ ] Target / mode / permission / model visible at a glance
- [ ] Send switches to Stop while running
- [ ] Permission not conveyed by ambiguous icons
- [ ] Attachment menu keyboard-accessible
- [ ] Input focus survives Timeline updates
- [ ] Errors shown near the Composer
- [ ] Options persist across restarts as expected

---

## D3.5 — Visual unification (tokens, not re-theming)

Freeze tokens:

```css
--space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px; --space-5: 24px;
--radius-sm: 6px; --radius-md: 8px; --radius-lg: 12px;
--text-xs: 12px; --text-sm: 13px; --text-md: 14px; --text-lg: 16px; --text-xl: 20px;
--motion-fast: 120ms; --motion-normal: 180ms; --motion-slow: 240ms;
```

Style: Codex-style, minimal, quiet, task-focused, native-feeling. Avoid: permanent
glass blur, big shadows, nested cards, purple-pink gradients, decorative
animation, mixing Codicons and Lucide at the same level, body text < 12px,
color-only status.

Animation: hover 120–160ms, drawer 180–220ms, modal 180–240ms, exit faster than
enter, transform+opacity only, prefers-reduced-motion support.

## Hybrid architecture strategy

```text
Shared Stores / View Models
        ├── React Islands
        └── Vanilla Views
```

- React and vanilla never touch each other's DOM directly.
- State flows through stores / events / explicit adapters.
- Design tokens shared by both sides.
- Single source of truth for Thread / Inspector / Runtime state.
- New complex interactions become standalone modules, not main.ts additions.

main.ts goal at end of D3: startup / coordination / binding only; sidebar →
ProjectThreadSidebar; Inspector → InspectorController; timeline projection →
TimelineProjection; renderer reuses MessageRenderer / TimelineRenderer; Composer
stays React. Stop main.ts growth (4364 lines today).

## PR order (revised)

1. docs: D3 interaction model (this spec) — baseline, states, acceptance
2. feat(desktop): group threads by project — DONE
3. feat(desktop): make inspector contextual and default-closed — DONE
4. refactor(desktop): typed task timeline projection (data + tests first)
5. feat(desktop): grouped activities + inline approvals
6. feat(desktop): refine task composer controls
7. style(desktop): unify Codex-style tokens and interactions

## Workload & order

| Module | Effort | Risk |
|---|---|---|
| Projects→Threads | M | Low | (DONE) |
| Topbar | S | Low | (out of scope) |
| Inspector default-closed | M | M | (DONE) |
| Timeline Projection | L | High | |
| Activity Group | L | High | |
| Composer | S–M | Low | |
| Visual tokens | M | M | |
| React full migration | — | Extreme | (not doing) |

Order: left nav → Inspector → Timeline data layer → Timeline visual → Composer
→ global visual acceptance. NOT CSS first, NOT main.ts rewrite first.
