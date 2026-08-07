#!/usr/bin/env node
/** P0 基线三尺寸截图 —— 1024×768 / 1280×720 / 1440×900。
 *
 * 对打包应用（或 dist/ + electron）经 CDP 强制视口尺寸后
 * Page.captureScreenshot 存 PNG，作为桌面稳定性对比基线
 * （spec 2026-08-07-desktop-stability-refactor.md P0：三尺寸截图）。
 *
 * 用法：
 *   node scripts/p0-baseline-screenshots.mjs [--out <dir>] [--port <port>]
 *
 * 环境：
 *   ELECTROMIND_STANDALONE_APP=<path-to-.app>  指定打包应用（缺省自动探测 release/）
 *
 * 输出：<out>/baseline-<width>x<height>.png，缺省 out=release/p0-baseline/。
 */

import { spawn } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const DESKTOP = path.resolve(import.meta.dirname, "..");
const SIZES = [
  { width: 1024, height: 768 },
  { width: 1280, height: 720 },
  { width: 1440, height: 900 },
];

function arg(name, fallback) {
  const idx = process.argv.indexOf(`--${name}`);
  return idx >= 0 && process.argv[idx + 1] ? process.argv[idx + 1] : fallback;
}

const outDir = arg("out", path.join(DESKTOP, "release", "p0-baseline"));
const port = Number(arg("port", 9600 + Math.floor(Math.random() * 100)));

// ── 打包应用探测（与 standalone-smoke 一致：取最新 .app）──────────────
function findApp() {
  const explicit = process.env.ELECTROMIND_STANDALONE_APP;
  if (explicit) {
    if (!existsSync(explicit)) {
      throw new Error(`ELECTROMIND_STANDALONE_APP 不存在: ${explicit}`);
    }
    return explicit;
  }
  const release = path.join(DESKTOP, "release");
  if (!existsSync(release)) {
    throw new Error("release/ 不存在 —— 请先打包");
  }
  const apps = [];
  for (const f of readdirSync(release)) {
    const p = path.join(release, f);
    if (f.endsWith(".app") && statSync(p).isDirectory()) {
      apps.push(p);
    } else if (statSync(p).isDirectory()) {
      for (const inner of readdirSync(p)) {
        if (inner.endsWith(".app")) {
          apps.push(path.join(p, inner));
        }
      }
    }
  }
  apps.sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs);
  if (apps.length === 0) {
    throw new Error("release/ 下无 .app");
  }
  return apps[0];
}

const APP = findApp();
const APP_BIN = path.join(APP, "Contents", "MacOS", "electromind Desktop");
const home = mkdtempSync(path.join(tmpdir(), "p0-shot-"));

/** 干净环境：隔离 HOME/ELECTROMIND_HOME，避免污染用户真实配置；
 *  特征配置缺失 → 全部 Feature Flag fail-closed=false → 旧桌面基线行为。 */
function cleanEnv() {
  return {
    ...process.env,
    HOME: home,
    ELECTROMIND_HOME: path.join(home, ".electromind"),
    DEEPSEEK_API_KEY: "sk-p0-baseline",
    ELECTROMIND_STANDALONE_APP: "",
  };
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function fetchJson(url) {
  const res = await fetch(url);
  return res.json();
}

/** 简易 CDP 客户端：连接后逐条发请求，按 id 配对响应。 */
function cdpSession(wsUrl) {
  const ws = new WebSocket(wsUrl);
  const pending = new Map();
  let nextId = 1;
  const ready = new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = (e) => reject(new Error(`cdp open error: ${e.message ?? ""}`));
  });
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(`CDP error ${JSON.stringify(msg.error)}`));
      else resolve(msg.result);
    }
  };
  return {
    ready,
    send(method, params = {}) {
      return new Promise((resolve, reject) => {
        const id = nextId++;
        pending.set(id, { resolve, reject });
        ws.send(JSON.stringify({ id, method, params }));
      });
    },
    close() {
      try {
        ws.close();
      } catch {
        /* already closed */
      }
    },
  };
}

async function main() {
  mkdirSync(outDir, { recursive: true });
  const proc = spawn(APP_BIN, [`--remote-debugging-port=${port}`, "--no-sandbox"], {
    env: cleanEnv(),
    stdio: ["ignore", "ignore", "pipe"],
  });
  let stderr = "";
  proc.stderr.on("data", (d) => {
    stderr += d;
  });

  try {
    // 等待真实应用页 target（type=page 且 URL 含 index.html）
    let target = null;
    const targetDeadline = Date.now() + 30_000;
    while (Date.now() < targetDeadline) {
      try {
        const targets = await fetchJson(`http://127.0.0.1:${port}/json`);
        target = targets.find(
          (t) =>
            t.type === "page" &&
            t.url !== "about:blank" &&
            (t.url || "").includes("index.html"),
        );
        if (target) break;
      } catch {
        /* not up yet */
      }
      await sleep(300);
    }
    if (!target) {
      throw new Error(`未找到 index.html target；stderr=${stderr.slice(-500)}`);
    }

    const cdp = cdpSession(target.webSocketDebuggerUrl);
    await cdp.ready;

    // 等待 React 外壳 boot 完成（与 cdp-smoke 同一判定）
    let bootDone = false;
    const bootDeadline = Date.now() + 20_000;
    while (Date.now() < bootDeadline) {
      try {
        const r = await cdp.send("Runtime.evaluate", {
          expression: "document.documentElement.dataset.boot === 'done'",
          returnByValue: true,
        });
        bootDone = r.result.value === true;
      } catch {
        /* renderer 未就绪 */
      }
      if (bootDone) break;
      await sleep(300);
    }
    if (!bootDone) {
      throw new Error(`boot 未完成；stderr=${stderr.slice(-500)}`);
    }

    // 截图：先 Emulation 强制视口尺寸，再 captureScreenshot
    for (const { width, height } of SIZES) {
      await cdp.send("Emulation.setDeviceMetricsOverride", {
        width,
        height,
        deviceScaleFactor: 1,
        mobile: false,
      });
      await sleep(600); // 让布局/滚动稳定
      const shot = await cdp.send("Page.captureScreenshot", { format: "png" });
      const png = Buffer.from(shot.data, "base64");
      const file = path.join(outDir, `baseline-${width}x${height}.png`);
      writeFileSync(file, png);
      console.log(`  ✅ ${width}x${height} → ${file} (${png.length} bytes)`);
    }
    cdp.close();
  } finally {
    proc.kill("SIGTERM");
    await sleep(400);
    try {
      proc.kill("SIGKILL");
    } catch {
      /* already dead */
    }
    await new Promise((r) => setTimeout(r, 300));
  }
}

main().then(
  () => process.exit(0),
  (err) => {
    console.error(`❌ ${err.message}`);
    process.exit(1);
  },
);
