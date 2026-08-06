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
  assert.ok(page, `应存在 index.html page target；targets=${JSON.stringify(targets.map((t) => ({ type: t.type, url: t.url })))}`);
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
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stderr = "";
  let stdout = "";
  proc.stderr.on("data", (d) => {
    stderr += d;
  });
  proc.stdout.on("data", (d) => {
    stdout += d;
  });
  return { proc, port, stderr: () => stderr, stdout: () => stdout };
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

test("skills manager: install → trust → update → revoke → remove → restart persistence", async () => {
  const home = mkdtempSync(path.join(tmpdir(), "skills-cdp-"));
  const installedRoot = path.join(home, ".electromind", "skills", "demo-skill");
  const manifestPath = path.join(installedRoot, ".electromind-install.json");

  // ── 第一段：安装 → 信任 → 更新 → 撤销 → 移除 ──
  let app = launch(home);
  try {
    // 等 bridge 就绪
    const bridge = await poll(
      app.port,
      "window.desktop.getRuntimeState().then(s => s.bridgeActive && s.status === 'ready')",
      60_000,
    );
    assert.ok(bridge, `bridge 应就绪; stderr=${app.stderr().slice(-300)}`);

    // 打开 Skills 面板（按钮是 toggle 语义：初始态未知，必要时点两次）
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

    // 挂钩渲染器事件流：agent 的任何事件都应到达 renderer
    const evtProbe = await cdpEval(
      app.port,
      `(async () => {
        window.__evtLog = [];
        window.__catalogNames = [];
        window.desktop.onAgentEvent((e) => {
          const inner = e && e.event ? e.event : e;
          window.__evtLog.push(inner.method);
          if (inner.method === 'skills/list' && inner.params && Array.isArray(inner.params.skills)) {
            window.__catalogNames = inner.params.skills.map((s) => s.name + ':' + (s.scope || '?') + ':' + (s.trust_state || '?'));
          }
        });
        await new Promise((r) => setTimeout(r, 2000));
        return JSON.stringify(window.__evtLog);
      })()`,
    );
    console.log(`DIAG rendererEvents=${evtProbe}`);
    // 安装本地 fixture v1（untrusted）。单次 eval 内完成 设值→点击→回读，
    // 避免跨 eval 的 DOM/时序混淆。
    const clickProbe = await cdpEval(
      app.port,
      `(async () => {
        window.__sendErr = '';
        window.__evtLog = [];
        window.__catalogNames = [];
        window.desktop.onAgentEvent((e) => {
          const inner = e && e.event ? e.event : e;
          window.__evtLog.push(inner.method);
          if (inner.method === 'skills/list' && inner.params && Array.isArray(inner.params.skills)) {
            window.__catalogNames = inner.params.skills.map((s) => s.name + ':' + (s.scope || '?') + ':' + (s.trust_state || '?'));
          }
        });
        window.desktop.sendWireCommand({
          cmd: 'skills/install',
          source: ${JSON.stringify(path.join(FIXTURES, "demo-skill-v1"))},
          trust: false,
          scope: 'user',
        }).catch((e) => { window.__sendErr = String(e); });
        const i = document.querySelector('[data-skills-install-source]');
        const btn = document.querySelector('[data-skills-install]');
        i.value = ${JSON.stringify(path.join(FIXTURES, "demo-skill-v1"))};
        btn.click();
        await new Promise((r) => setTimeout(r, 2500));
        return JSON.stringify({
          v: i.value,
          sendErr: window.__sendErr || '',
          events: window.__evtLog,
          catalog: window.__catalogNames,
          btnText: btn.textContent,
        });
      })()`,
    );
    console.log(`DIAG clickProbe=${clickProbe}`);
    console.log(`DIAG mainStdout=${app.stdout().slice(-800)}`);
    const installed = await poll(
      app.port,
      `[...document.querySelectorAll('.skill-item')].some(el => el.textContent.includes('demo-skill'))`,
    );
    if (!installed) {
      const navType = await cdpEval(
        app.port,
        `(performance.getEntriesByType('navigation')[0]?.type || '') + ' appChildren=' + (document.getElementById('app')?.childElementCount ?? -1) + ' boot=' + (document.documentElement.dataset.boot || '')`,
      );
      console.log(`DIAG nav=${navType}`);
      const bodySnap = await cdpEval(
        app.port,
        `(() => {
          const b = document.body;
          return JSON.stringify({
            bodyChildren: b ? b.children.length : -1,
            bodyHtml: b ? b.innerHTML.slice(0, 300) : '',
            skillsOpen: !!document.querySelector('[data-skills-open]'),
            appChildren: document.getElementById('app')?.children.length ?? -1,
          });
        })()`,
      );
      console.log(`DIAG body=${bodySnap}`);
      const panelSnap = await cdpEval(
        app.port,
        `(() => {
          const p = document.querySelector('[data-skills-panel]');
          return JSON.stringify({
            found: !!p,
            outer: p ? p.outerHTML.slice(0, 400) : '',
            inBody: (document.body.innerHTML || '').includes('skills-panel'),
          });
        })()`,
      );
      console.log(`DIAG panelSnap=${panelSnap}`);
      const targetsSnap = await fetchJson(`http://127.0.0.1:${app.port}/json`).then((t) =>
        JSON.stringify(t.map((x) => ({ type: x.type, url: (x.url || "").slice(0, 80) }))),
      );
      console.log(`DIAG targets=${targetsSnap}`);
      const lenSnap = await cdpEval(
        app.port,
        `JSON.stringify((() => {
          const p = document.querySelector('[data-skills-panel]');
          return { il: p ? p.innerHTML.length : -1, ol: p ? p.outerHTML.length : -1, installBtn: !!document.querySelector('[data-skills-install]'), list: (document.querySelector('[data-skills-list]')?.innerHTML || '').length };
        })())`,
      );
      console.log(`DIAG lens=${lenSnap}`);
      const panelHtml = await cdpEval(
        app.port,
        `(document.querySelector('[data-skills-panel]')?.innerHTML || '').slice(0, 900)`,
      );
      const errors = await cdpEval(
        app.port,
        `[...document.querySelectorAll('.toast, [data-toast]')].map(e => e.textContent).join(' | ').slice(0, 400)`,
      );
      const logDir = path.join(home, ".electromind", "logs");
      const logs = readdirSync(logDir).map((f) => {
        const p = path.join(logDir, f);
        return `${f}: ${readFileSync(p, "utf8").replace(/\n/g, " ⏎ ")}`;
      });
      console.log(
        `DIAG panel=${panelHtml}\nDIAG toasts=${errors}\nDIAG disk=${existsSync(installedRoot)}\nDIAG stderr=${app.stderr().slice(-400)}\nDIAG logs=${logs.join("\nDIAG   ")}`,
      );
    }
    assert.ok(installed, "demo-skill 应出现在面板");
    assert.ok(existsSync(installedRoot), "安装目录应落盘");

    // 安装不自动信任 → 显示"信任"按钮
    const untrusted = await poll(
      app.port,
      `[...document.querySelectorAll('[data-skill-trust]')].some(b => b.textContent.includes('信任') && !b.dataset.trusted)`,
    );
    assert.ok(untrusted, "untrusted 状态应显示「信任」按钮");

    // Trust → 显示"撤销信任"
    const trustProbe = await cdpEval(
      app.port,
      `(async () => {
        window.__catalogNames = [];
        window.__allEvents = [];
        window.desktop.onAgentEvent((e) => {
          const inner = e && e.event ? e.event : e;
          window.__allEvents.push(inner.method);
          if ((inner.method === 'skills/list' || inner.method === 'skills/reload') && inner.params && Array.isArray(inner.params.skills)) {
            const demo = inner.params.skills.find((x) => x.name === 'demo-skill');
            window.__catalogNames.push((inner.method === 'skills/reload' ? 'RL:' : 'L:') + (demo ? demo.trust_state : '?') + ':gen' + inner.params.generation);
          }
          if (inner.method === 'Error') { window.__lastErr = inner.params ? inner.params.message : JSON.stringify(inner); }
        });
        const target = [...document.querySelectorAll('[data-skill-trust]')].find((b) => b.textContent.includes('信任'));
        const clicked = target ? (target.click(), true) : false;
        await new Promise((r) => setTimeout(r, 6000));
        return JSON.stringify({
          clicked,
          catalog: window.__catalogNames,
          err: window.__lastErr || '',
          events: window.__allEvents,
          buttons: [...document.querySelectorAll('[data-skill-trust]')].map((b) => b.textContent.trim()),
        });
      })()`,
    );
    console.log(`DIAG trustProbe=${trustProbe}`);
    const manifestAfterTrust = existsSync(manifestPath)
      ? JSON.parse(readFileSync(manifestPath, "utf8")).trust_granted
      : "NO-MANIFEST";
    console.log(`DIAG manifestAfterTrust=${manifestAfterTrust}`);
    const trusted = await poll(
      app.port,
      `[...document.querySelectorAll('[data-skill-trust]')].some(b => b.textContent.includes('撤销信任'))`,
    );
    assert.ok(trusted, "Trust 后应显示「撤销信任」");

    // Update：把记录来源推进到 v2 → 点击更新 → 内容变化
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

    // Revoke
    await cdpEval(app.port, `[...document.querySelectorAll('[data-skill-trust][data-trusted="1"]')].find(b => b.textContent.includes('撤销信任'))?.click()`);
    const revoked = await poll(
      app.port,
      `[...document.querySelectorAll('[data-skill-trust]')].some(b => b.textContent.includes('信任') && !b.dataset.trusted)`,
    );
    assert.ok(revoked, "Revoke 后应回到「信任」");
    const manifestAfterRevoke = JSON.parse(readFileSync(manifestPath, "utf8"));
    assert.equal(manifestAfterRevoke.trust_granted, false, "Revoke 应落盘 trust_granted=false");

    // Remove（绕过 confirm）
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
    const bridge = await poll(
      app.port,
      "window.desktop.getRuntimeState().then(s => s.bridgeActive && s.status === 'ready')",
      60_000,
    );
    assert.ok(bridge, `重启后 bridge 应就绪; stderr=${app.stderr().slice(-300)}`);
    await cdpEval(app.port, `document.querySelector('[data-skills-open]')?.click()`);
    await poll(
      app.port,
      `!!document.querySelector('[data-skills-panel]') && !document.querySelector('[data-skills-panel]').hidden`,
    );
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
