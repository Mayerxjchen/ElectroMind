/** 七: Desktop Skills Manager —— CDP 端到端完整操作链（对打包 .app）。
 *
 * 流程：启动 .app → 打开 Skills 面板 → 安装本地 fixture → 验证 Untrusted
 * → Trust → 验证 Trusted → 更新到 v2（内容变化）→ Revoke → Remove →
 * 重启 .app → 验证删除状态已持久化。不依赖外网（本地 fixture）。
 *
 * 环境：ELECTROMIND_STANDALONE_APP=<path-to-.app>（缺省自动探测 release/）。
 */

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import {
  existsSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";

const DESKTOP = path.resolve(import.meta.dirname, "..");
const REPO = path.resolve(import.meta.dirname, "..", "..", "..");
const FIXTURES = path.join(REPO, "tests", "fixtures", "skills");

function findApp() {
  const explicit = process.env.ELECTROMIND_STANDALONE_APP;
  if (explicit) return explicit;
  const release = path.join(DESKTOP, "release");
  const apps = readdirSync(release)
    .filter((f) => f.endsWith(".app"))
    .map((f) => path.join(release, f));
  if (apps.length === 0) {
    for (const sub of readdirSync(release)) {
      const subPath = path.join(release, sub);
      if (!statSync(subPath).isDirectory()) continue;
      const inner = readdirSync(subPath).filter((f) => f.endsWith(".app"));
      if (inner.length) apps.push(path.join(subPath, inner[0]));
    }
  }
  apps.sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs);
  assert.ok(apps.length >= 1, `release/ 下应有 .app，实际: ${apps}`);
  return apps[0];
}

const APP = findApp();
const APP_BIN = path.join(APP, "Contents", "MacOS", "electromind Desktop");

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function fetchJson(url) {
  const res = await fetch(url);
  return res.json();
}

let wsSeq = 0;

async function cdpEval(port, expression) {
  const targets = await fetchJson(`http://127.0.0.1:${port}/json`);
  const page = targets.find(
    (t) =>
      t.type === "page" &&
      t.url !== "about:blank" &&
      (t.url || "").includes("index.html"),
  );
  assert.ok(page, `应存在 index.html page target`);
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });
  const id = ++wsSeq;
  const result = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("cdp eval timeout")), 10_000);
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
        params: { expression, returnByValue: true, awaitPromise: true },
      }),
    );
  });
  ws.close();
  if (result.exceptionDetails) {
    throw new Error(`cdp eval 异常: ${JSON.stringify(result.exceptionDetails).slice(0, 300)}`);
  }
  return result.result?.value;
}

async function poll(port, expr, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  let last;
  while (Date.now() < deadline) {
    try {
      last = await cdpEval(port, expr);
      if (last) return last;
    } catch {
      /* renderer 可能还在启动 */
    }
    await sleep(400);
  }
  return last;
}

function launch(home) {
  const port = 9600 + Math.floor(Math.random() * 200);
  const env = {
    ...process.env,
    HOME: home,
    ELECTROMIND_HOME: path.join(home, ".electromind"),
    DEEPSEEK_API_KEY: "sk-skills-cdp-smoke",
    VIRTUAL_ENV: "",
    PYTHONPATH: "",
    ELECTROMIND_STANDALONE_APP: "",
  };
  const proc = spawn(APP_BIN, [`--remote-debugging-port=${port}`, "--no-sandbox"], {
    env,
    stdio: ["ignore", "ignore", "pipe"],
  });
  let stderr = "";
  proc.stderr.on("data", (d) => {
    stderr += d;
  });
  return { proc, port, stderr: () => stderr };
}

async function stop(proc) {
  proc.kill("SIGTERM");
  await sleep(500);
  try {
    proc.kill("SIGKILL");
  } catch {
    /* already dead */
  }
  await sleep(700);
}

/** 等 bridge 就绪并打开 Skills 面板（toggle 语义，必要时点两次） */
async function openSkillsPanel(app) {
  const bridge = await poll(
    app.port,
    "window.desktop.getRuntimeState().then(s => s.bridgeActive && s.status === 'ready')",
    60_000,
  );
  assert.ok(bridge, `bridge 应就绪; stderr=${app.stderr().slice(-300)}`);

  await cdpEval(app.port, `document.querySelector('[data-skills-open]')?.click()`);
  let panelOpen = await poll(
    app.port,
    `!!document.querySelector('[data-skills-panel]') && !document.querySelector('[data-skills-panel]').hidden`,
    5000,
  );
  if (!panelOpen) {
    await cdpEval(app.port, `document.querySelector('[data-skills-open]')?.click()`);
    panelOpen = await poll(
      app.port,
      `!!document.querySelector('[data-skills-panel]') && !document.querySelector('[data-skills-panel]').hidden`,
      5000,
    );
  }
  assert.ok(panelOpen, "Skills 面板应打开");
}

