/** P5.3: CDP 冒烟测试 —— 打包/启动后的 Desktop 真能打开并渲染。
 *
 * 启动 Electron（--remote-debugging-port），经 Chrome DevTools Protocol
 * 连到渲染进程，断言：
 *   - 页面加载成功（非启动错误页）
 *   - #app 已挂载（根元素存在）
 *   - 未出现 P4.5 的启动错误（root 里没有 <pre> 错误块）
 *
 * 环境：需要已编译的 dist/（npm run compile）与 electron 可执行。
 */

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { test } from "node:test";

const PORT = 9333 + Math.floor(Math.random() * 200);
const APP_DIR = new URL("..", import.meta.url).pathname;
const ELECTRON = new URL("../node_modules/.bin/electron", import.meta.url).pathname;

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function fetchJson(url) {
  const res = await fetch(url);
  return res.json();
}

/** 经 CDP 连到 target，执行一段 JS，返回结果。 */
async function cdpEval(target, expression) {
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });
  const result = await new Promise((resolve, reject) => {
    const id = 1;
    const timer = setTimeout(() => reject(new Error("cdp eval timeout")), 8000);
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id === id) {
        clearTimeout(timer);
        resolve(msg.result);
      }
    };
    ws.send(
      JSON.stringify({
        id,
        method: "Runtime.evaluate",
        params: { expression, returnByValue: true },
      }),
    );
  });
  ws.close();
  return result.result?.value;
}

test("desktop renderer loads via CDP (no startup error page)", async () => {
  // CI（Linux root）需要 --no-sandbox；开发机加它无害。
  const electronArgs = [APP_DIR, `--remote-debugging-port=${PORT}`, "--no-sandbox"];
  const proc = spawn(ELECTRON, electronArgs, {
    stdio: ["ignore", "ignore", "pipe"],
    env: {
      ...process.env,
      ELECTROMIND_HOME: "/tmp/electromind-cdp-smoke",
      ELECTROMIND_TRANSPORT: "http", // 无真实 wire 后端；只验证渲染层
    },
  });
  let stderr = "";
  proc.stderr.on("data", (d) => {
    stderr += d;
  });

  try {
    // 等待 CDP endpoint 就绪
    let targets = [];
    const deadline = Date.now() + 30_000;
    while (Date.now() < deadline) {
      try {
        targets = await fetchJson(`http://127.0.0.1:${PORT}/json`);
        if (targets.length > 0) {
          break;
        }
      } catch {
        /* not up yet */
      }
      await sleep(300);
    }
    assert.ok(targets.length > 0, "CDP target 应可达");

    const page = targets.find((t) => t.type === "page");
    assert.ok(page, "应存在 page target");
    // 等 readyState 到 complete（渲染进程脚本执行完，React shell 挂载）。
    let ready = "loading";
    const readyDeadline = Date.now() + 20_000;
    while (Date.now() < readyDeadline) {
      ready = await cdpEval(page, "document.readyState");
      if (ready === "complete") {
        break;
      }
      await sleep(300);
    }
    assert.equal(ready, "complete", `页面应加载完成，实际 ${ready}`);

    const hasApp = await cdpEval(page, "!!document.getElementById('app')");
    assert.equal(hasApp, true, "#app 根元素应存在");

    // 启动错误页 = #app 下直接挂 <pre>（P4.5 之后为 textContent）。若 renderer
    // 启动即崩，会走到该错误页。
    const hasError = await cdpEval(
      page,
      "!!(document.getElementById('app') && document.getElementById('app').querySelector('pre'))",
    );
    assert.equal(hasError, false, "不应出现启动错误页（<pre> 错误块）");
  } finally {
    proc.kill("SIGTERM");
    await sleep(300);
    try {
      proc.kill("SIGKILL");
    } catch {
      /* already dead */
    }
  }
});
