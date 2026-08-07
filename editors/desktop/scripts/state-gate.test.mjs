/** P2 统一状态门测试 —— 状态优先级 + 等待审批时的命令门（spec 2026-08-07 §P2）。
 *
 *  验收：
 *   - 单一状态推导：disconnected > waiting_approval > running > idle
 *   - waiting_approval 时只放行 /status /logs /stop /allow /deny；
 *     execute() 与 isAvailable() 被同一道门约束
 *   - /allow /deny 经 permitToolCall / denyToolCall（不绕过权限模式）
 *   - /help --all 在 Palette 展示全部命令（含未接线项）
 */

import { test } from "node:test";
import assert from "node:assert/strict";

const {
  computeCompositeState,
  statePriority,
  approvalGate,
  APPROVAL_OK_COMMANDS,
} = await import(
  new URL("../src/renderer/react/state.ts", import.meta.url)
);
const {
  CommandRegistry,
  getCommandRegistry,
  resetCommandRegistry,
} = await import(
  new URL("../src/renderer/react/command-registry.ts", import.meta.url)
);
const { registerCoreCommands } = await import(
  new URL("../src/renderer/react/commands.ts", import.meta.url)
);
const { tokensToArgs } = await import(
  new URL("../src/renderer/react/slash-candidates.ts", import.meta.url)
);
const { __seedDesktopFeaturesForTest } = await import(
  new URL("../src/renderer/features.ts", import.meta.url)
);

// ── 纯状态逻辑 ───────────────────────────────────────────────────────

test("state: priority order is disconnected > waiting_approval > running > idle", () => {
  const order = [
    statePriority("disconnected"),
    statePriority("waiting_approval"),
    statePriority("running"),
    statePriority("idle"),
  ];
  assert.deepEqual(order, [4, 3, 2, 1], "优先级数值必须严格递减");
});

test("state: computeCompositeState follows priority, not input order", () => {
  // 无桥接 → 断开（压倒一切）
  assert.equal(
    computeCompositeState({ bridgeActive: false, running: true, pendingApproval: true }),
    "disconnected",
  );
  // 待审批压倒 running
  assert.equal(
    computeCompositeState({ bridgeActive: true, running: true, pendingApproval: true }),
    "waiting_approval",
  );
  assert.equal(
    computeCompositeState({ bridgeActive: true, running: false, pendingApproval: true }),
    "waiting_approval",
  );
  assert.equal(
    computeCompositeState({ bridgeActive: true, running: true, pendingApproval: false }),
    "running",
  );
  assert.equal(
    computeCompositeState({ bridgeActive: true, running: false, pendingApproval: false }),
    "idle",
  );
});

test("state: APPROVAL_OK_COMMANDS matches the spec set", () => {
  assert.deepEqual(
    [...APPROVAL_OK_COMMANDS].sort(),
    ["logs.open", "run.allow", "run.deny", "run.stop", "status.show"],
  );
});

test("state: approvalGate only restricts in waiting_approval", () => {
  const idleCtx = {
    store: {
      getState: () => ({ bridgeActive: true, activityState: "sleeping" }),
      getActiveThreadId: () => "t1",
      getThread: () => ({ status: "idle", pendingPermits: [] }),
    },
  };
  const gate = approvalGate(idleCtx);
  assert.equal(gate("agent.ask"), true, "idle 全放行");
  assert.equal(gate("thread.new"), true);
  assert.equal(gate("help"), true);
});

// ── 状态门经 Registry 生效 ───────────────────────────────────────────

/** 构造带待审批信号的 store stub。 */
function approvalStore({ pending = 0, status = "running", bridgeActive = true } = {}) {
  return {
    getState: () => ({ bridgeActive, activityState: pending ? "running" : "sleeping" }),
    getActiveThreadId: () => "t1",
    getThread: () => ({
      status,
      pendingPermits: Array.from({ length: pending }, (_, i) => ({
        toolCallId: `tc-${i}`,
        approvalId: "ap-1",
        toolName: "run_command",
        arguments: "{}",
        threadId: "t1",
        runId: "r1",
        timestamp: i,
      })),
    }),
    updateThread: () => {},
    setInspector: () => {},
  };
}

