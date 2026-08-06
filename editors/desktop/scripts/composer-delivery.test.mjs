/** P0 Composer 投递决策测试 —— 统一交互优先级。
 *
 *  Spec: disconnected > waiting_approval > running > idle
 *  - 等待审批时不允许发送（Enter 不得误发新任务）；
 *  - 等待审批时隐藏 steer / 下一任务控件；
 *  - 断线同样禁用发送。
 *  纯模块（无 React/DOM），node --test 直接跑。
 */

import { test } from "node:test";
import assert from "node:assert/strict";

const m = await import(
  new URL("../src/renderer/react/composer-delivery.ts", import.meta.url)
);
const {
  deliveryForState,
  showSteerControls,
  composerInputDisabled,
  composerPlaceholder,
} = m;

test("delivery: idle → auto", () => {
  assert.equal(
    deliveryForState({ disconnected: false, isRunning: false, awaitingApproval: false, enqueueNext: false }),
    "auto",
  );
});

test("delivery: running steer → immediate", () => {
  assert.equal(
    deliveryForState({ disconnected: false, isRunning: true, awaitingApproval: false, enqueueNext: false }),
    "immediate",
  );
});

test("delivery: explicit next task → enqueue", () => {
  assert.equal(
    deliveryForState({ disconnected: false, isRunning: true, awaitingApproval: false, enqueueNext: true }),
    "enqueue",
  );
});

test("delivery: awaiting approval blocks ANY send (new task cannot bypass approval)", () => {
  assert.equal(
    deliveryForState({ disconnected: false, isRunning: true, awaitingApproval: true, enqueueNext: false }),
    null,
  );
  assert.equal(
    deliveryForState({ disconnected: false, isRunning: false, awaitingApproval: true, enqueueNext: false }),
    null,
  );
  // enqueueNext 显式排队也不能绕过
  assert.equal(
    deliveryForState({ disconnected: false, isRunning: false, awaitingApproval: true, enqueueNext: true }),
    null,
  );
});

test("delivery: disconnected blocks ANY send", () => {
  assert.equal(
    deliveryForState({ disconnected: true, isRunning: false, awaitingApproval: false, enqueueNext: false }),
    null,
  );
  assert.equal(
    deliveryForState({ disconnected: true, isRunning: true, awaitingApproval: false, enqueueNext: true }),
    null,
  );
});

test("steer controls: only running && !awaitingApproval", () => {
  assert.equal(showSteerControls({ isRunning: true, awaitingApproval: false }), true);
  assert.equal(showSteerControls({ isRunning: true, awaitingApproval: true }), false, "approval hides steer");
  assert.equal(showSteerControls({ isRunning: false, awaitingApproval: false }), false);
  assert.equal(showSteerControls({ isRunning: false, awaitingApproval: true }), false);
});

test("input disabled: disconnected or awaiting approval", () => {
  assert.equal(composerInputDisabled({ disconnected: false, awaitingApproval: false }), false);
  assert.equal(composerInputDisabled({ disconnected: true, awaitingApproval: false }), true);
  assert.equal(composerInputDisabled({ disconnected: false, awaitingApproval: true }), true);
});

test("placeholder: approval state wins over running/idle", () => {
  assert.equal(
    composerPlaceholder({ awaitingApproval: true, isRunning: true, mode: "agent" }),
    "等待审批…",
  );
  assert.equal(
    composerPlaceholder({ awaitingApproval: true, isRunning: false, mode: "ask" }),
    "等待审批…",
  );
  assert.equal(
    composerPlaceholder({ awaitingApproval: false, isRunning: true, mode: "agent" }),
    "输入 steer 指令…",
  );
  assert.equal(
    composerPlaceholder({ awaitingApproval: false, isRunning: false, mode: "plan" }),
    "描述要规划的任务…",
  );
  assert.equal(
    composerPlaceholder({ awaitingApproval: false, isRunning: false, mode: "ask" }),
    "输入任务…",
  );
});
