/** P2 Slash Menu CDP 门禁 —— Claude Code 语义在真实应用中的验证。
 *
 *   - 输入 "/" 打开菜单；"/sk" 实时过滤为 /skills /skill-info
 *   - "/plan <task>" 是命令（切模式 + 发任务）；"请解释 /plan 的作用"
 *     是普通消息（不弹菜单）
 *   - 未知 Slash Command 不发送给模型（显示错误提示）
 *   - Tab 补全
 */

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { test } from "node:test";

const APP_DIR = new URL("..", import.meta.url).pathname;
const ELECTRON = new URL("../node_modules/.bin/electron", import.meta.url).pathname;
const PORT = 9783 + Math.floor(Math.random() * 100);

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function fetchJson(url) {
  const res = await fetch(url);
  return res.json();
}

async function cdpSend(target, method, params = {}) {
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("cdp ws open timeout")), 5000);
    ws.onopen = () => { clearTimeout(timer); resolve(); };
    ws.onerror = (e) => { clearTimeout(timer); reject(new Error("cdp ws error")); };
  });
  const msg = await new Promise((resolve, reject) => {
    const id = 1;
    const timer = setTimeout(() => reject(new Error("cdp send timeout")), 5000);
    ws.onmessage = (event) => {
      const parsed = JSON.parse(event.data);
      if (parsed.id === id) { clearTimeout(timer); resolve(parsed); }
    };
    ws.send(JSON.stringify({ id, method, params }));
  });
  ws.close();
  if (msg.error) throw new Error(`cdp ${method}: ${JSON.stringify(msg.error)}`);
  return msg.result;
}

async function cdpEval(target, expression, opts = {}) {
  const r = await cdpSend(target, "Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: opts.awaitPromise === true,
  });
  if (r.exceptionDetails) {
    throw new Error(
      `cdp eval exception: ${JSON.stringify(r.exceptionDetails).slice(0, 300)}`,
    );
  }
  return r.result?.value;
}

async function waitFor(page, expression, label, timeoutMs = 20_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      if (await cdpEval(page, expression)) return true;
    } catch {
      /* still booting */
    }
    await sleep(200);
  }
  assert.fail(`等待超时: ${label}`);
}

/** 设置输入框文本（React 受控 —— 先 .value 再派发 input 事件）。 */
const SET_INPUT = (text) => `
  (() => {
    const i = document.querySelector('[data-composer-react] .composer-input');
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(i, ${JSON.stringify(text)});
    i.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  })()
`;

const KEY = (key, extra = "") => `
  (() => {
    const i = document.querySelector('[data-composer-react] .composer-input');
    i.dispatchEvent(new KeyboardEvent('keydown', { key: ${JSON.stringify(key)}, bubbles: true ${extra ? `, ${extra}` : ""} }));
    return true;
  })()
`;