function approvalWindow(spies = {}) {
  const events = [];
  const win = {
    dispatchEvent: (e) => events.push({ type: e.type, detail: e.detail }),
    desktop: {
      openLogDir: () => {},
      sendWireCommand: () => {},
      permitToolCall: (...args) => spies.permit?.push(args),
      denyToolCall: (...args) => spies.deny?.push(args),
    },
  };
  return { win, events };
}

test("gate: waiting_approval restricts registry to APPROVAL_OK_COMMANDS", async () => {
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const ctx = { store: approvalStore({ pending: 1 }) };
  const prevWindow = globalThis.window;
  globalThis.window = approvalWindow().win;
  try {
    // 放行集
    for (const id of ["status.show", "run.stop", "run.allow", "run.deny"]) {
      assert.equal(reg.isAvailable(id, ctx), true, `${id} 等待审批时可用`);
    }
    // 阻断集（其余全部）
    for (const id of ["agent.ask", "mode.cycle", "thread.new", "model.set", "permissions.set", "skills.open", "help"]) {
      assert.equal(reg.isAvailable(id, ctx), false, `${id} 等待审批时被门拦下`);
    }
    // execute() 同样被拦（不只在 UI 层过滤）
    const res = await reg.execute("agent.ask", ctx, { text: "x" });
    assert.equal(res.ok, false);
    assert.match(res.error, /命令当前不可用/);
  } finally {
    globalThis.window = prevWindow;
  }
  resetCommandRegistry();
});

test("gate: logs.open allowed while waiting_approval (openLogDir present)", async () => {
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const ctx = { store: approvalStore({ pending: 1 }) };
  const prevWindow = globalThis.window;
  globalThis.window = approvalWindow().win;
  try {
    assert.equal(reg.isAvailable("logs.open", ctx), true);
  } finally {
    globalThis.window = prevWindow;
  }
  resetCommandRegistry();
});

test("gate: non-waiting states fully open", async () => {
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const prevWindow = globalThis.window;
  globalThis.window = approvalWindow().win;
  try {
    const idleCtx = { store: approvalStore({ pending: 0, status: "idle" }) };
    for (const id of ["agent.ask", "mode.cycle", "thread.new", "model.set", "status.show", "help"]) {
      assert.equal(reg.isAvailable(id, idleCtx), true, `${id} idle 可用`);
    }
  } finally {
    globalThis.window = prevWindow;
  }
  resetCommandRegistry();
});

// ── /allow /deny 命令 ────────────────────────────────────────────────

test("allow/deny: /allow permits the head pending permit", async () => {
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const spies = { permit: [], deny: [] };
  const prevWindow = globalThis.window;
  globalThis.window = approvalWindow(spies).win;
  try {
    const ctx = { store: approvalStore({ pending: 2 }) };
    assert.equal(reg.isAvailable("run.allow", ctx), true);
    const res = await reg.execute("run.allow", ctx, {});
    assert.equal(res.ok, true);
    assert.match(res.message, /已批准/);
    assert.equal(spies.permit.length, 1, "permitToolCall 恰好一次");
    assert.deepEqual(
      spies.permit[0],
      ["tc-0", "ap-1", "t1", "r1"],
      "permit(toolCallId, approvalId, threadId, runId)",
    );
  } finally {
    globalThis.window = prevWindow;
  }
  resetCommandRegistry();
});

test("allow/deny: /deny passes optional reason", async () => {
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const spies = { permit: [], deny: [] };
  const prevWindow = globalThis.window;
  globalThis.window = approvalWindow(spies).win;
  try {
    const ctx = { store: approvalStore({ pending: 1 }) };
    const res = await reg.execute("run.deny", ctx, { reason: "风险过高" });
    assert.equal(res.ok, true);
    assert.equal(spies.deny.length, 1);
    assert.deepEqual(
      spies.deny[0],
      ["tc-0", "风险过高", "ap-1", "t1", "r1"],
      "deny(toolCallId, reason, approvalId, threadId, runId)",
    );
  } finally {
    globalThis.window = prevWindow;
  }
  resetCommandRegistry();
});

