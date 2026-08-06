/** P0 几何与交互门禁 —— 三个验收窗口尺寸下的布局稳定性。
 *
 *  窗口：1024×768 / 1280×720 / 1440×900（resizeTo；主进程忽略
 *  --window-size，因为 BrowserWindow 显式指定尺寸）。
 *
 *  每尺寸断言：
 *   - 无横向滚动；body 无纵向滚动
 *   - Composer 恒在主列底部（chat-log 之上、视口之内），非浮层
 *   - 左栏会话列表不落到主区域下方
 *   - Inspector 开/关不改变 Composer 垂直位置
 *   - 等待审批：审批卡在 chat-log 内完整可见、按钮可点击
 *     （elementFromPoint 命中）、不与 Composer 相交
 *   - 长 Timeline 只滚动 Timeline（chat-log 可滚动，body 不滚动）
 *
 * 环境：需要已编译 dist/ 与 electron。无真实 agent
 * （ELECTROMIND_TRANSPORT=http）。
 */

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { test } from "node:test";

const APP_DIR = new URL("..", import.meta.url).pathname;
const ELECTRON = new URL("../node_modules/.bin/electron", import.meta.url).pathname;

const SIZES = [
  [1024, 768],
  [1280, 720],
  [1440, 900],
];

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function fetchJson(url) {
  const res = await fetch(url);
  return res.json();
}

/** 经 CDP 连到 target，发送一条任意方法调用。返回完整 msg.result
 *  （evaluate 时为 { result: {...}, exceptionDetails? }）。 */
async function cdpSend(target, method, params = {}) {
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });
  const msg = await new Promise((resolve, reject) => {
    const id = 1;
    const timer = setTimeout(() => reject(new Error("cdp send timeout")), 8000);
    ws.onmessage = (event) => {
      const parsed = JSON.parse(event.data);
      if (parsed.id === id) {
        clearTimeout(timer);
        resolve(parsed);
      }
    };
    ws.send(JSON.stringify({ id, method, params }));
  });
  ws.close();
  if (msg.error) {
    throw new Error(`cdp ${method} error: ${JSON.stringify(msg.error)}`);
  }
  return msg.result;
}

/** 经 CDP 连到 target，执行一段 JS。awaitPromise 仅对 async 表达式开启
 *  —— 同步条件表达式开启 awaitPromise 会在启动早期挂起（实测 CDP
 *  eval 8s 超时），轮询必须用同步求值。 */
async function cdpEval(target, expression, opts = {}) {
  const r = await cdpSend(target, "Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: opts.awaitPromise === true,
  });
  if (r.exceptionDetails) {
    throw new Error(
      `cdp eval exception: ${JSON.stringify(r.exceptionDetails).slice(0, 500)}`,
    );
  }
  return r.result?.value;
}

function isAppTarget(t) {
  return (
    t.type === "page" &&
    t.url !== "about:blank" &&
    (t.url || "").includes("index.html")
  );
}

/** 等待一个布尔表达式为真（轮询）。label 在前，timeoutMs 可选。 */
async function waitFor(page, expression, label = "condition", timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      if (await cdpEval(page, expression)) {
        return true;
      }
    } catch {
      /* renderer 可能还在启动 */
    }
    await sleep(200);
  }
  // 失败诊断：页面状态快照
  let diag = "";
  try {
    diag = await cdpEval(
      page,
      `JSON.stringify({ url: location.href, ready: document.readyState, html: (document.documentElement?.outerHTML || '').slice(0, 500) })`,
    );
  } catch {
    diag = "<diag eval failed>";
  }
  assert.fail(`等待超时: ${label}；${diag}`);
}

/** 隐藏可能弹出的 onboarding 等模态，避免遮挡几何断言。 */
const HIDE_MODALS = `
  document.querySelectorAll('.desktop-modal').forEach(m => { m.hidden = true; });
  true;
`;

/** 注入一条待审批 + 工具项，使审批卡渲染。依赖 store 驱动渲染
 *  （uiState.runtime.currentThreadId 无后端时回退到 store.activeThreadId）。 */
