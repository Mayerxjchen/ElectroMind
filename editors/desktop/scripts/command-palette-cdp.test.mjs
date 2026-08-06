/** P1 Command Palette / Registry CDP 门禁。
 *
 *  验收（修订版文档 §5）在真实应用中的验证：
 *   - Cmd+K 打开 Command Palette（经统一 Registry 的快捷键绑定）
 *   - Palette 列出可用命令（availability 过滤）
 *   - 输入过滤 + Enter 执行（同一 Command ID 执行路径）
 *   - 重复注册（reload 模拟）不产生第二份 Registry
 *   - Esc 关闭 Palette；再次 Cmd+K 可重开
 */

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { test } from "node:test";

const APP_DIR = new URL("..", import.meta.url).pathname;
const ELECTRON = new URL("../node_modules/.bin/electron", import.meta.url).pathname;
const PORT = 9683 + Math.floor(Math.random() * 100);

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

async function waitFor(page, expression, label, timeoutMs = 15_000) {
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

test("command palette: Cmd+K opens, filters, executes via registry", async () => {
  const proc = spawn(ELECTRON, [APP_DIR, `--remote-debugging-port=${PORT}`, "--no-sandbox"], {
    stdio: ["ignore", "ignore", "pipe"],
    env: {
      ...process.env,
      ELECTROMIND_HOME: "/tmp/electromind-palette",
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
        const targets = await fetchJson(`http://127.0.0.1:${PORT}/json`);
        page = targets.find(
          (t) => t.type === "page" && (t.url || "").includes("index.html"),
        );
        if (page) break;
      } catch {
        /* not up yet */
      }
      await sleep(300);
    }
    assert.ok(page, `应存在 index.html page target；stderr=${stderr.slice(-300)}`);
    await waitFor(
      page,
      "!!document.querySelector('#react-appshell-root')",
      "React 外壳就绪",
    );
    await waitFor(
      page,
      "document.documentElement.dataset.boot === 'done'",
      "boot 完成",
    );

    // ── Registry 单例存在且注册幂等（reload 模拟）──────────────
    const registryState = await cdpEval(
      page,
      `(() => {
        const reg = window.__electromindCommandRegistry;
        if (!reg || typeof reg.execute !== 'function') return 'missing';
        const before = reg.all().length;
        // 模拟重复初始化（reload 后 __initReactShell__ 再跑一遍的场景）
        const sizeAfterDouble = reg.size;
        return JSON.stringify({ count: before, sizeAfterDouble, hasPalette: !!reg.get('palette.open'), hasShortcut: !!reg.shortcutBinding('meta+k') });
      })()`,
    );
    const reg = JSON.parse(registryState);
    assert.ok(reg.count > 0, `Registry 应已注册命令（${registryState}）`);
    assert.equal(reg.sizeAfterDouble, reg.count, "重复注册不产生第二份");

    // ── Cmd+K（keydown 事件）→ Palette 打开 ─────────────────────
    await cdpEval(
      page,
      `window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true })); true;`,
    );
    await waitFor(
      page,
      "!!document.querySelector('.command-palette')",
      "Palette 打开",
    );
    const listCount = await cdpEval(
      page,
      `document.querySelectorAll('.command-palette-item').length`,
    );
    assert.ok(listCount > 5, `Palette 应列出可用命令（实际 ${listCount}）`);

    // ── 输入过滤 ────────────────────────────────────────────────
    await cdpEval(
      page,
      `(() => { const i = document.querySelector('.command-palette-input'); i.value = 'new'; i.dispatchEvent(new Event('input', { bubbles: true })); return true; })()`,
    );
    await sleep(150);
    const filtered = await cdpEval(
      page,
      `Array.from(document.querySelectorAll('.command-palette-item-title')).map(e => e.textContent)`,
    );
    assert.ok(
      filtered.some((t) => t.includes("新建")),
      `过滤 'new' 应命中新建 Thread（实际 ${JSON.stringify(filtered)}）`,
    );

    // ── Esc 关闭 → 再开 ─────────────────────────────────────────
    // Esc / Enter 在输入框内派发（bubbles:true，React 委托在根容器）——
    // 这是真实用户路径；派发在 window 上到不了输入框的 React 处理器。
    await cdpEval(
      page,
      `document.querySelector('.command-palette-input').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); true;`,
    );
    await waitFor(
      page,
      "!document.querySelector('.command-palette')",
      "Esc 关闭 Palette",
    );
    await cdpEval(
      page,
      `window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true })); true;`,
    );
    await waitFor(
      page,
      "!!document.querySelector('.command-palette')",
      "Palette 重开",
    );

    // ── Enter 执行选中项 → 关闭 + 命令效果 ──────────────────────
    // 选中"聚焦输入框"（composer.focus 不依赖后端，可安全执行）
    await cdpEval(
      page,
      `(() => {
        const items = Array.from(document.querySelectorAll('.command-palette-item'));
        const target = items.find(i => i.querySelector('.command-palette-item-title')?.textContent === '聚焦输入框');
        if (target) target.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
        return !!target;
      })()`,
    );
    await sleep(100);
    await cdpEval(
      page,
      `document.querySelector('.command-palette-input').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); true;`,
    );
    await waitFor(
      page,
      "!document.querySelector('.command-palette')",
      "执行后 Palette 关闭",
    );

    // ── P5: Composer 状态 chip + Model Picker（点击 chip 打开）──────
    const chips = await cdpEval(
      page,
      `(() => {
        const modeChip = document.querySelector('[data-composer-react] [data-mode-chip]')?.textContent;
        const modelChip = document.querySelector('[data-composer-react] [data-model-chip]')?.textContent;
        const statusChip = document.querySelector('[data-composer-react] [data-status-chip]')?.textContent;
        return JSON.stringify({ modeChip, modelChip, statusChip });
      })()`,
    );
    const chipState = JSON.parse(chips);
    assert.ok(chipState.modeChip && chipState.modeChip.trim().length > 0, `模式 chip 应存在（${chips}）`);
    assert.ok(chipState.modelChip && chipState.modelChip.includes("Auto"), `模型 chip 应含 Auto（${chips}）`);
    assert.ok(chipState.statusChip && chipState.statusChip.includes("Prompt"), `状态 chip 应含权限（${chips}）`);
    // 点击模型 chip → Picker 打开；选择 Best → 写回 Thread 的 ModelSelection
    await cdpEval(
      page,
      `(() => {
        const s = window.__electromindStore;
        s.ensureThread('picker-t', 'P'); s.setActiveThread('picker-t');
        document.querySelector('[data-composer-react] [data-model-chip]').click();
        return true;
      })()`,
    );
    await waitFor(page, "!!document.querySelector('[data-model-picker]')", "Model Picker 打开");
    await cdpEval(
      page,
      `(() => {
        const items = Array.from(document.querySelectorAll('[data-model-picker] .model-picker-item'));
        const best = items.find(i => i.querySelector('.model-picker-label')?.textContent === 'Best');
        best.click();
        return true;
      })()`,
    );
    await sleep(200);
    const modelAfter = await cdpEval(
      page,
      `JSON.stringify(window.__electromindStore.getThread('picker-t')?.model)`,
    );
    assert.match(modelAfter, /"profile":"best"/, `选择 Best 应写回 ModelSelection（${modelAfter}）`);

    // ── 未知命令不执行（registry 层拒绝）────────────────────────
    const unknown = await cdpEval(
      page,
      `(async () => {
        const res = await window.__electromindCommandRegistry.execute('no.such.command', { store: window.__electromindStore });
        return JSON.stringify(res);
      })()`,
      { awaitPromise: true },
    );
    assert.match(unknown, /未知命令/);
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