test("allow/deny: no pending permit → command unavailable", async () => {
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const prevWindow = globalThis.window;
  globalThis.window = approvalWindow().win;
  try {
    const ctx = { store: approvalStore({ pending: 0, status: "idle" }) };
    assert.equal(reg.isAvailable("run.allow", ctx), false);
    assert.equal(reg.isAvailable("run.deny", ctx), false);
    const res = await reg.execute("run.deny", ctx, {});
    assert.equal(res.ok, false);
    assert.match(res.error, /命令当前不可用/);
  } finally {
    globalThis.window = prevWindow;
  }
  resetCommandRegistry();
});

// ── /help --all ──────────────────────────────────────────────────────

test("help: /help --all opens palette in unimplemented mode", async () => {
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const events = [];
  const prevWindow = globalThis.window;
  globalThis.window = {
    dispatchEvent: (e) => events.push({ type: e.type, detail: e.detail }),
    desktop: {},
  };
  try {
    const ctx = { store: approvalStore({ pending: 0 }) };
    const res = await reg.execute("help", ctx, { all: true });
    assert.equal(res.ok, true);
    assert.ok(
      events.some((e) => e.type === "electromind:palette-toggle-all"),
      "/help --all 应派发 palette-toggle-all",
    );
    assert.ok(
      !events.some((e) => e.type === "electromind:open-shortcuts"),
    );
  } finally {
    globalThis.window = prevWindow;
  }
  resetCommandRegistry();
});

test("help: plain /help opens the shortcuts panel", async () => {
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const events = [];
  const prevWindow = globalThis.window;
  globalThis.window = {
    dispatchEvent: (e) => events.push({ type: e.type, detail: e.detail }),
    desktop: {},
  };
  try {
    const ctx = { store: approvalStore({ pending: 0 }) };
    const res = await reg.execute("help", ctx, {});
    assert.equal(res.ok, true);
    assert.ok(
      events.some((e) => e.type === "electromind:open-shortcuts"),
    );
    assert.ok(
      !events.some((e) => e.type === "electromind:palette-toggle-all"),
    );
  } finally {
    globalThis.window = prevWindow;
  }
  resetCommandRegistry();
});

// ── tokensToArgs（slash 参数 → 命令 args）────────────────────────────

test("tokensToArgs: /deny keeps the rest as reason; /help parses --all", () => {
  assert.deepEqual(tokensToArgs("run.deny", ["风险", "过高"]), {
    reason: "风险 过高",
  });
  assert.deepEqual(tokensToArgs("run.allow", []), {});
  assert.deepEqual(tokensToArgs("help", ["--all"]), { all: true });
  assert.deepEqual(tokensToArgs("help", []), { all: false });
});

// ── 门不依赖 slash_skill_v2：状态门是独立的通用机制 ───────────────────

test("gate: approval gate applies regardless of feature flags", async () => {
  __seedDesktopFeaturesForTest({});
  resetCommandRegistry();
  const reg = getCommandRegistry();
  registerCoreCommands(reg);
  const ctx = { store: approvalStore({ pending: 1 }) };
  const prevWindow = globalThis.window;
  globalThis.window = approvalWindow().win;
  try {
    // flag 全关时 skill.root 本来不可用；门把非放行集一并拦下
    assert.equal(reg.isAvailable("status.show", ctx), true);
    assert.equal(reg.isAvailable("agent.ask", ctx), false);
  } finally {
    globalThis.window = prevWindow;
  }
  __seedDesktopFeaturesForTest({});
  resetCommandRegistry();
});

// ── CommandRegistry.setStateGate 单元（不带真实命令集）────────────────

test("registry: setStateGate applies before spec.available and in execute", async () => {
  const r = new CommandRegistry();
  const spec = {
    id: "g.test",
    title: "g",
    description: "d",
    category: "view",
    kind: "ui",
    slash: ["g"],
    available: () => true,
    execute: () => ({ ok: true }),
  };
  r.register(spec);
  // 无门：可用
  assert.equal(r.isAvailable("g.test", {}), true);
  // 装门：只放行白名单
  r.setStateGate(() => (id) => id === "g.only");
  assert.equal(r.isAvailable("g.test", {}), false, "白名单外不可用");
  const res = await r.execute("g.test", {}, {});
  assert.equal(res.ok, false);
  assert.match(res.error, /命令当前不可用/);
  // 换门：全放行
  r.setStateGate(() => () => true);
  assert.equal(r.isAvailable("g.test", {}), true);
});
