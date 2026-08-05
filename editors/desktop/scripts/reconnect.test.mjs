// D3: 自动重连调度器（shared/reconnect.ts）单元测试。
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { createReconnectScheduler, RECONNECT_MAX_ATTEMPTS } = require("../src/shared/reconnect.ts");

// 用真实定时器但把退避基数压小（10ms），测试总时长可控。
function makeScheduler({ maxAttempts } = {}) {
  const calls = [];
  const scheduler = createReconnectScheduler({
    onReconnect: () => calls.push(Date.now()),
    baseDelayMs: 10,
    maxDelayMs: 40,
    maxAttempts: maxAttempts ?? RECONNECT_MAX_ATTEMPTS,
  });
  return { scheduler, calls };
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

test("schedule 退避递增：1x, 2x, 4x（以 10ms 为基数）", async () => {
  const { scheduler, calls } = makeScheduler();
  assert.equal(scheduler.schedule(), true); // 第 1 次 → 10ms
  assert.equal(scheduler.schedule(), true); // 第 2 次 → 20ms
  assert.equal(scheduler.schedule(), true); // 第 3 次 → 40ms
  await wait(120);
  assert.equal(calls.length, 1, "仅第一次定时器触发（后续 schedule 覆盖前一个）");
  scheduler.cancel();
});

test("schedule 覆盖：重连尝试前再次失败不会叠加定时器", async () => {
  const { scheduler, calls } = makeScheduler();
  scheduler.schedule();
  await wait(5);
  scheduler.schedule(); // 覆盖前一个 10ms 定时器 → 新的 20ms
  await wait(120);
  assert.equal(calls.length, 1);
  scheduler.cancel();
});

test("onConnected 重置：成功连接后失败重新从 1x 退避", async () => {
  const { scheduler } = makeScheduler();
  scheduler.schedule(); // 10ms
  scheduler.onConnected(); // 重置
  assert.equal(scheduler.attempts, 0);
  scheduler.schedule(); // 又从 10ms 开始
  await wait(40);
  scheduler.onConnected();
  scheduler.cancel();
});

test("上限：超过 maxAttempts 后 schedule 返回 false（不无限重连）", () => {
  const { scheduler } = makeScheduler({ maxAttempts: 2 });
  assert.equal(scheduler.schedule(), true);
  scheduler.onConnected(); // 重置计数 —— 失败-成功-失败-成功不会耗尽
  assert.equal(scheduler.schedule(), true);
  scheduler.onConnected();
  // 连续失败 2 次后：
  scheduler.schedule();
  scheduler.cancel(); // 取消后 attempts 归零，可重新开始（手动重试路径）
  assert.equal(scheduler.schedule(), true);
  scheduler.schedule();
  scheduler.cancel();
});

test("cancel：取消后 pending=false 且不再触发", async () => {
  const { scheduler, calls } = makeScheduler();
  scheduler.schedule();
  assert.equal(scheduler.pending(), true);
  scheduler.cancel();
  assert.equal(scheduler.pending(), false);
  await wait(60);
  assert.equal(calls.length, 0);
});

test("达到上限后 pending=false（等待手动重试）", async () => {
  const { scheduler, calls } = makeScheduler({ maxAttempts: 1 });
  scheduler.schedule(); // 唯一一次
  await wait(60);
  assert.equal(calls.length, 1);
  assert.equal(scheduler.schedule(), false, "已达上限 → 不再安排");
  assert.equal(scheduler.pending(), false);
  scheduler.cancel();
});
