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

/** 只认真实应用页：type=page 且 URL 含 index.html；排除 about:blank
 * （about:blank 的 readyState 也是 complete，直接取第一个 page 会抓到空页）。 */
function isAppTarget(t) {
  return (
    t.type === "page" &&
    t.url !== "about:blank" &&
    (t.url || "").includes("index.html")
  );
}

function targetSummary(targets) {
  return JSON.stringify(
    targets.map((t) => ({ type: t.type, url: t.url })),
  );
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
  let exitCode = null;
  proc.stderr.on("data", (d) => {
    stderr += d;
  });
  proc.on("exit", (code) => {
    exitCode = code;
  });

  let page = null;
  let targets = [];
  try {
    // 等待 CDP endpoint 就绪，且出现真实应用页 target
    const targetDeadline = Date.now() + 30_000;
    while (Date.now() < targetDeadline) {
      try {
        targets = await fetchJson(`http://127.0.0.1:${PORT}/json`);
        page = targets.find(isAppTarget);
        if (page) {
          break;
        }
      } catch {
        /* not up yet */
      }
      await sleep(300);
    }
    assert.ok(
      page,
      `应存在 index.html page target；全部 targets=${targetSummary(targets)}` +
        (stderr ? `；electron stderr=${stderr.slice(-500)}` : ""),
    );

    // #app 挂载轮询（不止看 readyState——about:blank 也是 complete）
    let hasApp = false;
    let ready = "";
    const appDeadline = Date.now() + 20_000;
    while (Date.now() < appDeadline) {
      try {
        ready = await cdpEval(page, "document.readyState");
        hasApp = await cdpEval(page, "!!document.getElementById('app')");
      } catch {
        /* renderer 可能还在启动 */
      }
      if (hasApp) {
        break;
      }
      await sleep(300);
    }

    if (!hasApp) {
      // 失败诊断：DOM 快照 + targets + stderr + exit code
      let html = "";
      try {
        html = await cdpEval(
          page,
          "(document.documentElement?.outerHTML || '').slice(0, 2000)",
        );
      } catch {
        html = "<cdp eval failed>";
      }
      assert.equal(
        hasApp,
        true,
        `#app 根元素应存在；target url=${page.url}, readyState=${ready}` +
          `；targets=${targetSummary(targets)}` +
          `；outerHTML=${html}` +
          (stderr ? `；electron stderr=${stderr.slice(-500)}` : "") +
          (exitCode !== null ? `；electron exit=${exitCode}` : ""),
      );
    }

    // 启动错误页 = #app 的**直接子元素** <pre>（P4.5 之后为 textContent）——
    // 错误 handler 是唯一直接往 #app 挂 <pre> 的代码。onboarding/设置等
    // 正常界面也含 <pre class="setup-cmd">（agent 未安装引导），但它们
    // 包在容器/模态里，不是 #app 直接子元素，不算启动错误。
    // P0: 必须先等 boot 完成再检查 —— renderShell 等待 React 外壳
    // （25×80ms）后才会填充槽位/回退，晚到 ~2.5s 的启动错误不能被漏掉。
    let bootDone = false;
    const bootDeadline = Date.now() + 20_000;
    while (Date.now() < bootDeadline) {
      try {
        bootDone = await cdpEval(
          page,
          "document.documentElement.dataset.boot === 'done'",
        );
      } catch {
        /* not up yet */
      }
      if (bootDone) break;
      await sleep(300);
    }
    assert.equal(
      bootDone,
      true,
      "boot 应完成（html[data-boot=done]）——启动可能仍卡在等待 React 外壳或已出现启动错误",
    );

    const errorText = await cdpEval(
      page,
      "(document.querySelector('#app > pre')?.textContent || '').slice(0, 800)",
    );
    const hasError = !!errorText;
    assert.equal(
      hasError,
      false,
      `不应出现启动错误页（#app 直接子 <pre>）；errorText=${errorText}`,
    );
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