const INJECT_APPROVAL = `
  (async () => {
    const store = window.__electromindStore;
    if (!store) return 'no-store';
    const sm = window.__electromindSM;
    const id = 'geom-approval';
    store.ensureThread(id, '几何测试');
    store.setActiveThread(id);
    if (sm) { sm.switchThread(id).catch(() => {}); }
    store.updateThread(id, {
      status: 'running',
      pendingPermits: [{
        toolCallId: 'tc-1',
        approvalId: 'ap-1',
        toolName: 'run_command',
        arguments: '{}',
        threadId: id,
        runId: 'run-1',
        timestamp: Date.now(),
      }],
    });
    store.appendThreadItem(id, {
      id: 'item-approval-1',
      kind: 'approval',
      threadId: id,
      timestamp: Date.now(),
      payload: {
        tool_call_id: 'tc-1',
        name: 'run_command',
        status: 'pending',
        summary: 'geometry gate approval',
        risk: 'high',
      },
    });
    store.setActivityState('running');
    return 'injected';
  })();
`;

/** 注入 200 条工具调用项，制造可滚动长 Timeline。 */
const INJECT_LONG_TIMELINE = `
  (() => {
    const store = window.__electromindStore;
    const id = store.getActiveThreadId() ?? 'geom-approval';
    store.ensureThread(id, '几何测试');
    store.setActiveThread(id);
    const now = Date.now();
    for (let i = 0; i < 200; i++) {
      store.appendThreadItem(id, {
        id: 'item-long-' + i,
        kind: 'tool_call',
        threadId: id,
        timestamp: now - (200 - i) * 1000,
        payload: { name: 'read_file', tool_call_id: 'tc-long-' + i, status: 'done' },
      });
    }
    return true;
  })();
`;