test("skills manager: install → trust → update → revoke → remove → restart persistence", async () => {
  const home = mkdtempSync(path.join(tmpdir(), "skills-cdp-"));
  const installedRoot = path.join(home, ".electromind", "skills", "demo-skill");
  const manifestPath = path.join(installedRoot, ".electromind-install.json");

  // ── 第一段：安装 → 信任 → 更新 → 撤销 → 移除 ──
  let app = launch(home);
  try {
    await openSkillsPanel(app);

    // 安装本地 fixture v1（untrusted）
    await cdpEval(
      app.port,
      `(() => {
        const i = document.querySelector('[data-skills-install-source]');
        i.value = ${JSON.stringify(path.join(FIXTURES, "demo-skill-v1"))};
        document.querySelector('[data-skills-install]').click();
        return true;
      })()`,
    );
    const installed = await poll(
      app.port,
      `[...document.querySelectorAll('.skill-item')].some(el => el.textContent.includes('demo-skill'))`,
    );
    assert.ok(installed, "demo-skill 应出现在面板");
    assert.ok(existsSync(installedRoot), "安装目录应落盘");

    // 安装不自动信任 → 显示"信任"按钮
    const untrusted = await poll(
      app.port,
      `[...document.querySelectorAll('[data-skill-trust]')].some(b => b.textContent.includes('信任') && !b.dataset.trusted)`,
    );
    assert.ok(untrusted, "untrusted 状态应显示「信任」按钮");

    // Trust → 显示"撤销信任"；manifest 落盘 trust_granted=true
    await cdpEval(app.port, `[...document.querySelectorAll('[data-skill-trust]')].find(b => b.textContent.includes('信任'))?.click()`);
    const trusted = await poll(
      app.port,
      `[...document.querySelectorAll('[data-skill-trust]')].some(b => b.textContent.includes('撤销信任'))`,
    );
    assert.ok(trusted, "Trust 后应显示「撤销信任」");
    const manifestAfterTrust = JSON.parse(readFileSync(manifestPath, "utf8"));
    assert.equal(manifestAfterTrust.trust_granted, true, "Trust 应落盘");

    // Update：把记录来源推进到 v2 → 点击更新 → SKILL.md 内容变化
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    manifest.source = path.join(FIXTURES, "demo-skill-v2");
    writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
    await cdpEval(app.port, `document.querySelector('[data-skill-update="demo-skill"]')?.click()`);
    const updated = await poll(
      app.port,
      `(async () => { await new Promise(r => setTimeout(r, 300)); return true; })()`,
      2000,
    );
    assert.ok(updated);
    await sleep(1500); // 等 wire 更新完成 + 面板刷新
    const body = readFileSync(path.join(installedRoot, "SKILL.md"), "utf8");
    assert.match(body, /body v2/, "Update 后内容应为 v2");

    // Revoke → 回到"信任"；manifest trust_granted=false
    await cdpEval(app.port, `[...document.querySelectorAll('[data-skill-trust][data-trusted="1"]')].find(b => b.textContent.includes('撤销信任'))?.click()`);
    const revoked = await poll(
      app.port,
      `[...document.querySelectorAll('[data-skill-trust]')].some(b => b.textContent.includes('信任') && !b.dataset.trusted)`,
    );
    assert.ok(revoked, "Revoke 后应回到「信任」");
    const manifestAfterRevoke = JSON.parse(readFileSync(manifestPath, "utf8"));
    assert.equal(manifestAfterRevoke.trust_granted, false, "Revoke 应落盘");

    // Remove（绕过 confirm）→ 面板消失 + 目录删除
    await cdpEval(app.port, `window.confirm = () => true; document.querySelector('[data-skill-remove="demo-skill"]')?.click()`);
    const removed = await poll(
      app.port,
      `![...document.querySelectorAll('.skill-item')].some(el => el.textContent.includes('demo-skill'))`,
    );
    assert.ok(removed, "移除后面板不应再显示 demo-skill");
    assert.ok(!existsSync(installedRoot), "安装目录应删除");

    await stop(app.proc);
  } catch (err) {
    await stop(app.proc);
    throw err;
  }

  // ── 第二段：重启后删除状态已持久化 ──
  app = launch(home);
  try {
    await openSkillsPanel(app);
    const stillAbsent = await poll(
      app.port,
      `![...document.querySelectorAll('.skill-item')].some(el => el.textContent.includes('demo-skill'))`,
    );
    assert.ok(stillAbsent, "重启后 demo-skill 应仍为已移除状态");
    assert.ok(!existsSync(installedRoot), "重启后安装目录不应复活");
    await stop(app.proc);
  } catch (err) {
    await stop(app.proc);
    throw err;
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});