test("slash menu: leading slash opens, filters, executes, never sends unknown", async () => {
  const proc = spawn(ELECTRON, [APP_DIR, `--remote-debugging-port=${PORT}`, "--no-sandbox"], {
    stdio: ["ignore", "ignore", "pipe"],
    env: {
      ...process.env,
      ELECTROMIND_HOME: "/tmp/electromind-slash",
      ELECTROMIND_TRANSPORT: "http",
    },
  });
  let stderr = "";
  proc.stderr.on("data", (d) => { stderr += d; });
  let page = null;
  try {
    const deadline = Date.now() + 30_000;
    while (Date.now() < deadline) {
      try {
        const targets = await fetchJson(`http://127.0.0.1:${PORT}/json`);
        page = targets.find(
          (t) => t.type === "page" && (t.url || "").includes("index.html"),
        );
        if (page) break;
      } catch { /* not up yet */ }
      await sleep(300);
    }
    assert.ok(page, `应存在 index.html page target；stderr=${stderr.slice(-300)}`);
    await waitFor(
      page,
      "document.documentElement.dataset.boot === 'done' && !!document.querySelector('[data-composer-react] .composer-input')",
      "boot + 输入框就绪",
    );
    // 准备一个活动 Thread + 模拟已连接（Agent 命令的 availability 依赖
    // bridgeActive；无真实 agent 的测试环境需要显式置为 true）。
    // 同时注入一个 Skill 状态，让 /skill-info 进入可用列表（文档的
    // "/sk → /skills /skill-info" 过滤示例以 Skills 存在为前提）。
    await cdpEval(
      page,
      `(() => {
        const s = window.__electromindStore;
        s.ensureThread('slash-t', 'Slash 测试');
        s.setActiveThread('slash-t');
        s.setBridgeActive(true);
        s.setThreadSkillsState('slash-t', {
          threadId: 'slash-t', fingerprint: 'f', generation: 1, digest: 'd',
          skills: [{ name: 'cp2k', description: 'CP2K', source: 'builtin', sha256: 'abc', status: 'available' }],
          loaded: [], loadedThisRun: [], diagnostics: [],
        });
        return true;
      })()`,
    );
    await sleep(150);

    // ── "/" 打开菜单 ─────────────────────────────────────────────
    await cdpEval(page, SET_INPUT("/"));
    await waitFor(page, "!!document.querySelector('.slash-menu')", "菜单打开");
    const allItems = await cdpEval(
      page,
      `Array.from(document.querySelectorAll('.slash-menu-name')).map(e => e.textContent)`,
    );
    assert.ok(allItems.includes("/skills"), `菜单应含 /skills（${JSON.stringify(allItems)}）`);
    assert.ok(allItems.includes("/plan"), `菜单应含 /plan（${JSON.stringify(allItems)}）`);

    // ── "/sk" 实时过滤 ───────────────────────────────────────────
    await cdpEval(page, SET_INPUT("/sk"));
    await sleep(150);
    const filtered = await cdpEval(
      page,
      `Array.from(document.querySelectorAll('.slash-menu-name')).map(e => e.textContent)`,
    );
    assert.ok(
      filtered.length === 2 && filtered.every((n) => n.startsWith("/sk")),
      `/sk 应过滤为 /skills /skill-info（实际 ${JSON.stringify(filtered)}）`,
    );

    // ── P4: SKILLS 分组（可信 + 可用户调用的 Skill 动态生成 /cp2k）──
    await cdpEval(page, SET_INPUT("/"));
    await sleep(150);
    const groups = await cdpEval(
      page,
      `Array.from(document.querySelectorAll('.slash-menu-group-label')).map(e => e.textContent)`,
    );
    assert.ok(
      groups.includes("SKILLS"),
      `菜单应有 SKILLS 分组（实际 ${JSON.stringify(groups)}）`,
    );
    const skillItems = await cdpEval(
      page,
      `(() => {
        const groups = Array.from(document.querySelectorAll('.slash-menu-group'));
        const skills = groups.find(g => g.querySelector('.slash-menu-group-label')?.textContent === 'SKILLS');
        return skills ? Array.from(skills.querySelectorAll('.slash-menu-name')).map(e => e.textContent) : [];
      })()`,
    );
    assert.ok(
      skillItems.includes("/cp2k"),
      `SKILLS 分组应含 /cp2k（实际 ${JSON.stringify(skillItems)}）`,
    );

    // ── "/plan <task>" 是命令：切模式 + 清空输入 ─────────────────
    await cdpEval(page, SET_INPUT("/plan 检查当前 CP2K 输入"));
    await sleep(100);
    await cdpEval(page, KEY("Enter"));
    await sleep(300);
    const mode = await cdpEval(
      page,
      `window.__electromindStore.getThread('slash-t')?.sessionMode`,
    );
    assert.equal(mode, "plan", "/plan 应切换 Thread 模式为 plan");
    const textAfter = await cdpEval(
      page,
      `document.querySelector('[data-composer-react] .composer-input').value`,
    );
    assert.equal(textAfter, "", "命令执行后输入框应清空");

    // ── "请解释 /plan 的作用" 是普通消息（不弹菜单）──────────────
    await cdpEval(page, SET_INPUT("请解释 /plan 的作用"));
    await sleep(150);
    const menuAfter = await cdpEval(page, `!!document.querySelector('.slash-menu')`);
    assert.equal(menuAfter, false, "消息中的 / 不应弹菜单");

    // ── 未知命令：错误提示、不发送、输入保留 ─────────────────────
    await cdpEval(page, SET_INPUT("/nosuchcmd 跑一下"));
    await sleep(100);
    await cdpEval(page, KEY("Enter"));
    await sleep(300);
    const slashError = await cdpEval(
      page,
      `(document.querySelector('[data-slash-error] .composer-error-text')?.textContent || '')`,
    );
    assert.match(slashError, /未知命令/, `未知命令应提示（实际 ${slashError}）`);
    const textKept = await cdpEval(
      page,
      `document.querySelector('[data-composer-react] .composer-input').value`,
    );
    assert.equal(textKept, "/nosuchcmd 跑一下", "未知命令不发送、输入保留");

    // ── Tab 补全 ─────────────────────────────────────────────────
    await cdpEval(page, SET_INPUT("/sk"));
    await sleep(100);
    await cdpEval(page, KEY("Tab"));
    await sleep(150);
    const completed = await cdpEval(
      page,
      `document.querySelector('[data-composer-react] .composer-input').value`,
    );
    assert.ok(
      completed.startsWith("/skill"),
      `Tab 应补全为 /skills 或 /skill-info（实际 ${completed}）`,
    );
  } finally {
    proc.kill("SIGTERM");
    await sleep(300);
    try { proc.kill("SIGKILL"); } catch { /* already dead */ }
    await new Promise((r) => setTimeout(r, 200));
  }
});
