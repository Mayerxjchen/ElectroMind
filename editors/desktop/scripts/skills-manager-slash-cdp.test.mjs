/** P3 阶段 2: /skill 管理命令 —— CDP 端到端完整操作链（对打包 .app）。
 *
 * 与 skills-manager-cdp.test.mjs 同流程，但驱动方式改为 Slash 流
 * （/skill add|trust|update|revoke|remove 经 Command Registry 执行），
 * 证明新路径可替换旧 Skills Manager 的按钮 CDP 链（特征对等）：
 *   seed flags → 启动 .app → /skill add 本地 fixture v1（untrusted）
 *   → /skill trust → 验证 manifest trust_granted → /skill update 到 v2
 *   → /skill revoke → /skill remove（自动确认）→ 重启验证持久化。
 *
 * 验收点：
 *   - slash 管理命令在无活动会话时仍可用（Skills Manager 与会话解耦）
 *   - 每个 /skill 命令发出的 wire 链与旧面板按钮等价（skills/install、
 *     skills/trust、skills/update、skills/remove，后端操作后自吐目录）
 *   - 移除经 confirm-bridge 二次确认（不绕过）
 *   - 重启后删除状态持久化
 *
 * 环境：ELECTROMIND_STANDALONE_APP=<path-to-.app>（缺省自动探测 release/）。
 * 需先 npm run compile && npm run package。
 */

import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import {
  existsSync,
  mkdirSync,
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

/** 预置 Feature Flags：slash_skill_v2=true（legacy 面板保留 true，兼容期）。 */
function seedFeatureFlags(home) {
  const dir = path.join(home, ".electromind");
  mkdirSync(dir, { recursive: true });
  writeFileSync(
    path.join(dir, "desktop.json"),
    JSON.stringify(
      {
        features: { slash_skill_v2: true, legacy_skills_panel: true },
      },
      null,
      2,
    ),
  );
}

/** 等 bridge 就绪 + registry 暴露（slash 命令执行入口）。 */
async function waitReady(app) {
  const ready = await poll(
    app.port,
    `(async () => {
      const r = await window.desktop.getRuntimeState().then(s => s.bridgeActive && s.status === 'ready').catch(() => false);
      return r && !!window.__electromindCommandRegistry;
    })()`,
    60_000,
  );
  assert.ok(ready, `bridge + registry 应就绪; stderr=${app.stderr().slice(-300)}`);
}

/** 经 /skill <verb> <rest> 驱动（skill.root → 管理动词委派 → wire）。
 *  无活动会话的 ctx（Skills Manager 与会话解耦）。 */
async function slash(app, verb, rest = "") {
  const args = JSON.stringify({ name: verb, rest, text: `${verb} ${rest}`.trim() });
  const res = await cdpEval(
    app.port,
    `window.__electromindCommandRegistry.execute("skill.root", { store: { getActiveThreadId: () => null } }, ${args})`,
  );
  assert.equal(res?.ok, true, `/skill ${verb} ${rest} 应执行成功: ${JSON.stringify(res)}`);
  return res;
}

/** 自动放行 confirm-bridge（/skill remove 的二次确认）。 */
async function armAutoConfirm(app) {
  await cdpEval(
    app.port,
    `(() => {
      if (window.__skillSlashCdpAutoConfirm) return true;
      window.__skillSlashCdpAutoConfirm = true;
      window.addEventListener("electromind:confirm-request", (e) => {
        window.dispatchEvent(new CustomEvent("electromind:confirm-resolved", {
          detail: { requestId: e.detail.requestId, ok: true },
        }));
      });
      return true;
    })()`,
  );
}

/** 目录是否已含某 Skill（skills/list 反馈 → catalog → DOM 行）。 */
function skillInCatalog(port, name) {
  return poll(
    port,
    `[...document.querySelectorAll('.skill-item')].some(el => el.textContent.includes(${JSON.stringify(name)}))`,
  );
}

test("skill slash flow: add → trust → update → revoke → remove → restart persistence", async () => {
  const home = mkdtempSync(path.join(tmpdir(), "skills-slash-cdp-"));
  seedFeatureFlags(home);
  const installedRoot = path.join(home, ".electromind", "skills", "demo-skill");
  const manifestPath = path.join(installedRoot, ".electromind-install.json");

  // ── 第一段：add → trust → update → revoke → remove ──
  let app = launch(home);
  try {
    await waitReady(app);

    // /skill add 本地 fixture v1（不 --trust → 安装不自动信任）
    await slash(app, "add", path.join(FIXTURES, "demo-skill-v1"));
    assert.ok(await skillInCatalog(app.port, "demo-skill"), "demo-skill 应出现在 catalog");
    assert.ok(existsSync(installedRoot), "安装目录应落盘");
    const manifestAfterAdd = JSON.parse(readFileSync(manifestPath, "utf8"));
    assert.equal(manifestAfterAdd.trust_granted, false, "安装默认不信任");

    // /skill trust → manifest 落盘 trust_granted=true（宿主轮询 manifest）
    await slash(app, "trust", "demo-skill");
    await sleep(1200);
    const manifestAfterTrust = JSON.parse(readFileSync(manifestPath, "utf8"));
    assert.equal(manifestAfterTrust.trust_granted, true, "Trust 应落盘");

    // /skill update：把记录来源推进到 v2 → SKILL.md 内容变化
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    manifest.source = path.join(FIXTURES, "demo-skill-v2");
    writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
    await slash(app, "update", "demo-skill");
    await poll(
      app.port,
      `(async () => { await new Promise(r => setTimeout(r, 400)); return true; })()`,
      3000,
    );
    await sleep(1500); // 等 wire 更新完成 + 目录刷新
    const body = readFileSync(path.join(installedRoot, "SKILL.md"), "utf8");
    assert.match(body, /body v2/, "Update 后内容应为 v2");

    // /skill revoke → manifest trust_granted=false
    await slash(app, "revoke", "demo-skill");
    await sleep(1000);
    const manifestAfterRevoke = JSON.parse(readFileSync(manifestPath, "utf8"));
    assert.equal(manifestAfterRevoke.trust_granted, false, "Revoke 应落盘");

    // /skill remove（自动确认 confirm-bridge）→ 目录删除
    await armAutoConfirm(app);
    await slash(app, "remove", "demo-skill");
    const removed = await poll(
      app.port,
      `![...document.querySelectorAll('.skill-item')].some(el => el.textContent.includes('demo-skill'))`,
    );
    assert.ok(removed, "移除后 catalog 不应再显示 demo-skill");
    assert.ok(!existsSync(installedRoot), "安装目录应删除");

    await stop(app.proc);
  } catch (err) {
    await stop(app.proc);
    throw err;
  }

  // ── 第二段：重启后删除状态已持久化 ──
  app = launch(home);
  try {
    await waitReady(app);
    const stillAbsent = await skillInCatalog(app.port, "demo-skill");
    assert.ok(!stillAbsent, "重启后 demo-skill 应仍为已移除状态");
    assert.ok(!existsSync(installedRoot), "重启后安装目录不应复活");
    await stop(app.proc);
  } catch (err) {
    await stop(app.proc);
    throw err;
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});