test("P0 geometry gates at 1024x768 / 1280x720 / 1440x900", async () => {
  const port = 9533 + Math.floor(Math.random() * 200);
  const proc = spawn(ELECTRON, [APP_DIR, `--remote-debugging-port=${port}`, "--no-sandbox"], {
    stdio: ["ignore", "ignore", "pipe"],
    env: {
      ...process.env,
      ELECTROMIND_HOME: "/tmp/electromind-geometry",
      ELECTROMIND_TRANSPORT: "http",
    },
  });
  let stderr = "";
  proc.stderr.on("data", (d) => {
    stderr += d;
  });

  let page = null;
  try {
    const deadline = Date.now() + 30_000;
    while (Date.now() < deadline) {
      try {
        const targets = await fetchJson(`http://127.0.0.1:${port}/json`);
        page = targets.find(isAppTarget);
        if (page) break;
      } catch {
        /* not up yet */
      }
      await sleep(300);
    }
    assert.ok(page, `应存在 index.html page target；stderr=${stderr.slice(-500)}`);

    // 等待 React 外壳 + 槽位填充完成（vanilla 面板就位）
    await waitFor(
      page,
      "!!document.querySelector('.desktop-shell[data-shell]') && !!document.querySelector('#react-appshell-root') && !!document.querySelector('[data-session-list]')",
      "React AppShell + slots 就绪",
    );
    // 等待 boot splash 消失（start() 完成）
    await waitFor(
      page,
      "document.documentElement.dataset.boot === 'done'",
      "boot splash 完成",
    );

    for (const [w, h] of SIZES) {
      // 主进程忽略 --window-size（BrowserWindow 显式尺寸），且 macOS 会按
      // workArea 钳制窗口高度（本机 workArea 仅 ~638px，768 不可达）。
      // 用 CDP 视口模拟把页面布局到验收尺寸 —— 几何断言测量的是布局视口。
      await cdpSend(page, "Emulation.setDeviceMetricsOverride", {
        width: w,
        height: h,
        deviceScaleFactor: 1,
        mobile: false,
      });
      await waitFor(
        page,
        `Math.abs(window.innerWidth - ${w}) <= 2 && Math.abs(window.innerHeight - ${h}) <= 2`,
        `视口模拟到 ${w}x${h}`,
      );
      await sleep(150); // 布局稳定（CSS transition 均 < 600ms，足够）

      const probe = await cdpEval(
        page,
        `(() => {
          const r = (el) => {
            if (!el) return null;
            const b = el.getBoundingClientRect();
            return { left: b.left, top: b.top, right: b.right, bottom: b.bottom,
                     width: b.width, height: b.height };
          };
          const composer = document.querySelector('[data-composer-react] .composer');
          const chatLog = document.querySelector('[data-chat-log]');
          const leftPane = document.querySelector('[data-left-pane]');
          const centerPane = document.querySelector('.pane-center');
          const sessionList = document.querySelector('.session-list');
          const workbench = document.querySelector('[data-workbench]');
          const vw = window.innerWidth;
          const vh = window.innerHeight;
          return {
            composer: r(composer),
            chatLog: r(chatLog),
            leftPane: r(leftPane),
            centerPane: r(centerPane),
            sessionList: r(sessionList),
            workbench: r(workbench),
            vw, vh,
            docScrollW: document.documentElement.scrollWidth,
            bodyScrollH: document.body.scrollHeight,
            bodyOverflow: getComputedStyle(document.body).overflow,
          };
        })()`,
      );
      assert.ok(probe.composer, `[${w}x${h}] React Composer 应存在`);
      assert.ok(probe.chatLog, `[${w}x${h}] chat-log 应存在`);

      // ── 无横向滚动；body 无纵向滚动 ─────────────────────────────
      assert.ok(
        probe.docScrollW <= probe.vw + 1,
        `[${w}x${h}] 无横向滚动（scrollWidth=${probe.docScrollW} vw=${probe.vw}）`,
      );
      assert.ok(
        probe.bodyScrollH <= probe.vh + 1,
        `[${w}x${h}] body 无纵向滚动（scrollHeight=${probe.bodyScrollH} vh=${probe.vh}）`,
      );
      assert.equal(
        probe.bodyOverflow,
        "hidden",
        `[${w}x${h}] body overflow 必须 hidden`,
      );

      // ── Composer 恒在主列底部、不覆盖 Timeline ──────────────────
      assert.ok(
        probe.composer.bottom <= probe.vh + 1 && probe.composer.top >= 0,
        `[${w}x${h}] Composer 在视口内（top=${probe.composer.top} bottom=${probe.composer.bottom} vh=${probe.vh}）`,
      );
      assert.ok(
        probe.chatLog.bottom <= probe.composer.top + 1,
        `[${w}x${h}] Timeline 不被 Composer 覆盖（chatLog.bottom=${probe.chatLog.bottom} composer.top=${probe.composer.top}）`,
      );
      assert.ok(
        probe.composer.left >= probe.centerPane.left - 1 &&
          probe.composer.right <= probe.centerPane.right + 1,
        `[${w}x${h}] Composer 位于主列内`,
      );

      // ── 左栏不落到主区域下方 ────────────────────────────────────
      assert.ok(
        probe.leftPane.top >= 0 && probe.leftPane.bottom <= probe.vh + 1,
        `[${w}x${h}] 左栏在视口内（bottom=${probe.leftPane.bottom}）`,
      );
      assert.ok(
        probe.sessionList && probe.sessionList.bottom <= probe.vh + 1,
        `[${w}x${h}] 会话列表不掉到主区域下方`,
      );

      // ── Inspector 开关不改变 Composer 位置（垂直）────────────────
      const before = await cdpEval(
        page,
        `(() => { const b = document.querySelector('[data-composer-react] .composer').getBoundingClientRect(); return { top: b.top, bottom: b.bottom }; })()`,
      );
      await cdpEval(
        page,
        `window.__electromindStore.setInspector({ open: true, pinned: true }); true;`,
      );
      await sleep(250); // push 模式 grid 变化 + transition
      const during = await cdpEval(
        page,
        `(() => { const b = document.querySelector('[data-composer-react] .composer').getBoundingClientRect(); return { top: b.top, bottom: b.bottom }; })()`,
      );
      assert.ok(
        Math.abs(before.top - during.top) <= 1 &&
          Math.abs(before.bottom - during.bottom) <= 1,
        `[${w}x${h}] Inspector 开/关不改变 Composer 位置（before=${JSON.stringify(before)} during=${JSON.stringify(during)}）`,
      );
      await cdpEval(
        page,
        `window.__electromindStore.setInspector({ open: false, pinned: false }); true;`,
      );
      await sleep(250);

      // ── 等待审批：审批卡可见、按钮可点击、不与 Composer 相交 ────
      await cdpEval(page, HIDE_MODALS);
      const injected = await cdpEval(page, INJECT_APPROVAL, { awaitPromise: true });
      assert.equal(injected, "injected", `[${w}x${h}] 审批注入成功`);
      try {
        await waitFor(
          page,
          "!!document.querySelector('.approval-card') && !document.querySelector('.approval-card').hidden",
          `[${w}x${h}] 审批卡渲染`,
          10_000,
        );
      } catch (e) {
        // 失败诊断：注入后的 store / timeline / DOM 状态
        const diag = await cdpEval(
          page,
          `JSON.stringify({
            active: window.__electromindStore?.getActiveThreadId(),
            kinds: (window.__electromindStore?.getThread('geom-approval')?.timeline || []).map(i => i.kind),
            permits: (window.__electromindStore?.getThread('geom-approval')?.pendingPermits || []).length,
            chatChildren: document.querySelector('[data-chat-log]')?.children.length,
            chatHtml: (document.querySelector('[data-chat-log]')?.innerHTML || '').slice(0, 400),
          })`,
        );
        assert.fail(`${e.message}；注入后状态：${diag}`);
      }
      const approval = await cdpEval(
        page,
        `(async () => {
          const card = document.querySelector('.approval-card');
          card.scrollIntoView({ block: 'nearest' });
          await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
          const chatLog = document.querySelector('[data-chat-log]');
          const composer = document.querySelector('[data-composer-react] .composer');
          const cb = card.getBoundingClientRect();
          const lb = chatLog.getBoundingClientRect();
          const pb = composer.getBoundingClientRect();
          const hitTest = (sel) => {
            const el = document.querySelector(sel);
            const b = el.getBoundingClientRect();
            const cx = b.left + b.width / 2;
            const cy = b.top + b.height / 2;
            const hit = document.elementFromPoint(cx, cy);
            return { ok: hit === el || el.contains(hit), rect: { left: b.left, top: b.top, right: b.right, bottom: b.bottom }, hit: hit ? hit.className || hit.tagName : null };
          };
          const intersects = (a, b) => !(a.right <= b.left || a.left >= b.right ||
                                         a.bottom <= b.top || a.top >= b.bottom);
          return {
            card: { left: cb.left, top: cb.top, right: cb.right, bottom: cb.bottom },
            chatLog: { left: lb.left, top: lb.top, right: lb.right, bottom: lb.bottom },
            composer: { left: pb.left, top: pb.top, right: pb.right, bottom: pb.bottom },
            allow: hitTest('.approval-allow'),
            deny: hitTest('.approval-deny'),
            intersectsComposer: intersects(cb, pb),
            fullyInChat: cb.top >= lb.top - 1 && cb.bottom <= lb.bottom + 1 &&
                         cb.left >= lb.left - 1 && cb.right <= lb.right + 1,
          };
        })()`,
        { awaitPromise: true },
      );
      assert.ok(
        approval.allow.ok && approval.deny.ok,
        `[${w}x${h}] Allow once / Deny 始终可点击（allow=${JSON.stringify(approval.allow)} deny=${JSON.stringify(approval.deny)}）`,
      );
      assert.equal(
        approval.intersectsComposer,
        false,
        `[${w}x${h}] 审批卡不被 Composer 覆盖（composer=${JSON.stringify(approval.composer)}）`,
      );
      assert.ok(
        approval.fullyInChat,
        `[${w}x${h}] 审批卡完整位于 Timeline 内`,
      );

      // ── 长 Timeline 只滚动 Timeline ──────────────────────────────
      await cdpEval(page, INJECT_LONG_TIMELINE);
      await sleep(300);
      const scroll = await cdpEval(
        page,
        `(() => {
          const chatLog = document.querySelector('[data-chat-log]');
          const doc = document.documentElement;
          return {
            chatScrollable: chatLog.scrollHeight > chatLog.clientHeight + 10,
            chatOverflowY: getComputedStyle(chatLog).overflowY,
            docScrollH: doc.scrollHeight,
            vh: window.innerHeight,
          };
        })()`,
      );
      assert.ok(
        scroll.chatScrollable,
        `[${w}x${h}] 长 Timeline 时 chat-log 自身可滚动`,
      );
      assert.equal(
        scroll.chatOverflowY,
        "auto",
        `[${w}x${h}] chat-log overflow-y 为 auto`,
      );
      assert.ok(
        scroll.docScrollH <= scroll.vh + 1,
        `[${w}x${h}] 长 Timeline 时 body 仍不滚动（docScrollH=${scroll.docScrollH}）`,
      );

      // 清理注入状态，进入下一个尺寸
      await cdpEval(
        page,
        `(() => { const s = window.__electromindStore; const t = s.getActiveThreadId(); if (t) s.removeThread(t); s.setActivityState('sleeping'); return true; })()`,
      );
      // 恢复真实视口，避免模拟尺寸泄漏到下一轮
      await cdpSend(page, "Emulation.clearDeviceMetricsOverride");
    }
  } finally {
    proc.kill("SIGTERM");
    await sleep(300);
    try {
      proc.kill("SIGKILL");
    } catch {
      /* already dead */
    }
    await new Promise((r) => setTimeout(r, 200));
  }
});
